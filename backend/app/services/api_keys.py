"""Usługa kluczy API: tworzenie, lista z odszyfrowaniem, unieważnianie (kontrakt C7, B4)."""

import logging
import secrets
from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import decrypt, encrypt
from app.core.ids import IdGenerator, is_valid_id
from app.core.timeutil import Clock
from app.db.repositories import api_keys as keys_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.auth_tokens import sha256_hex

logger = logging.getLogger("app.services.api_keys")

# Prefiks w bazie i kryterium wyszukiwania po prefixie (kontrakt C7).
PREFIX_LEN = 16

# Dozwolone profile zgodności (C7) — alias lokalny (usługi nie importują app.api.ragflow).
CompatProfileValue = Literal["ragflow_0_27", "ragflow_0_24"]


def generate_api_key(prefix: str) -> str:
    """Nowy token API: prefix + losowy urlsafe (kontrakt C7)."""
    return prefix + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ApiKeyView:
    """Widok klucza dla API; `token` jawny tylko w wyniku create/list_full."""

    id: str
    token: str
    user_id: str
    name: str | None
    dialog_id: str | None
    source: str | None
    prefix: str
    last_used_at: int | None
    expires_at: int | None
    create_time: int
    update_time: int


def _view(row: keys_repo.ApiKeyRow, token: str) -> ApiKeyView:
    """Wiersz bazy → widok z jawnym tokenem podanym przez wywołującego."""
    return ApiKeyView(
        id=row.id,
        token=token,
        user_id=row.user_id,
        name=row.name,
        dialog_id=row.dialog_id,
        source=row.source,
        prefix=row.prefix,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        create_time=row.create_time,
        update_time=row.update_time,
    )


class ApiKeyService:
    """Klucze API właściciela; zakres zawsze ograniczony do principal.user_id (C7)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Clock,
        id_gen: IdGenerator,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._clock = clock
        self._id_gen = id_gen

    async def create(
        self,
        principal: Principal,
        *,
        name: str | None = None,
        compat_profile: CompatProfileValue | None = None,
        expires_at: int | None = None,
    ) -> ApiKeyView:
        """Nowy klucz: hash, szyfrowana kopia i prefix w bazie, jawny token tylko w widoku.

        `expires_at` (K14 §1) to BIGINT ms UTC albo None (klucz bezterminowy);
        walidacja wartości należy do trasy WD (T2), nie do serwisu.
        """
        token = generate_api_key(self._settings.api_key_prefix)
        key_id = self._id_gen.new_id()
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            await keys_repo.insert(
                session,
                key_id=key_id,
                user_id=principal.user_id,
                token_hash=sha256_hex(token),
                token_enc=encrypt(self._settings.crypto_key.get_secret_value(), token.encode()),
                prefix=token[:PREFIX_LEN],
                name=name,
                compat_profile=compat_profile,
                expires_at=expires_at,
                now_ms=now,
            )
        logger.info("api key created", extra={"event": "api_key_created", "key_id": key_id})
        return ApiKeyView(
            id=key_id,
            token=token,
            user_id=principal.user_id,
            name=name,
            dialog_id=None,
            source=None,
            prefix=token[:PREFIX_LEN],
            last_used_at=None,
            expires_at=expires_at,
            create_time=now,
            update_time=now,
        )

    async def compat_profile(self, api_key_id: str) -> CompatProfileValue | None:
        """Profil zgodności klucza (C7); brak wiersza → None."""
        async with transaction(self._sessionmaker) as session:
            value = await keys_repo.get_compat_profile(session, api_key_id)
        return cast(CompatProfileValue | None, value)

    async def list_full(self, principal: Principal) -> list[ApiKeyView]:
        """Aktywne klucze właściciela z pełnym, odszyfrowanym tokenem (C7)."""
        crypto = self._settings.crypto_key.get_secret_value()
        async with transaction(self._sessionmaker) as session:
            rows = await keys_repo.list_active_for_user(session, principal.user_id)
            return [_view(row, decrypt(crypto, row.token_enc).decode()) for row in rows]

    async def list_for_user(self, user_id: str) -> list[ApiKeyView]:
        """Aktywne klucze użytkownika **bez** tokenu — odszyfrowanie zbędne (kontrakt §4)."""
        async with transaction(self._sessionmaker) as session:
            rows = await keys_repo.list_active_for_user(session, user_id)
        return [_view(row, "") for row in rows]

    async def revoke(self, principal: Principal, token_or_id: str) -> str | None:
        """Unieważnia klucz właściciela po tokenie, id albo prefixie; zwraca id albo None (C7).

        Jednoznaczne dopasowanie do dokładnie jednego aktywnego klucza — inaczej ``None``
        (trasa mapuje to na 404/0; zachowanie ``delete`` bez zmian).
        """
        async with transaction(self._sessionmaker) as session:
            matches = await keys_repo.find_active_for_user(
                session, principal.user_id, token_hash=sha256_hex(token_or_id)
            )
            if not matches and is_valid_id(token_or_id):
                matches = await keys_repo.find_active_for_user(
                    session, principal.user_id, key_id=token_or_id
                )
            if not matches and len(token_or_id) == PREFIX_LEN:
                matches = await keys_repo.find_active_for_user(
                    session, principal.user_id, prefix=token_or_id
                )
            if len(matches) != 1:
                return None
            await keys_repo.revoke(session, matches[0].id, self._clock.now_ms())
        revoked = matches[0]
        logger.info("api key revoked", extra={"event": "api_key_revoked", "key_id": revoked.id})
        return revoked.id

    async def delete(self, principal: Principal, token_or_id: str) -> int:
        """Unieważnienie po tokenie, id albo prefixu; zwraca 1 gdy unieważniono, 0 inaczej."""
        return int(await self.revoke(principal, token_or_id) is not None)

    async def revoke_for_user(self, user_id: str, key_id: str) -> str | None:
        """Unieważnia aktywny klucz o ``key_id`` należący do użytkownika; brak → None (§4)."""
        async with transaction(self._sessionmaker) as session:
            matches = await keys_repo.find_active_for_user(session, user_id, key_id=key_id)
            if len(matches) != 1:
                return None
            await keys_repo.revoke(session, matches[0].id, self._clock.now_ms())
        revoked = matches[0]
        logger.info("api key revoked", extra={"event": "api_key_revoked", "key_id": revoked.id})
        return revoked.id
