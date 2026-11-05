"""Migracja 0015: czaty z domyślnym top_n 6 dostają 10; inne wartości bez zmian."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.uow import transaction
from tests.integration.chat.conftest import seed_chat
from tests.integration.db.helpers import alembic_cfg
from tests.integration.db.test_searches_repo import _seed_user

pytestmark = pytest.mark.db

NEW_TOP_N = 10
CUSTOM_TOP_N = 8


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def test_upgrade_sets_default_top_n_to_ten(migrated_db, sm) -> None:
    """Po downgrade do 0014 i ponownym upgrade: top_n 6 → 10, 8 bez zmian."""
    owner = await _seed_user(sm)
    default_chat = await seed_chat(sm, owner, [], top_n=6)
    custom_chat = await seed_chat(sm, owner, [], top_n=CUSTOM_TOP_N)

    cfg = alembic_cfg(migrated_db)
    await asyncio.to_thread(command.downgrade, cfg, "0014")
    await asyncio.to_thread(command.upgrade, cfg, "head")

    async with transaction(sm) as session:
        rows = dict((await session.execute(text("SELECT id, top_n FROM chats"))).all())
    assert rows[default_chat.id] == NEW_TOP_N
    assert rows[custom_chat.id] == CUSTOM_TOP_N
