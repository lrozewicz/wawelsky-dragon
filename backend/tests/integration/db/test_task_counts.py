"""Testy repozytorium task_counts na MariaDB: ``count_by_status`` (zadanie T5, kontrakt §4)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.timeutil import now_ms
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import task_counts
from app.db.repositories import tasks as tasks_repo
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

QUEUE_KEYS = ("queued", "running", "dead")


@pytest.fixture
async def db(fresh_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Zmigrowana świeża baza; fabryka sesji, engine zamknięty po teście."""
    await asyncio.to_thread(command.upgrade, alembic_cfg(fresh_db), "head")
    engine = make_engine(fresh_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def _seed(db: async_sessionmaker[AsyncSession], statuses: list[str]) -> None:
    """Wstawia po jednym zadaniu na każdy status (queued przez repo, inne przez UPDATE)."""
    timestamp = now_ms()
    async with transaction(db) as session:
        for status in statuses:
            public_id = uuid.uuid4().hex
            await tasks_repo.insert(
                session,
                public_id=public_id,
                task_type="parse_document",
                payload_json="{}",
                document_id=None,
                dataset_id=None,
                priority=0,
                max_attempts=3,
                digest=None,
                next_attempt_at=timestamp,
                now_ms=timestamp,
            )
            if status != "queued":
                await session.execute(
                    text("UPDATE tasks SET status = :status WHERE public_id = :public_id"),
                    {"status": status, "public_id": public_id},
                )


async def test_count_by_status_returns_zeroes_for_an_empty_queue(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """Pusta tabela → wszystkie trzy stany z zerem (kontrakt §4: brakujące = 0)."""
    async with db() as session:
        counts = await task_counts.count_by_status(session)

    assert counts == dict.fromkeys(QUEUE_KEYS, 0)


async def test_count_by_status_counts_only_queue_states(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """Zadania done/failed/cancelled nie wchodzą do liczników kolejki (kontrakt §4)."""
    await _seed(
        db,
        ["queued", "queued", "running", "dead", "done", "failed", "cancelled"],
    )

    async with db() as session:
        counts = await task_counts.count_by_status(session)

    assert counts == {"queued": 2, "running": 1, "dead": 1}


async def test_count_by_status_defaults_missing_states_to_zero(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """Tylko queued w tabeli, a wynik nadal ma wszystkie trzy klucze."""
    await _seed(db, ["queued"])

    async with db() as session:
        counts = await task_counts.count_by_status(session)

    assert counts == {"queued": 1, "running": 0, "dead": 0}
