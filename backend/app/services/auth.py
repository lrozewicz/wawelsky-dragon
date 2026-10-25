"""Usługa uwierzytelniania: login hasłem, sesje refresh, logout, authenticate (kontrakt C8)."""

import logging
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.error_codes import RetCode
from app.core.errors import AuthenticationFailed, OperationNotAllowed, Unauthorized, WDError
from app.core.ids import IdGenerator
from app.core.timeutil import Clock
from app.db.repositories import api_keys as keys_repo
from app.db.repositories import refresh_sessions as sessions_repo
from app.db.repositories import users as users_repo
from app.db.repositories.api_keys import ApiKeyRow
from app.db.repositories.users import UserRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.auth_passwords import hash_password, needs_rehash, verify_password
from app.services.auth_ratelimit import LoginGuard
from app.services.auth_tokens import (
    TokenType,
    decode_token,
    issue_token,
    looks_like_wd_jwt,
    new_refresh_token,
    sha256_hex,
)

logger = logging.getLogger("app.services.auth")


class AccountDisabled(WDError):
    """Konto dezaktywowane — upstream kod 403 (07 §3.1)."""

    code = RetCode.FORBIDDEN
    http_status = 403
    slug = "account_disabled"


MSG_UNAUTHORIZED_LOGIN = "Unauthorized!"
MSG_NOT_REGISTERED = "Email: {email} is not registered!"
MSG_BAD_PASSWORD = "Email and password do not match!"  # noqa: S105 — komunikat upstream, nie hasło
MSG_DISABLED = "This account has been disabled, please contact the administrator!"
MSG_PASSWORD_LOGIN_DISABLED = "Password login is disabled!"  # noqa: S105 — komunikat upstream
API_KEY_TOUCH_MS = 60_000  # last_used_at aktualizowane nie częściej niż co 60 s (07 §5.2)


@dataclass(frozen=True)
class SessionTokens:
    """Tokeny sesji po loginie/refresh (kontrakt C8)."""

    user: UserRow
    access_token: str  # JWT typ=access
    expires_in: int  # sekundy = settings.access_token_ttl_min * 60
    legacy_token: str  # JWT typ=legacy (nagłówek Authorization przy loginie)
    refresh_token: str  # wartość cookie wd_refresh
    refresh_max_age: int  # sekundy = settings.refresh_token_ttl_days * 86400


class AuthService:
    """Rozpoznaje podmiot z tokenu i prowadzi sesje refresh (kontrakt C8)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Clock,
        id_gen: IdGenerator,
        guard: LoginGuard,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._clock = clock
        self._id_gen = id_gen
        self._guard = guard

    async def login_password(
        self, email: str | None, password: str | None, *, ip: str, user_agent: str | None
    ) -> SessionTokens:
        """Login hasłem — kolejność kroków i komunikaty dokładnie wg C8 / upstream."""
        if not email:
            raise AuthenticationFailed(MSG_UNAUTHORIZED_LOGIN)
        if not self._settings.password_login_enabled:
            raise OperationNotAllowed(MSG_PASSWORD_LOGIN_DISABLED)
        await self._guard.hit(ip, email)
        async with transaction(self._sessionmaker) as session:
            user = await users_repo.get_by_email(session, email)
        if user is None:
            self._log_failure("not_registered")
            raise AuthenticationFailed(MSG_NOT_REGISTERED.format(email=email))
        locked = await self._guard.is_locked(email)
        if locked or not verify_password(user.password_hash, password or ""):
            await self._guard.record_failure(email)
            self._log_failure("locked" if locked else "bad_password")
            raise AuthenticationFailed(MSG_BAD_PASSWORD)
        if not user.is_active:
            self._log_failure("disabled")
            raise AccountDisabled(MSG_DISABLED)
        await self._guard.record_success(email)
        if user.password_hash is not None and needs_rehash(user.password_hash):
            async with transaction(self._sessionmaker) as session:
                await users_repo.update_fields(
                    session,
                    user.id,
                    {"password_hash": hash_password(password or "")},
                    self._clock.now_ms(),
                )
        logger.info("login success", extra={"event": "login_success", "user_id": user.id})
        return await self.start_session(user.id, ip=ip, user_agent=user_agent)

    async def start_session(
        self, user_id: str, *, ip: str, user_agent: str | None
    ) -> SessionTokens:
        """Nowa rodzina sesji: last_login_time, wiersz refresh i tokeny access/legacy (C8)."""
        now = self._clock.now_ms()
        refresh = new_refresh_token()
        async with transaction(self._sessionmaker) as session:
            user = await users_repo.get_by_id(session, user_id)
            if user is None:
                raise Unauthorized("Invalid token")
            await users_repo.update_fields(session, user_id, {"last_login_time": now}, now)
            await sessions_repo.insert(
                session,
                session_id=self._id_gen.new_id(),
                user_id=user_id,
                token_hash=sha256_hex(refresh),
                family_id=self._id_gen.new_id(),
                expires_at=now + self._refresh_ttl_ms(),
                user_agent=user_agent,
                ip=ip,
                now_ms=now,
            )
        return SessionTokens(
            user=replace(user, last_login_time=now),
            access_token=self._token(user, "access", now),
            expires_in=self._settings.access_token_ttl_min * 60,
            legacy_token=self._token(user, "legacy", now),
            refresh_token=refresh,
            refresh_max_age=self._settings.refresh_token_ttl_days * 86400,
        )

    async def refresh(
        self, refresh_token: str | None, *, ip: str, user_agent: str | None
    ) -> SessionTokens:
        """Rotacja refresh tokenu w jednej transakcji; reuse unieważnia całą rodzinę
        (C8, 07 §3.2)."""
        if not refresh_token:
            raise Unauthorized("Invalid refresh token")
        now = self._clock.now_ms()
        refresh = new_refresh_token()
        user: UserRow | None = None
        async with transaction(self._sessionmaker) as session:
            row = await sessions_repo.get_by_hash(session, sha256_hex(refresh_token))
            if row is None:
                raise Unauthorized("Invalid refresh token")
            if row.revoked_at is None:
                user = await self._rotate(session, row, refresh, now, ip=ip, user_agent=user_agent)
        if user is None:
            # Reuse albo przegrany wyścig: rodzina w osobnej transakcji,
            # zatwierdzonej przed wyjątkiem.
            await self._revoke_family_on_reuse(row.user_id, row.family_id, now)
            raise Unauthorized("Invalid refresh token")
        return SessionTokens(
            user=user,
            access_token=self._token(user, "access", now),
            expires_in=self._settings.access_token_ttl_min * 60,
            legacy_token=self._token(user, "legacy", now),
            refresh_token=refresh,
            refresh_max_age=self._settings.refresh_token_ttl_days * 86400,
        )

    async def _rotate(  # noqa: PLR0913 — sygnatura z kontraktu WP E1-H1
        self,
        session: AsyncSession,
        row: sessions_repo.RefreshSessionRow,
        refresh: str,
        now: int,
        *,
        ip: str,
        user_agent: str | None,
    ) -> UserRow | None:
        """Unieważnia sesję warunkowo i wstawia następną; None = sesję unieważnił
        równoległy refresh."""
        if row.expires_at <= now:
            raise Unauthorized("Invalid refresh token")
        user = await users_repo.get_by_id(session, row.user_id)
        if user is None or not user.is_active:
            raise Unauthorized("Invalid refresh token")
        # UPDATE … AND revoked_at IS NULL: przegrany czeka na blokadę wiersza i dostaje 0 wierszy.
        if await sessions_repo.revoke(session, row.id, now) == 0:
            return None
        await sessions_repo.insert(
            session,
            session_id=self._id_gen.new_id(),
            user_id=user.id,
            token_hash=sha256_hex(refresh),
            family_id=row.family_id,  # rotacja w tej samej rodzinie
            expires_at=now + self._refresh_ttl_ms(),
            user_agent=user_agent,
            ip=ip,
            now_ms=now,
        )
        return user

    async def logout(
        self, principal: Principal, refresh_token: str | None, *, all_sessions: bool
    ) -> None:
        """Unieważnienie sesji; all_sessions dodatkowo bump token_version (C8, 07 §3.2)."""
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            if refresh_token:
                # Token jest sekretem — właściciela wiersza nie porównujemy (C8).
                row = await sessions_repo.get_by_hash(session, sha256_hex(refresh_token))
                if row is not None:
                    await sessions_repo.revoke(session, row.id, now)
            if all_sessions:
                await users_repo.bump_token_version(session, principal.user_id, now)
                await sessions_repo.revoke_all_for_user(session, principal.user_id, now)

    async def authenticate(self, token: str) -> Principal:
        """Podmiot z tokenu: nasz JWT (access/legacy) albo klucz API (07 §2 p. 3)."""
        if looks_like_wd_jwt(token):
            return await self._authenticate_jwt(token)
        return await self._authenticate_api_key(token)

    async def _authenticate_jwt(self, token: str) -> Principal:
        """JWT: podpis, wygaśnięcie, aktywność i token_version użytkownika (07 §2)."""
        claims = decode_token(self._settings, self._clock.now_ms(), token)
        async with transaction(self._sessionmaker) as session:
            user = await users_repo.get_by_id(session, claims.user_id)
        if user is None or not user.is_active or claims.tv != user.token_version:
            raise Unauthorized("Invalid token")
        auth_kind: Literal["jwt", "legacy_token"] = (
            "jwt" if claims.typ == "access" else "legacy_token"
        )
        return Principal(user.id, user.email, user.is_superuser, user.is_service, auth_kind)

    async def _authenticate_api_key(self, token: str) -> Principal:
        """Klucz API (dowolny nie-JWT): hash, wygaśnięcie, właściciel, dotyk last_used_at."""
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            key: ApiKeyRow | None = await keys_repo.get_active_by_hash(session, sha256_hex(token))
            if key is None:
                raise Unauthorized("Invalid token")
            # K14 §2: wygasły klucz jest nieodróżnialny od nieistniejącego —
            # ten sam wyjątek, komunikat i brak dotknięcia last_used_at.
            if key.expires_at is not None and key.expires_at <= now:
                raise Unauthorized("Invalid token")
            user = await users_repo.get_by_id(session, key.user_id)
            if user is None or not user.is_active:
                raise Unauthorized("Invalid token")
            if key.last_used_at is None or now - key.last_used_at >= API_KEY_TOUCH_MS:
                await keys_repo.touch_last_used(session, key.id, now)
        return Principal(user.id, user.email, user.is_superuser, user.is_service, "api_key", key.id)

    async def _revoke_family_on_reuse(self, user_id: str, family_id: str, now: int) -> None:
        """Reuse: unieważnienie rodziny w osobnej, commitowanej transakcji + log (C8)."""
        async with transaction(self._sessionmaker) as session:
            await sessions_repo.revoke_family(session, family_id, now)
        logger.warning(
            "refresh token reuse",
            extra={"event": "refresh_reuse_detected", "user_id": user_id, "family_id": family_id},
        )

    def _log_failure(self, reason: str) -> None:
        """Log porażki loginu; nigdy hasło ani token (B8)."""
        logger.warning("login failure", extra={"event": "login_failure", "reason": reason})

    def _token(self, user: UserRow, typ: TokenType, now_ms: int) -> str:
        """JWT access/legacy: jti z generatora, tv z konta użytkownika."""
        return issue_token(
            self._settings,
            now_ms,
            user_id=user.id,
            token_version=user.token_version,
            typ=typ,
            jti=self._id_gen.new_id(),
        )

    def _refresh_ttl_ms(self) -> int:
        """TTL refresh tokenu w milisekundach (expires_at wiersza sesji)."""
        return self._settings.refresh_token_ttl_days * 86400 * 1000
