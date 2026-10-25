"""Testy integracyjne workera na MariaDB — pętla claim→handler (brief T3, wymaganie 5)."""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock, now_ms
from app.core.version import APP_VERSION
from app.db.repositories import worker_heartbeat as wh_repo
from app.db.uow import transaction
from app.worker import loop
from app.worker.context import TaskContext
from app.worker.errors import PermanentError, TransientError
from app.worker.loop import Worker, host_name, make_worker_id
from app.worker.queue import DbTaskQueue, NewTask, TaskRow
from tests.integration.queue.conftest import insert_document

pytestmark = pytest.mark.db


@pytest.fixture
async def worker_container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy wg briefu T3: concurrency 2, szybki poll i heartbeat 1 s (C12)."""
    container = Container(
        migrated_db.model_copy(
            update={
                "storage_root": str(tmp_path),
                "worker_concurrency": 2,
                "worker_poll_s": 0.05,
                "task_heartbeat_s": 1,
            }
        )
    )
    await container.start()
    yield container
    await container.aclose()


async def wait_until(
    pred: Callable[[], Awaitable[bool]],
    timeout: float = 15.0,  # noqa: ASYNC109 — nazwa `timeout` z briefu T3 (helper testowy)
    *,
    label: str = "warunek",
) -> None:
    """Czeka aż pred() zwróci True; pętla z asyncio.sleep(0.05) i limitem (brief T3 pkt 5)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await pred():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{label} nie został spełniony w {timeout} s")


def _queue(sm: async_sessionmaker[AsyncSession]) -> DbTaskQueue:
    """Osobna kolejka do zakładania zadań (brief T3 pkt 5)."""
    return DbTaskQueue(sm, SystemClock(), UuidV7Generator())


async def _row(sm: async_sessionmaker[AsyncSession], public_id: str) -> RowMapping:
    """Odczyt wiersza tasks po public_id, poza workere."""
    async with sm() as session:
        result = await session.execute(
            text("SELECT * FROM tasks WHERE public_id = :public_id"), {"public_id": public_id}
        )
        return result.mappings().one()


async def _status(sm: async_sessionmaker[AsyncSession], public_id: str) -> str:
    return str((await _row(sm, public_id))["status"])


@contextlib.asynccontextmanager
async def _run_worker(
    container: Container, handler: Callable[[TaskRow, TaskContext], Awaitable[None]]
) -> AsyncIterator[asyncio.Task[None]]:
    """Startuje workera z handlerem parse_document; na wyjściu stop i oczekiwanie na run()."""
    worker = Worker(container, {"parse_document": handler})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    yield run_task
    stop.set()
    await asyncio.wait_for(run_task, timeout=15)


async def test_e2e_six_tasks_done(
    worker_container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """6 zadań → wszystkie done, handler dokładnie 6 razy po jednym, układ storage (brief)."""
    queue = _queue(sm)
    ids = [await queue.enqueue(NewTask("parse_document")) for _ in range(6)]
    handled: list[str] = []

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        handled.append(task.id)
        await ctx.report(0.5, "half")

    async def all_done() -> bool:
        async with sm() as session:
            statuses = (await session.execute(text("SELECT status FROM tasks"))).scalars().all()
        return len(statuses) == len(ids) and set(statuses) == {"done"}

    async with _run_worker(worker_container, handler):
        await wait_until(all_done)

    assert len(handled) == len(ids)
    assert sorted(handled) == sorted(ids)
    async with sm() as session:
        rows = (await session.execute(text("SELECT public_id, status FROM tasks"))).mappings().all()
    assert sorted((str(r["public_id"]), str(r["status"])) for r in rows) == sorted(
        (task_id, "done") for task_id in ids
    )
    for name in ("files", "images", "filemanager", "tmp"):
        assert (tmp_path / name).is_dir()


async def test_slots_limit_concurrency(
    worker_container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """worker_concurrency=2: z 3 zadań naraz dokładnie 2 running; po zwolnieniu wszystkie done."""
    queue = _queue(sm)
    ids = [await queue.enqueue(NewTask("parse_document")) for _ in range(3)]
    gate = asyncio.Event()

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        await gate.wait()

    async def two_running() -> bool:
        async with sm() as session:
            running = (
                await session.execute(text("SELECT COUNT(*) FROM tasks WHERE status = 'running'"))
            ).scalar_one()
        return int(running) == 2  # noqa: PLR2004 — worker_concurrency=2 z fixture

    async def all_done() -> bool:
        async with sm() as session:
            statuses = (await session.execute(text("SELECT status FROM tasks"))).scalars().all()
        return len(statuses) == len(ids) and set(statuses) == {"done"}

    async with _run_worker(worker_container, handler):
        await wait_until(two_running)
        async with sm() as session:
            running = (
                await session.execute(text("SELECT COUNT(*) FROM tasks WHERE status = 'running'"))
            ).scalar_one()
            queued = (
                await session.execute(text("SELECT COUNT(*) FROM tasks WHERE status = 'queued'"))
            ).scalar_one()
        assert int(running) == 2  # noqa: PLR2004 — worker_concurrency=2 z fixture
        assert int(queued) == 1
        gate.set()
        await wait_until(all_done)  # dopóki worker działa — trzecie zadanie musi zostać zebrane

    async with sm() as session:
        statuses = (await session.execute(text("SELECT status FROM tasks"))).scalars().all()
    assert len(statuses) == len(ids) and set(statuses) == {"done"}


async def test_transient_error_requeues(
    worker_container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """TransientError → queued z attempts=1 i next_attempt_at > now (brief)."""
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document"))

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        raise TransientError("boom")

    async def requeued() -> bool:
        row = await _row(sm, task_id)
        return str(row["status"]) == "queued" and int(row["attempts"]) == 1

    async with _run_worker(worker_container, handler):
        await wait_until(requeued)

    row = await _row(sm, task_id)
    assert row["status"] == "queued"
    assert int(row["attempts"]) == 1
    assert row["next_attempt_at"] is not None
    assert int(row["next_attempt_at"]) > now_ms()


async def test_permanent_error_fails(
    worker_container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PermanentError → failed (brief)."""
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document"))

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        raise PermanentError("bad input")

    async def failed() -> bool:
        return await _status(sm, task_id) == "failed"

    async with _run_worker(worker_container, handler):
        await wait_until(failed)


async def test_value_error_is_transient(
    worker_container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """ValueError (bez atrybutu transient, nie-WDError) → queued (brief)."""
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document"))

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        raise ValueError("oops")

    async def requeued() -> bool:
        row = await _row(sm, task_id)
        return str(row["status"]) == "queued" and int(row["attempts"]) == 1

    async with _run_worker(worker_container, handler):
        await wait_until(requeued)


async def test_request_cancel_marks_task_cancelled(
    worker_container: Container, sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    """check_cancel() w pętli + request_cancel po document_id → cancelled (brief)."""
    _, document_id = insert_document(migrated_db)
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document", document_id=document_id))
    started = asyncio.Event()

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        started.set()
        while True:
            await ctx.check_cancel()
            await asyncio.sleep(0.05)

    async def started_flag() -> bool:
        return started.is_set()

    async def cancelled() -> bool:
        return await _status(sm, task_id) == "cancelled"

    async with _run_worker(worker_container, handler):
        await wait_until(started_flag)
        await queue.request_cancel(document_ids=[document_id])
        await wait_until(cancelled)


async def test_lost_heartbeat_cancels_handler_without_writes(
    worker_container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przejęcie zadania przez obcego: handler anulowany ≤ 5 s, worker nic nie zapisuje (brief)."""
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document"))
    handler_cancelled = asyncio.Event()

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise

    async def running() -> bool:
        return await _status(sm, task_id) == "running"

    async def handler_cancelled_flag() -> bool:
        return handler_cancelled.is_set()

    async with _run_worker(worker_container, handler):
        await wait_until(running)
        async with transaction(sm) as session:
            await session.execute(
                text("UPDATE tasks SET locked_by = 'obcy:1:0' WHERE public_id = :public_id"),
                {"public_id": task_id},
            )
        await wait_until(handler_cancelled_flag, timeout=5, label="anulowanie handlera")

    row = await _row(sm, task_id)
    assert row["status"] == "running"
    assert row["locked_by"] == "obcy:1:0"


async def test_graceful_stop_releases_hanging_handler(
    worker_container: Container,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop przy wiszącym handlerze (grace 0,5 s): run < 5 s, zadanie queued, attempts=0 (brief)."""
    monkeypatch.setattr(loop, "SHUTDOWN_GRACE_S", 0.5)
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document"))
    started = asyncio.Event()

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        started.set()
        await asyncio.Event().wait()  # w nieskończoność

    async def started_flag() -> bool:
        return started.is_set()

    worker = Worker(worker_container, {"parse_document": handler})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    await wait_until(started_flag)
    stop.set()
    await asyncio.wait_for(run_task, timeout=5)  # run kończy się < 5 s

    row = await _row(sm, task_id)
    assert row["status"] == "queued"
    assert int(row["attempts"]) == 0
    assert row["locked_by"] is None


async def test_graceful_stop_waits_for_finishing_handler(
    worker_container: Container,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler kończy się 0,1 s po stop.set() → grace czeka, zadanie done (brief)."""
    monkeypatch.setattr(loop, "SHUTDOWN_GRACE_S", 5.0)
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document"))
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        started.set()
        await release.wait()

    async def started_flag() -> bool:
        return started.is_set()

    worker = Worker(worker_container, {"parse_document": handler})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    await wait_until(started_flag)
    stop.set()
    await asyncio.sleep(0.1)
    release.set()
    await asyncio.wait_for(run_task, timeout=5)

    row = await _row(sm, task_id)
    assert row["status"] == "done"


async def test_release_own_host_requeues_and_runs(
    worker_container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zadanie running z locked_by host:999999:0 wraca do kolejki przy starcie i jest wykonane."""
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document"))
    now = now_ms()
    async with transaction(sm) as session:
        await session.execute(
            text(
                "UPDATE tasks SET status = 'running', attempts = 1, locked_by = :locked_by,"
                " started_at = :now, heartbeat_at = :now, next_attempt_at = :now"
                " WHERE public_id = :public_id"
            ),
            {"locked_by": f"{host_name()}:999999:0", "now": now, "public_id": task_id},
        )

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        return None

    async def done() -> bool:
        return await _status(sm, task_id) == "done"

    async with _run_worker(worker_container, handler):
        await wait_until(done)


async def test_reaper_requeues_stale_task(
    worker_container: Container,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REAPER_INTERVAL_S=0,2, task_stale_s=1: running bez tętna od 10 s → queued ≤ 5 s (brief)."""
    monkeypatch.setattr(loop, "REAPER_INTERVAL_S", 0.2)
    worker_container.settings.task_stale_s = 1
    queue = _queue(sm)
    task_id = await queue.enqueue(NewTask("parse_document"))
    stale = now_ms() - 10_000
    async with transaction(sm) as session:
        await session.execute(
            text(
                "UPDATE tasks SET status = 'running', attempts = 1, locked_by = 'x:1:0',"
                " started_at = :stale, heartbeat_at = :stale, next_attempt_at = :stale"
                " WHERE public_id = :public_id"
            ),
            {"stale": stale, "public_id": task_id},
        )

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        raise AssertionError("zadanie przechwycone przez reapera nie może być wykonywane")

    async def requeued() -> bool:
        return await _status(sm, task_id) == "queued"

    async with _run_worker(worker_container, handler):
        await wait_until(requeued, timeout=5, label="reaper")


async def test_worker_heartbeat_upsert_and_has_recent(
    worker_container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Wiersz worker_heartbeat: klucz procesu, APP_VERSION, capabilities; has_recent wg hosta."""

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        return None

    async def beat() -> bool:
        async with transaction(sm) as session:
            return await wh_repo.has_recent(session, host=host_name(), since_ms=now_ms() - 60_000)

    async with _run_worker(worker_container, handler):
        await wait_until(beat)

    async with sm() as session:
        row = (
            (
                await session.execute(
                    text("SELECT worker_id, version, capabilities FROM worker_heartbeat")
                )
            )
            .mappings()
            .one()
        )
    assert row["worker_id"] == make_worker_id()
    assert row["version"] == APP_VERSION
    assert json.loads(cast("str", row["capabilities"])) == {
        "task_types": ["parse_document"],
        "ocr_available": False,
    }
    async with transaction(sm) as session:
        assert await wh_repo.has_recent(session, host=host_name(), since_ms=now_ms() - 60_000)
        assert not await wh_repo.has_recent(session, host="innyhost", since_ms=now_ms() - 60_000)
