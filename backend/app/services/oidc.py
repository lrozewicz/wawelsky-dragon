"""Usługa OIDC: Authorization Code + PKCE S256, cookie stanu, JWKS, provisioning (kontrakt C10)."""

import asyncio
import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import OperationNotAllowed, ValidationFailed
from app.core.ids import IdGenerator
from app.core.timeutil import Clock
from app.db.repositories import users as users_repo
from app.db.repositories.users import UserRow
from app.db.uow import transaction
from app.domain.policy import ensure_admin_remains
from app.services.users import UserService

STATE_TTL_S = 600
DISCOVERY_TTL_MS = 3_600_000
CALLBACK_PATH = "/api/v1/auth/oauth/keycloak/callback"
HTTP_OK = 200
MIN_PRINTABLE_ORD = 32


@dataclass(frozen=True)
class OidcStart:
    """Wynik begin(): URL autoryzacji i wartość cookie stanu wd_oidc."""

    redirect_url: str
    state_cookie: str


class OidcError(Exception):
    """Błąd OIDC — trasa zamienia slug na 302 /?error=<slug> (C10)."""

    def __init__(self, slug: str) -> None:
        super().__init__(slug)
        self.slug = slug


def safe_redirect(value: str | None) -> str:
    """Względny adres powrotu; None/puste → "/" (C10). Inaczej ValidationFailed."""
    if not value:
        return "/"
    no_backslash = "\\" not in value
    no_scheme = "://" not in value
    printable = all(ord(ch) >= MIN_PRINTABLE_ORD for ch in value)
    starts_local = value.startswith("/") and value[1:2] != "/" and value[1:2] != "\\"
    if not (starts_local and no_backslash and no_scheme and printable):
        raise ValidationFailed("Invalid redirect")
    return value


def _csv_set(value: str) -> frozenset[str]:
    """CSV ustawień ("a, b") → zbiór nazw bez pustych."""
    return frozenset({part.strip() for part in value.split(",") if part.strip()})


def _claim_roles(claims: dict[str, Any], client_id: str) -> set[str]:
    """Role z claimów tokenu: realm_access.roles + resource_access[client_id].roles (C10, R5)."""
    roles: set[str] = set()
    realm = claims.get("realm_access")
    if isinstance(realm, dict) and isinstance(realm.get("roles"), list):
        roles.update(str(item) for item in realm["roles"])
    resource = claims.get("resource_access")
    if isinstance(resource, dict):
        mine = resource.get(client_id)
        if isinstance(mine, dict) and isinstance(mine.get("roles"), list):
            roles.update(str(item) for item in mine["roles"])
    return roles


def _claim_groups(claims: dict[str, Any]) -> set[str]:
    """Grupy z claimów tokenu; nazwy bez wiodącego "/" (C10)."""
    groups = claims.get("groups")
    if not isinstance(groups, list):
        return set()
    return {str(item).removeprefix("/") for item in groups}


class OidcService:
    """Przepływ Authorization Code + PKCE po stronie backendu (C10)."""

    def __init__(  # noqa: PLR0913, PLR0917 — sygnatura z kontraktu C10
        self,
        settings: Settings,
        clock: Clock,
        id_gen: IdGenerator,
        http: httpx.AsyncClient,
        users: UserService,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        jwks_lifespan_s: int = 600,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._id_gen = id_gen
        self._http = http
        self._users = users
        self._sessionmaker = sessionmaker
        self._jwks_lifespan_s = jwks_lifespan_s
        self._discovery: tuple[dict[str, Any], int] | None = None
        self._jwks_client: jwt.PyJWKClient | None = None
        self._jwks_uri = ""

    @property
    def enabled(self) -> bool:
        """OIDC włączony, gdy issuer i client_id niepuste (C10)."""
        return bool(self._settings.oidc_issuer and self._settings.oidc_client_id)

    async def discovery(self) -> dict[str, Any]:
        """Dokument discovery z cache na DISCOVERY_TTL_MS; status ≠ 200 → oidc_error."""
        now = self._clock.now_ms()
        if self._discovery is not None and now - self._discovery[1] < DISCOVERY_TTL_MS:
            return self._discovery[0]
        issuer = self._settings.oidc_issuer.rstrip("/")
        response = await self._http.get(f"{issuer}/.well-known/openid-configuration")
        if response.status_code != HTTP_OK:
            raise OidcError("oidc_error")
        data: dict[str, Any] = response.json()
        self._discovery = (data, now)
        return data

    async def begin(self, redirect: str | None) -> OidcStart:
        """Buduje URL autoryzacji z PKCE i podpisane cookie stanu (C10)."""
        data = await self.discovery()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        params = {
            "response_type": "code",
            "client_id": self._settings.oidc_client_id,
            "redirect_uri": self._settings.public_base_url.rstrip("/") + CALLBACK_PATH,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        now_s = self._clock.now_ms() // 1000
        cookie = jwt.encode(
            {
                "typ": "oidc_state",
                "state": state,
                "nonce": nonce,
                "cv": verifier,
                "redirect": safe_redirect(redirect),
                "exp": now_s + STATE_TTL_S,
            },
            self._settings.secret_key.get_secret_value(),
            algorithm="HS256",
        )
        return OidcStart(
            redirect_url=f"{data['authorization_endpoint']}?{urlencode(params)}",
            state_cookie=cookie,
        )

    async def complete(
        self, *, code: str | None, state: str | None, state_cookie: str | None
    ) -> tuple[UserRow, str]:
        """Wymiana kodu na tokeny, weryfikacja id_token, provisioning (C10)."""
        state_claims = self._read_state(state_cookie, state)
        if not code:
            raise OidcError("missing_code")
        data = await self.discovery()
        payload = await self._exchange(data, code, str(state_claims["cv"]))
        id_claims = await self._verified_id_token(payload, data, str(state_claims["nonce"]))
        email = id_claims.get("email")
        if not isinstance(email, str) or not email:
            raise OidcError("email_missing")
        if id_claims.get("email_verified") is not True:
            raise OidcError("email_not_verified")
        is_admin = await self._has_admin_role(id_claims, payload, data)
        row_id = await self._provision(str(id_claims["sub"]), email, id_claims, is_admin)
        fresh = await self._users.get(row_id)
        return fresh, str(state_claims.get("redirect", "/"))

    async def logout_url(self) -> str | None:
        """URL end_session z powrotem na oidc_logout_redirect; None gdy wyłączone (C10)."""
        if not self.enabled or not self._settings.oidc_logout_redirect:
            return None
        data = await self.discovery()
        endpoint = data.get("end_session_endpoint")
        if not endpoint:
            return None
        query = urlencode(
            {
                "client_id": self._settings.oidc_client_id,
                "post_logout_redirect_uri": self._settings.oidc_logout_redirect,
            }
        )
        return f"{endpoint}?{query}"

    async def aclose(self) -> None:
        """Zamyka klienta HTTP (C10)."""
        await self._http.aclose()

    def _read_state(self, state_cookie: str | None, state: str | None) -> dict[str, Any]:
        """Odczyt i walidacja cookie stanu; każda odmowa → invalid_state (C10)."""
        if not state_cookie:
            raise OidcError("invalid_state")
        try:
            claims: dict[str, Any] = jwt.decode(
                state_cookie,
                key=self._settings.secret_key.get_secret_value(),
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
        except jwt.PyJWTError:
            raise OidcError("invalid_state") from None
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or exp * 1000 <= self._clock.now_ms():
            raise OidcError("invalid_state")
        if claims.get("typ") != "oidc_state":
            raise OidcError("invalid_state")
        cookie_state = claims.get("state")
        if (
            not isinstance(cookie_state, str)
            or not isinstance(state, str)
            or not hmac.compare_digest(cookie_state, state)
        ):
            raise OidcError("invalid_state")
        return claims

    async def _exchange(self, data: dict[str, Any], code: str, verifier: str) -> dict[str, Any]:
        """POST token_endpoint z grant_type=authorization_code i code_verifier (C10)."""
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._settings.public_base_url.rstrip("/") + CALLBACK_PATH,
            "client_id": self._settings.oidc_client_id,
            "client_secret": self._settings.oidc_client_secret.get_secret_value(),
            "code_verifier": verifier,
        }
        try:
            response = await self._http.post(str(data["token_endpoint"]), data=form)
        except httpx.HTTPError:
            raise OidcError("token_failed") from None
        if response.status_code != HTTP_OK:
            raise OidcError("token_failed")
        payload: dict[str, Any] = response.json()
        if not payload.get("id_token"):
            raise OidcError("token_failed")
        return payload

    def _jwks_for(self, jwks_uri: str) -> jwt.PyJWKClient:
        """PyJWKClient leniwie, jeden na jwks_uri (C10)."""
        if self._jwks_client is None or self._jwks_uri != jwks_uri:
            self._jwks_client = jwt.PyJWKClient(jwks_uri, lifespan=self._jwks_lifespan_s)
            self._jwks_uri = jwks_uri
        return self._jwks_client

    async def _verified_claims(
        self, token: str, data: dict[str, Any], *, verify_aud: bool
    ) -> dict[str, Any]:
        """Decode tokenu przez JWKS (sync PyJWKClient przez to_thread); issuer z ustawień."""
        client = self._jwks_for(str(data["jwks_uri"]))
        signing_key = await asyncio.to_thread(client.get_signing_key_from_jwt, token)
        return jwt.decode(
            token,
            key=signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=self._settings.oidc_audience or self._settings.oidc_client_id,
            issuer=self._settings.oidc_issuer,
            options={"verify_aud": verify_aud},
        )

    async def _verified_id_token(
        self, payload: dict[str, Any], data: dict[str, Any], nonce: str
    ) -> dict[str, Any]:
        """Weryfikacja id_token (B6): podpis, iss, aud, exp, nonce; błąd → invalid_token."""
        try:
            id_claims = await self._verified_claims(str(payload["id_token"]), data, verify_aud=True)
        except jwt.PyJWTError:
            raise OidcError("invalid_token") from None
        if id_claims.get("nonce") != nonce:
            raise OidcError("invalid_token")
        return id_claims

    async def _has_admin_role(
        self, id_claims: dict[str, Any], payload: dict[str, Any], data: dict[str, Any]
    ) -> bool:
        """Przecięcie ról/grup obu tokenów z oidc_admin_roles i oidc_admin_groups (C10, R5)."""
        access_claims: dict[str, Any] = {}
        access_token = payload.get("access_token")
        if isinstance(access_token, str) and access_token:
            try:  # niepodpisany/nieważny access_token → pomijany (C10)
                access_claims = await self._verified_claims(access_token, data, verify_aud=False)
            except jwt.PyJWTError:
                access_claims = {}
        client_id = self._settings.oidc_client_id
        role_names = _claim_roles(id_claims, client_id) | _claim_roles(access_claims, client_id)
        group_names = _claim_groups(id_claims) | _claim_groups(access_claims)
        return bool(role_names & _csv_set(self._settings.oidc_admin_roles)) or bool(
            group_names & _csv_set(self._settings.oidc_admin_groups)
        )

    async def _provision(self, sub: str, email: str, claims: dict[str, Any], is_admin: bool) -> str:
        """Znalezienie/powiązanie/założenie konta + synchronizacja admina (C10, pkt 4 briefu)."""
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            row = await users_repo.get_by_oidc_sub(session, sub)
            if row is None:
                row = await users_repo.get_by_email(session, email)
                if row is not None:
                    fields: dict[str, object] = {"oidc_sub": sub}
                    if row.auth_source == "local":
                        fields["auth_source"] = "both"
                    await users_repo.update_fields(session, row.id, fields, now)
            if row is None:
                if not self._settings.oidc_auto_register:
                    raise OidcError("registration_disabled")
                user_id = self._id_gen.new_id()
                nickname = str(claims.get("preferred_username") or email.split("@", 1)[0])
                await users_repo.insert(
                    session,
                    user_id=user_id,
                    email=email,
                    nickname=nickname,
                    password_hash=None,
                    auth_source="oidc",
                    oidc_sub=sub,
                    is_superuser=is_admin,
                    is_service=False,
                    now_ms=now,
                )
                row = await users_repo.get_by_id(session, user_id)
            if row is None:
                raise OidcError("oidc_error")
            if not row.is_active:
                raise OidcError("user_inactive")
            changed = row.is_superuser ^ is_admin
            if changed:
                was_admin = all((row.is_superuser, row.is_active))
                stays = all((is_admin, row.is_active))
                others = await users_repo.count_active_superusers(session) - int(was_admin)
                try:
                    ensure_admin_remains(was_admin, stays, others)
                except OperationNotAllowed:
                    raise OidcError("last_admin") from None
                await users_repo.update_fields(session, row.id, {"is_superuser": is_admin}, now)
                await users_repo.bump_token_version(session, row.id, now)
            return row.id
