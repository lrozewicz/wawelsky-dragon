"""Testy repozytorium `wd_settings` na MariaDB (CONTRACT E7-1f §5 / DEC-320).

Klucz `instance_id` (32 hex) — generowany przy pierwszym użyciu, potem tylko odczytywany.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import wd_settings as repo
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME_MS

pytestmark = pytest.mark.db

LATER = TIME_MS + 1000
FIRST_ID = "0123456789abcdef0123456789abcdef"
SECOND_ID = "fedcba9876543210fedcba9876543210"


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head (sync — env.py Alembic robi asyncio.run, C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def test_first_call_inserts_new_id(sm: async_sessionmaker[AsyncSession]) -> None:
    """Pierwsze wywołanie wstawia i zwraca `new_id`; wiersz ma `update_time` z zegara (§5)."""
    async with transaction(sm) as session:
        assert (
            await repo.get_or_create_instance_id(session, new_id=FIRST_ID, now_ms=TIME_MS)
            == FIRST_ID
        )
    async with transaction(sm) as session:
        rows = (
            await session.execute(
                text("SELECT name, value, update_time FROM wd_settings WHERE name = 'instance_id'")
            )
        ).all()
    assert rows == [("instance_id", FIRST_ID, TIME_MS)]


async def test_second_call_returns_stored_id(sm: async_sessionmaker[AsyncSession]) -> None:
    """Drugie wywołanie z innym `new_id` zwraca id z pierwszego wstawienia (§5)."""
    async with transaction(sm) as session:
        assert (
            await repo.get_or_create_instance_id(session, new_id=FIRST_ID, now_ms=TIME_MS)
            == FIRST_ID
        )
    async with transaction(sm) as session:
        assert (
            await repo.get_or_create_instance_id(session, new_id=SECOND_ID, now_ms=LATER)
            == FIRST_ID
        )
    async with transaction(sm) as session:
        rows = (await session.execute(text("SELECT COUNT(*) FROM wd_settings"))).scalar_one()
    assert rows == 1


async def test_atomic_get_or_create(sm: async_sessionmaker[AsyncSession]) -> None:
    """Wywołanie na istniejącym wierszu nie zmienia `update_time` (INSERT IGNORE, §5)."""
    async with transaction(sm) as session:
        await repo.get_or_create_instance_id(session, new_id=FIRST_ID, now_ms=TIME_MS)
    async with transaction(sm) as session:
        await repo.get_or_create_instance_id(session, new_id=SECOND_ID, now_ms=LATER)
    async with transaction(sm) as session:
        row = (
            await session.execute(
                text("SELECT value, update_time FROM wd_settings WHERE name = 'instance_id'")
            )
        ).one()
    assert (row[0], row[1]) == (FIRST_ID, TIME_MS)


async def test_id_is_not_validated(sm: async_sessionmaker[AsyncSession]) -> None:
    """Repozytorium nie waliduje kształtu id — zapisuje i zwraca dosłownie (§5)."""
    weird = "nie-hex-" + "z" * 13
    async with transaction(sm) as session:
        assert await repo.get_or_create_instance_id(session, new_id=weird, now_ms=TIME_MS) == weird
    async with transaction(sm) as session:
        assert await repo.get_or_create_instance_id(session, new_id=FIRST_ID, now_ms=LATER) == weird
