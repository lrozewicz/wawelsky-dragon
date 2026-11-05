"""Migracja 0014: czaty i wyszukiwarki z domyślną wagą 0.3 dostają 1.0; inne wagi bez zmian."""

import asyncio
import json
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
from tests.integration.db.test_searches_repo import _insert_search, _seed_user

pytestmark = pytest.mark.db


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


async def test_upgrade_sets_default_weights_to_one(migrated_db, sm) -> None:
    """Po downgrade do 0013 i ponownym upgrade: 0.3 → 1.0, 0.7 bez zmian, brak klucza → 1.0."""
    owner = await _seed_user(sm)
    default_chat = await seed_chat(sm, owner, [], vector_similarity_weight=0.3)
    custom_chat = await seed_chat(sm, owner, [], vector_similarity_weight=0.7)
    s_default = await _insert_search(
        sm, owner, "Domyślna", search_config={"vector_similarity_weight": 0.3}
    )
    s_custom = await _insert_search(
        sm, owner, "Własna", search_config={"vector_similarity_weight": 0.5}
    )
    s_missing = await _insert_search(sm, owner, "Bez klucza", search_config={"chat_id": ""})

    cfg = alembic_cfg(migrated_db)
    await asyncio.to_thread(command.downgrade, cfg, "0013")
    await asyncio.to_thread(command.upgrade, cfg, "head")

    async with transaction(sm) as session:
        chats = dict(
            (await session.execute(text("SELECT id, vector_similarity_weight FROM chats"))).all()
        )
        searches = {
            row[0]: json.loads(row[1])
            for row in (await session.execute(text("SELECT id, search_config FROM searches"))).all()
        }
    assert chats[default_chat.id] == pytest.approx(1.0)
    assert chats[custom_chat.id] == pytest.approx(0.7)
    assert searches[s_default.id]["vector_similarity_weight"] == pytest.approx(1.0)
    assert searches[s_custom.id]["vector_similarity_weight"] == pytest.approx(0.5)
    assert searches[s_missing.id]["vector_similarity_weight"] == pytest.approx(1.0)
    assert searches[s_missing.id]["chat_id"] == ""
