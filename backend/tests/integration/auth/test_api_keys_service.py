"""Testy ApiKeyService (brief T4a, kontrakt C7)."""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.repositories import api_keys as keys_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.api_keys import ApiKeyService
from app.services.auth_tokens import sha256_hex
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

pytestmark = pytest.mark.db

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
LOGGER_NAME = "app.services.api_keys"
MIN_TOKEN_LEN = 50  # dolna granica długości tokenu z tabeli briefu


@pytest.fixture
def users_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> UserService:
    return UserService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
def keys(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> ApiKeyService:
    return ApiKeyService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


async def _principal(users_svc: UserService, email: str) -> Principal:
    """Właściciel kluczy: konto w bazie (FK api_keys.user_id) + Principal (wskazówka briefu)."""
    user = await users_svc.create(email=email, password=PASSWORD)
    return Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")


async def test_create_returns_full_token_and_stores_encrypted(
    keys: ApiKeyService,
    users_svc: UserService,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    principal = await _principal(users_svc, "owner@x.pl")
    view = await keys.create(principal, name="n")
    assert view.token.startswith("ragflow-")
    assert len(view.token) >= MIN_TOKEN_LEN
    assert view.prefix == view.token[:16]
    async with transaction(sm) as session:
        row = await keys_repo.get_active_by_hash(session, sha256_hex(view.token))
    assert row is not None
    assert row.token_hash == sha256_hex(view.token)
    assert row.token_enc != view.token.encode()


async def test_list_full_returns_decrypted_tokens(
    keys: ApiKeyService, users_svc: UserService
) -> None:
    principal = await _principal(users_svc, "list@x.pl")
    view = await keys.create(principal, name="n")
    found = await keys.list_full(principal)
    assert len(found) == 1
    assert found[0].id == view.id
    assert found[0].token == view.token


async def test_delete_by_token_sets_revoked_at(
    keys: ApiKeyService,
    users_svc: UserService,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    principal = await _principal(users_svc, "del@x.pl")
    view = await keys.create(principal, name="n")
    assert await keys.delete(principal, view.token) == 1
    assert await keys.list_full(principal) == []
    async with transaction(sm) as session:
        result = await session.execute(
            text("SELECT revoked_at FROM api_keys WHERE id = :id"), {"id": view.id}
        )
        revoked_at = result.scalar_one()
    assert revoked_at is not None


async def test_delete_by_key_id(keys: ApiKeyService, users_svc: UserService) -> None:
    principal = await _principal(users_svc, "byid@x.pl")
    view = await keys.create(principal, name="n")
    assert await keys.delete(principal, view.id) == 1
    assert await keys.list_full(principal) == []


async def test_delete_by_prefix(keys: ApiKeyService, users_svc: UserService) -> None:
    principal = await _principal(users_svc, "byprefix@x.pl")
    view = await keys.create(principal, name="n")
    assert await keys.delete(principal, view.prefix) == 1
    assert await keys.list_full(principal) == []


async def test_delete_foreign_key_is_noop(keys: ApiKeyService, users_svc: UserService) -> None:
    owner = await _principal(users_svc, "own@x.pl")
    stranger = await _principal(users_svc, "stranger@x.pl")
    view = await keys.create(owner, name="n")
    assert await keys.delete(stranger, view.token) == 0
    remaining = await keys.list_full(owner)
    assert len(remaining) == 1


async def test_delete_unknown_is_zero(keys: ApiKeyService, users_svc: UserService) -> None:
    principal = await _principal(users_svc, "unk@x.pl")
    assert await keys.delete(principal, "nieistniejacy") == 0


async def test_create_logs_event_without_token(
    keys: ApiKeyService, users_svc: UserService, caplog: pytest.LogCaptureFixture
) -> None:
    principal = await _principal(users_svc, "log@x.pl")
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        view = await keys.create(principal, name="n")
    created = [r for r in caplog.records if getattr(r, "event", None) == "api_key_created"]
    assert len(created) == 1
    assert created[0].key_id == view.id
    assert view.token not in caplog.text


async def test_compat_profile_none_for_fresh_key(
    keys: ApiKeyService, users_svc: UserService
) -> None:
    """Nowy klucz (kolumna NULL) → compat_profile None (C7)."""
    principal = await _principal(users_svc, "compat1@x.pl")
    view = await keys.create(principal, name="n")
    assert await keys.compat_profile(view.id) is None


async def test_compat_profile_returns_stored_value(
    keys: ApiKeyService, users_svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Po UPDATE kolumny → zwrócona wartość (C7)."""
    principal = await _principal(users_svc, "compat2@x.pl")
    view = await keys.create(principal, name="n")
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE api_keys SET compat_profile = 'ragflow_0_24' WHERE id = :id"),
            {"id": view.id},
        )
    assert await keys.compat_profile(view.id) == "ragflow_0_24"


async def test_compat_profile_unknown_key_is_none(keys: ApiKeyService) -> None:
    """Nieistniejące id → None."""
    assert await keys.compat_profile("nie-ma-takiego-id") is None


async def test_create_stores_expires_at(
    keys: ApiKeyService, users_svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`expires_at` z create trafia do widoku i do kolumny (K14 §1/§2)."""
    expires_at = FrozenClock().now_ms() + 86_400_000
    principal = await _principal(users_svc, "exp@x.pl")
    view = await keys.create(principal, name="n", expires_at=expires_at)
    assert view.expires_at == expires_at
    async with transaction(sm) as session:
        row = await keys_repo.get_active_by_hash(session, sha256_hex(view.token))
    assert row is not None
    assert row.expires_at == expires_at


async def test_create_without_expiry_is_null(
    keys: ApiKeyService, users_svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak `expires_at` (domyślne None) → NULL w kolumnie i w widoku (K14 §1)."""
    principal = await _principal(users_svc, "noexp@x.pl")
    view = await keys.create(principal, name="n")
    assert view.expires_at is None
    async with transaction(sm) as session:
        row = await keys_repo.get_active_by_hash(session, sha256_hex(view.token))
    assert row is not None
    assert row.expires_at is None


async def test_list_for_user_returns_expired_key(
    keys: ApiKeyService, users_svc: UserService
) -> None:
    """Lista nie filtruje po `expires_at` — klucz wygasły nadal widoczny (K14 §3 p. 3)."""
    principal = await _principal(users_svc, "expired-list@x.pl")
    view = await keys.create(principal, name="n", expires_at=1)  # 1 ms po epoce → wygasły
    listed = await keys.list_for_user(principal.user_id)
    assert [item.id for item in listed] == [view.id]
    assert listed[0].expires_at == 1
