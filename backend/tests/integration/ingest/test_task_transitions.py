"""Testy przejść zadań a stany dokumentu (K5 §6.3) i odczytów task_lookup (brief T3)."""

import re
from dataclasses import replace

import pytest
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import UuidV7Generator
from app.db.repositories import documents as documents_repo
from app.db.repositories import task_lookup
from app.db.repositories import tasks as tasks_repo
from app.db.repositories.datasets import DatasetRow
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.worker.queue import DbTaskQueue, NewTask
from tests.fakes.clock import FrozenClock
from tests.integration.ingest.conftest import (
    _insert_parse_task,
    make_document_row,
    seed_dataset,
)

pytestmark = pytest.mark.db

WORKER_ID = "w:1:0"


def _queue(sm: async_sessionmaker[AsyncSession], clock: FrozenClock | None = None) -> DbTaskQueue:
    """Kolejka na zamrożonym zegarze, bez jitteru (brief T3)."""
    return DbTaskQueue(sm, clock or FrozenClock(), UuidV7Generator(), jitter=lambda: 0)


def _parse_task(document_id: str) -> NewTask:
    return NewTask("parse_document", document_id=document_id)


async def _running_document(
    sm: async_sessionmaker[AsyncSession], dataset: DatasetRow
) -> DocumentRow:
    """Dokument w trakcie parsowania: documents.insert w transakcji, run='1' (brief T3)."""
    row = replace(make_document_row(dataset), run="1")
    async with transaction(sm) as session:
        await documents_repo.insert(session, row)
    return row


async def _document(sm: async_sessionmaker[AsyncSession], document_id: str) -> DocumentRow:
    """Odczyt dokumentu w osobnej transakcji."""
    async with transaction(sm) as session:
        return await documents_repo.get(session, document_id)


async def _task_row(sm: async_sessionmaker[AsyncSession], public_id: str) -> RowMapping:
    """Odczyt wiersza tasks po public_id."""
    async with transaction(sm) as session:
        row = await tasks_repo.get(session, public_id)
    assert row is not None
    return row


async def test_fail_permanent_fails_document(sm) -> None:
    """fail(transient=False) → failed: dokument run='4', error z zadania, linia [ERROR] (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    queue = _queue(sm)
    await queue.enqueue(_parse_task(doc.id))
    task = await queue.claim(WORKER_ID, ["parse_document"])

    status = await queue.fail(task.id, WORKER_ID, ValueError("x"), transient=False)

    assert status == "failed"
    row = await _document(sm, doc.id)
    assert row.run == "4"
    assert row.error == "ValueError: x"
    last_line = row.progress_msg.rsplit("\n", 1)[-1]
    assert re.match(r"^\d\d:\d\d:\d\d \[ERROR\] ValueError: x$", last_line)


async def test_fail_transient_dead_fails_document(sm) -> None:
    """transient=True bez zapasu prób → dead: dokument run='4' (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    queue = _queue(sm)
    await queue.enqueue(NewTask("parse_document", document_id=doc.id, max_attempts=1))
    task = await queue.claim(WORKER_ID, ["parse_document"])

    status = await queue.fail(task.id, WORKER_ID, ValueError("x"), transient=True)

    assert status == "dead"
    row = await _document(sm, doc.id)
    assert row.run == "4"


async def test_fail_transient_requeue_keeps_document(sm) -> None:
    """transient=True z zapasem prób → queued: run='1', error None, msg bez zmian (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    queue = _queue(sm)
    await queue.enqueue(NewTask("parse_document", document_id=doc.id, max_attempts=3))
    task = await queue.claim(WORKER_ID, ["parse_document"])

    status = await queue.fail(task.id, WORKER_ID, ValueError("x"), transient=True)

    assert status == "queued"
    row = await _document(sm, doc.id)
    assert row.run == "1"
    assert row.error is None
    assert row.progress_msg == ""


async def test_complete_keeps_document(sm) -> None:
    """complete → dokument bez zmian (DONE ustawia commit §6.2, nie kolejka; brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    queue = _queue(sm)
    await queue.enqueue(_parse_task(doc.id))
    task = await queue.claim(WORKER_ID, ["parse_document"])

    await queue.complete(task.id, WORKER_ID)

    row = await _document(sm, doc.id)
    assert row.run == "1"
    assert row.error is None
    assert row.progress_msg == ""


async def test_mark_cancelled_cancels_document(sm) -> None:
    """mark_cancelled → run='2', ostatnia linia „HH:MM:SS Task has been cancelled.” (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    queue = _queue(sm)
    await queue.enqueue(_parse_task(doc.id))
    task = await queue.claim(WORKER_ID, ["parse_document"])

    await queue.mark_cancelled(task.id, WORKER_ID)

    row = await _document(sm, doc.id)
    assert row.run == "2"
    last_line = row.progress_msg.rsplit("\n", 1)[-1]
    assert re.match(r"^\d\d:\d\d:\d\d Task has been cancelled\.$", last_line)


async def test_request_cancel_queued_cancels_document_and_task(sm) -> None:
    """request_cancel na queued: zwraca 1, run='2', linia cancelled, zadanie cancelled (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    queue = _queue(sm)
    pid = await queue.enqueue(_parse_task(doc.id))

    touched = await queue.request_cancel(document_ids=[doc.id])

    assert touched == 1
    row = await _document(sm, doc.id)
    assert row.run == "2"
    last_line = row.progress_msg.rsplit("\n", 1)[-1]
    assert re.match(r"^\d\d:\d\d:\d\d Task has been cancelled\.$", last_line)
    task = await _task_row(sm, pid)
    assert task["status"] == "cancelled"


async def test_request_cancel_running_only_flags_task(sm) -> None:
    """request_cancel na running: cancel_requested=1, dokument bez zmian (run='1') (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    queue = _queue(sm)
    pid = await queue.enqueue(_parse_task(doc.id))
    await queue.claim(WORKER_ID, ["parse_document"])

    touched = await queue.request_cancel(document_ids=[doc.id])

    assert touched == 1
    task = await _task_row(sm, pid)
    assert int(task["cancel_requested"]) == 1
    row = await _document(sm, doc.id)
    assert row.run == "1"
    assert row.progress_msg == ""


async def test_reap_stale_dead_fails_document(sm) -> None:
    """reap_stale przy attempts=max_attempts → dead: dokument run='4', error TaskLost (brief)."""
    clock = FrozenClock()
    queue = _queue(sm, clock)
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    pid = await queue.enqueue(NewTask("parse_document", document_id=doc.id, max_attempts=1))
    await queue.claim(WORKER_ID, ["parse_document"])
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE tasks SET heartbeat_at = :stale WHERE public_id = :pid"),
            {"stale": clock.now_ms() - 10_000, "pid": pid},
        )
    clock.advance(20_000)

    reaped = await queue.reap_stale(1)

    assert reaped == 1
    task = await _task_row(sm, pid)
    assert task["status"] == "dead"
    assert task["error"] == "TaskLost: heartbeat timeout"
    row = await _document(sm, doc.id)
    assert row.run == "4"
    assert row.error == "TaskLost: heartbeat timeout"


async def test_fail_other_task_type_keeps_document(sm) -> None:
    """fail zadania innej klasy (reembed_dataset) → dokument bez zmian (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    queue = _queue(sm)
    await queue.enqueue(NewTask("reembed_dataset", document_id=doc.id, dataset_id=ds.id))
    task = await queue.claim(WORKER_ID, ["reembed_dataset"])

    status = await queue.fail(task.id, WORKER_ID, ValueError("x"), transient=False)

    assert status == "failed"
    row = await _document(sm, doc.id)
    assert row.run == "1"
    assert row.error is None
    assert row.progress_msg == ""


async def test_internal_id_resolves_and_missing_is_none(sm) -> None:
    """internal_id: istniejące zadanie → int > 0, nieznane public_id → None (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    pid = await _insert_parse_task(sm, ds, doc.id)
    async with transaction(sm) as session:
        found = await task_lookup.internal_id(session, pid)
        missing = await task_lookup.internal_id(session, "0" * 32)
    assert found is not None and found > 0
    assert missing is None


async def test_active_parse_documents_filters_statuses(sm) -> None:
    """active_parse_documents: queued+running w zbiorze, done poza; [] → set() (brief)."""
    ds = await seed_dataset(sm)
    queued_doc, running_doc, done_doc = [await _running_document(sm, ds) for _ in range(3)]
    pids = {
        doc.id: await _insert_parse_task(sm, ds, doc.id)
        for doc in (queued_doc, running_doc, done_doc)
    }
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE tasks SET status = 'running' WHERE public_id = :pid"),
            {"pid": pids[running_doc.id]},
        )
        await session.execute(
            text("UPDATE tasks SET status = 'done' WHERE public_id = :pid"),
            {"pid": pids[done_doc.id]},
        )
    async with transaction(sm) as session:
        active = await task_lookup.active_parse_documents(
            session, [queued_doc.id, running_doc.id, done_doc.id]
        )
        assert await task_lookup.active_parse_documents(session, []) == set()
    assert active == {queued_doc.id, running_doc.id}


async def test_last_done_digest_picks_latest_and_excludes(sm) -> None:
    """last_done_digest: najnowszy finished_at; exclude pomija zadanie; brak → None (brief)."""
    ds = await seed_dataset(sm)
    doc = await _running_document(sm, ds)
    first = await _insert_parse_task(sm, ds, doc.id)
    second = await _insert_parse_task(sm, ds, doc.id)
    async with transaction(sm) as session:
        await session.execute(
            text(
                "UPDATE tasks SET status = 'done', digest = :digest, finished_at = :finished"
                " WHERE public_id = :pid"
            ),
            [
                {"digest": "1" * 32, "finished": 1, "pid": first},
                {"digest": "2" * 32, "finished": 2, "pid": second},
            ],
        )
    async with transaction(sm) as session:
        latest = await task_lookup.last_done_digest(session, doc.id, exclude_public_id="f" * 32)
        without_latest = await task_lookup.last_done_digest(
            session, doc.id, exclude_public_id=second
        )
        none_digest = await task_lookup.last_done_digest(
            session, "e" * 32, exclude_public_id="f" * 32
        )
    assert latest == "2" * 32
    assert without_latest == "1" * 32
    assert none_digest is None
