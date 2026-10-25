"""Testy współbieżności claimu: dokładnie raz i SKIP LOCKED (brief T2, wymaganie 8)."""

import asyncio

import pymysql
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.db.engine import make_engine, make_sessionmaker
from app.worker.queue import DbTaskQueue, NewTask
from tests.fakes.clock import FrozenClock
from tests.integration.queue.conftest import insert_document

pytestmark = pytest.mark.db

_TASKS = 50
_CONSUMERS = 4


def _queue(sm: async_sessionmaker[AsyncSession], clock: FrozenClock) -> DbTaskQueue:
    return DbTaskQueue(sm, clock, UuidV7Generator(), jitter=lambda: 0)


async def _count(sm: async_sessionmaker[AsyncSession], sql: str) -> int:
    async with sm() as session:
        result = await session.execute(text(sql))
        return int(result.scalar_one())


async def test_claim_exactly_once(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    enqueued = {await queue.enqueue(NewTask("parse_document")) for _ in range(_TASKS)}
    collected: list[str] = []

    async def consume(slot: int) -> None:
        engine = make_engine(migrated_db)
        try:
            consumer = DbTaskQueue(
                make_sessionmaker(engine), clock, UuidV7Generator(), jitter=lambda: 0
            )
            worker_id = f"t:1:{slot}"
            while True:
                row = await consumer.claim(worker_id, ["parse_document"])
                if row is None:
                    return
                collected.append(row.id)
                await asyncio.sleep(0)
                await consumer.complete(row.id, worker_id)
        finally:
            await engine.dispose()

    await asyncio.gather(*(consume(slot) for slot in range(_CONSUMERS)))

    assert len(collected) == _TASKS
    assert set(collected) == enqueued
    assert (
        await _count(sm, "SELECT COUNT(*) FROM tasks WHERE status = 'done' AND attempts = 1")
        == _TASKS
    )
    assert (
        await _count(sm, "SELECT COUNT(*) FROM tasks WHERE status <> 'done' OR attempts <> 1") == 0
    )


async def test_claim_skips_locked_row(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    first = await queue.enqueue(NewTask("parse_document"))
    second = await queue.enqueue(NewTask("parse_document"))
    connection = pymysql.connect(
        host=migrated_db.db_host,
        port=migrated_db.db_port,
        user=migrated_db.db_user,
        password=migrated_db.db_password.get_secret_value(),
        database=migrated_db.db_name,
        autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM tasks WHERE public_id = %s FOR UPDATE", (first,))
        # Bez SKIP LOCKED claim czekałby na lock wiersza `first` → timeout → test czerwony.
        row = await asyncio.wait_for(queue.claim("t:1:0", ["parse_document"]), timeout=5)
        assert row is not None
        assert row.id == second
    finally:
        connection.rollback()
        connection.close()
