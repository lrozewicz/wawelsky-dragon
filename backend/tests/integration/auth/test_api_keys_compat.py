"""Testy profilu zgodności klucza API (brief T4b, kontrakt C5)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.repositories import api_keys as keys_repo
from app.db.uow import transaction
from app.services.api_keys import ApiKeyService
from app.services.auth_tokens import sha256_hex
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

pytestmark = pytest.mark.db

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście


@pytest.fixture
def users_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> UserService:
    return UserService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
def keys(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> ApiKeyService:
    return ApiKeyService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


async def test_create_stores_compat_profile(
    keys: ApiKeyService,
    users_svc: UserService,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`compat_profile` z argumentu trafia do kolumny i wraca z `compat_profile(id)` (C5)."""
    owner = await users_svc.create(email="owner@x.pl", password=PASSWORD)
    view = await keys.create(users_svc.principal_of(owner), name="n", compat_profile="ragflow_0_24")

    assert await keys.compat_profile(view.id) == "ragflow_0_24"
    async with transaction(sm) as session:
        row = await keys_repo.get_active_by_hash(session, sha256_hex(view.token))
    assert row is not None
    assert row.compat_profile == "ragflow_0_24"


async def test_create_without_compat_profile_stays_null(
    keys: ApiKeyService, users_svc: UserService
) -> None:
    """Istniejące wywołania bez argumentu zapisują NULL (C5 — zgodność wstecz)."""
    owner = await users_svc.create(email="owner2@x.pl", password=PASSWORD)
    view = await keys.create(users_svc.principal_of(owner))

    assert await keys.compat_profile(view.id) is None
