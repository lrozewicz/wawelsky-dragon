"""SC-E5-H8a-03: restart workera z zaplanowanym anulowaniem (brief T2, kontrakt C5).

``release_own_host``/``reap_stale`` kończą zadanie z ``cancel_requested=1`` jako ``cancelled``,
a ``claim`` nie uruchamia zadań z ``cancel_requested=1``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.db.uow import transaction
from app.worker.queue import DbTaskQueue, NewTask
from tests.fakes.clock import FrozenClock
from tests.integration.queue.conftest import insert_document

pytestmark = pytest.mark.db

_HOST_WORKER = "host-a:1:0"
_STALE_S = 60


def _queue(sm: async_sessionmaker[AsyncSession], clock: FrozenClock) -> DbTaskQueue:
    """Kolejka na zamrożonym zegarze, bez jitteru (jak w test_queue)."""
    return DbTaskQueue(sm, clock, UuidV7Generator(), jitter=lambda: 0)


async def _row(sm: async_sessionmaker[AsyncSession], public_id: str) -> RowMapping:
    """Wiersz tasks po public_id, poza kolejką."""
    async with sm() as session:
        result = await session.execute(
            text("SELECT * FROM tasks WHERE public_id = :pid"), {"pid": public_id}
        )
        return result.mappings().one()


async def _document_run(sm: async_sessionmaker[AsyncSession], document_id: str) -> str:
    """run dokumentu (kontrakt C5: cancelled → '2')."""
    async with transaction(sm) as session:
        value = (
            await session.execute(
                text("SELECT run FROM documents WHERE id = :id"), {"id": document_id}
            )
        ).scalar_one()
    return str(value)


async def _running_cancel_requested(
    sm: async_sessionmaker[AsyncSession], settings: Settings, worker_id: str
) -> tuple[str, str, FrozenClock, DbTaskQueue]:
    """Zadanie running z cancel_requested=1 dla dokumentu (kontrakt C5)."""
    _, document_id = insert_document(settings)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    public_id = await queue.enqueue(NewTask("parse_document", document_id=document_id))
    assert await queue.claim(worker_id, ["parse_document"]) is not None
    assert await queue.request_cancel(document_ids=[document_id]) == 1
    row = await _row(sm, public_id)
    assert row["status"] == "running"
    assert bool(row["cancel_requested"]) is True
    return public_id, document_id, clock, queue


async def test_cancel_requested_running_task_is_cancelled_on_release_own_host(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    """SC-E5-H8a-03: release_own_host kończy zadanie z cancel_requested jako cancelled."""
    public_id, document_id, _, queue = await _running_cancel_requested(
        sm, migrated_db, _HOST_WORKER
    )

    await queue.release_own_host(_HOST_WORKER)

    row = await _row(sm, public_id)
    assert row["status"] == "cancelled"
    assert row["finished_at"] is not None
    assert await _document_run(sm, document_id) == "2"


async def test_cancel_requested_running_task_is_cancelled_on_reap_stale(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    """SC-E5-H8a-03: reap_stale kończy zadanie z cancel_requested jako cancelled."""
    public_id, document_id, clock, queue = await _running_cancel_requested(
        sm, migrated_db, _HOST_WORKER
    )
    clock.advance((_STALE_S + 1) * 1000)

    assert await queue.reap_stale(_STALE_S) >= 1

    row = await _row(sm, public_id)
    assert row["status"] == "cancelled"
    assert row["finished_at"] is not None
    assert await _document_run(sm, document_id) == "2"


async def test_claim_skips_cancel_requested_queued_task(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    """SC-E5-H8a-03: claim nie uruchamia zadania queued z cancel_requested=1 (kontrakt C5)."""
    _, document_id = insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    public_id = await queue.enqueue(NewTask("parse_document", document_id=document_id))
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE tasks SET cancel_requested = 1 WHERE public_id = :pid"),
            {"pid": public_id},
        )

    claimed = await queue.claim(_HOST_WORKER, ["parse_document"])

    assert claimed is None
    assert (await _row(sm, public_id))["status"] == "cancelled"
