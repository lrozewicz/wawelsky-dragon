"""Odporność pętli workera na przejściowe błędy DB — bez bazy, na fałszywej kolejce (brief T6).

Kontener bez ``start()`` (``sessionmaker = None``): przy podstawionych ``DbTaskQueue``,
``transaction`` i ``worker_heartbeat_repo.upsert`` nie jest używany (``cast`` nie sprawdza
typu w runtime). Każdy test ogranicza czas: po ``stop.set()`` czeka na ``run`` max 5 s.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

import pytest

from app.core.config import Settings
from app.core.container import Container
from app.worker import loop
from app.worker.context import TaskContext
from app.worker.errors import TaskCancelled
from app.worker.loop import Worker
from app.worker.queue import TaskRow


class _FakeQueue:
    """Metody TaskQueue używane przez Worker; zachowania (wyniki/wyjątki) skryptuje test."""

    def __init__(self, upsert_fail_after: int = 0) -> None:
        self.claim_script: list[Any] = []  # TaskRow albo Exception; po wyczerpaniu claim → None
        self.complete_error: Exception | None = None
        self.reap_error: Exception | None = None
        self.heartbeat_ok = True
        self.heartbeat_error: Exception | None = None
        self.fail_status = "queued"  # wynik queue.fail: queued | dead | failed
        self.upsert = _FakeUpsert(upsert_fail_after)  # podstawiany za worker_heartbeat_repo
        self.claims = 0
        self.completes = 0
        self.fail_calls = 0
        self.reaps = 0
        self.releases = 0
        self.mark_cancelleds = 0
        self.released = 0  # ile zadań zwraca release_own_host (brief T5)

    async def claim(self, worker_id: str, types: list[str]) -> TaskRow | None:
        self.claims += 1
        item = self.claim_script.pop(0) if self.claim_script else None
        if isinstance(item, Exception):
            raise item
        return item

    async def heartbeat(
        self, task_id: str, worker_id: str, progress: float | None, msg: str | None
    ) -> bool:
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return self.heartbeat_ok

    async def complete(self, task_id: str, worker_id: str) -> None:
        self.completes += 1
        if self.complete_error is not None:
            raise self.complete_error

    async def fail(
        self, task_id: str, worker_id: str, err: BaseException, *, transient: bool
    ) -> str:
        self.fail_calls += 1
        return self.fail_status

    async def mark_cancelled(self, task_id: str, worker_id: str) -> None:
        self.mark_cancelleds += 1

    async def release(self, task_id: str, worker_id: str) -> None:
        self.releases += 1

    async def reap_stale(self, stale_after_s: int) -> int:
        self.reaps += 1
        if self.reap_error is not None:
            raise self.reap_error
        return 0

    async def release_own_host(self, worker_id: str) -> int:
        return self.released


class _FakeUpsert:
    """Fałszywy worker_heartbeat_repo.upsert; po ``fail_after`` wywołaniach rzuca (0 = nigdy)."""

    def __init__(self, fail_after: int = 0) -> None:
        self.calls = 0
        self._fail_after = fail_after

    async def __call__(self, session: Any, **kwargs: Any) -> None:
        self.calls += 1
        if 0 < self._fail_after < self.calls:
            raise OSError("db down")


@contextlib.asynccontextmanager
async def _fake_transaction(sessionmaker: Any) -> Any:
    yield object()


def _task_row() -> TaskRow:
    return TaskRow(
        id="t" * 32,
        task_type="parse_document",
        payload={},
        document_id=None,
        dataset_id=None,
        priority=0,
        status="running",
        attempts=1,
        max_attempts=3,
        cancel_requested=False,
        progress=0.0,
        progress_msg="",
        digest=None,
        error=None,
        locked_by="host:1:0",
    )


async def _until(predicate: Callable[[], bool], timeout_s: float = 5.0) -> None:
    """Czeka aż predykat prawdziwy; TimeoutError ogranicza czas oczekiwania na pętlę."""
    clock = asyncio.get_running_loop().time
    deadline = clock() + timeout_s
    while not predicate():
        if clock() > deadline:
            raise TimeoutError
        await asyncio.sleep(0.01)


def _make_worker(
    monkeypatch: Any,
    tmp_path: Any,
    queue: _FakeQueue,
    handlers: dict[str, Callable[[TaskRow, TaskContext], Any]],
) -> Worker:
    """Worker na kontenerze bez start(), z podstawioną kolejką, transakcją i upsertem."""
    container = Container(
        Settings(
            env="test",
            storage_root=str(tmp_path),
            worker_concurrency=1,
            worker_poll_s=0.01,
            task_heartbeat_s=1,
        )
    )
    monkeypatch.setattr(loop, "DbTaskQueue", lambda *a, **k: queue)
    monkeypatch.setattr(loop.worker_heartbeat_repo, "upsert", queue.upsert)
    monkeypatch.setattr(loop, "transaction", _fake_transaction)
    monkeypatch.setattr(loop, "ERROR_BACKOFF_S", 0.01)
    return Worker(container, handlers)


async def _run_and_stop(worker: Worker, stop: asyncio.Event, ready: Callable[[], bool]) -> None:
    """Uruchamia run(), czeka aż ``ready`` (pętla doszła do badanego miejsca), potem stop."""
    run_task = asyncio.create_task(worker.run(stop))
    await _until(ready)
    stop.set()
    await asyncio.wait_for(run_task, 5)


async def test_claim_error_does_not_kill_slot(monkeypatch: Any, tmp_path: Any, caplog: Any) -> None:
    queue = _FakeQueue()
    queue.claim_script = [OSError("db down"), OSError("db down"), _task_row()]
    handled: list[str] = []

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        handled.append(task.id)

    worker = _make_worker(monkeypatch, tmp_path, queue, {"parse_document": handler})
    stop = asyncio.Event()
    await _run_and_stop(worker, stop, lambda: queue.completes == 1)
    assert handled == ["t" * 32]  # handler wywołany raz, po dwóch błędach claimu
    assert queue.completes == 1
    assert "claim failed" in [record.getMessage() for record in caplog.records]


async def test_complete_error_does_not_kill_slot(
    monkeypatch: Any, tmp_path: Any, caplog: Any
) -> None:
    queue = _FakeQueue()
    queue.claim_script = [_task_row(), _task_row()]
    queue.complete_error = OSError("db down")
    handled: list[str] = []

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        handled.append(task.id)

    worker = _make_worker(monkeypatch, tmp_path, queue, {"parse_document": handler})
    stop = asyncio.Event()
    await _run_and_stop(worker, stop, lambda: len(handled) == 2)  # noqa: PLR2004 — dwa zadania
    assert len(handled) == 2  # noqa: PLR2004 — dwa zadania: slot wziął kolejne mimo błędu zapisu
    assert "recording task result failed" in [record.getMessage() for record in caplog.records]


async def test_handler_error_is_failed_as_transient(
    monkeypatch: Any, tmp_path: Any, caplog: Any
) -> None:
    queue = _FakeQueue()
    queue.claim_script = [_task_row()]
    # Log "task back to queue" jest INFO — domyślny poziom caplog go nie łapie.
    caplog.set_level(logging.INFO, logger="app.worker")

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        raise OSError("handler broke")  # nie-WDError → fail_transient (C9)

    worker = _make_worker(monkeypatch, tmp_path, queue, {"parse_document": handler})
    stop = asyncio.Event()
    await _run_and_stop(worker, stop, lambda: queue.fail_calls == 1)
    assert queue.fail_calls == 1  # błąd handlera ≠ śmierć slotu: wynik zapisany przez fail()
    assert "task back to queue" in [record.getMessage() for record in caplog.records]


async def test_worker_heartbeat_loop_survives_upsert_errors(
    monkeypatch: Any, tmp_path: Any
) -> None:
    queue = _FakeQueue(upsert_fail_after=1)  # startowy upsert w run() przechodzi, kolejne rzucają
    worker = _make_worker(monkeypatch, tmp_path, queue, {})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    # Czekamy na FAKTYCZNY warunek (drugi upsert z pętli tętna), nie na zegar: przy
    # task_heartbeat_s=1 stałe sleep(1.5) bywało za krótkie pod obciążeniem (flak E5-H7/T1).
    await _until(lambda: queue.upsert.calls >= 2)  # noqa: PLR2004 — startowy + pętla
    assert queue.upsert.calls >= 2  # noqa: PLR2004 — pętla żyje mimo wyjątków z upsertu
    stop.set()
    await asyncio.wait_for(run_task, 5)  # kończy się bez wyjątku


async def test_reaper_loop_survives_reap_errors(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(loop, "REAPER_INTERVAL_S", 0.05)
    queue = _FakeQueue()
    queue.reap_error = OSError("db down")
    worker = _make_worker(monkeypatch, tmp_path, queue, {})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    await asyncio.sleep(0.5)  # przy interwale 0,05 s reap_stale zdąży się wykonać wielokrotnie
    assert queue.reaps >= 2  # noqa: PLR2004 — dwa przebiegi: reaper próbuje dalej po błędzie
    stop.set()
    await asyncio.wait_for(run_task, 5)


async def test_task_heartbeat_error_does_not_lose_task(
    monkeypatch: Any, tmp_path: Any, caplog: Any
) -> None:
    queue = _FakeQueue()
    queue.claim_script = [_task_row()]
    queue.heartbeat_error = OSError("db down")  # błąd DB ≠ utrata zadania

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        await asyncio.sleep(1.2)  # trwa dłużej niż interwał tętna (1 s), żeby błąd zdążył paść

    worker = _make_worker(monkeypatch, tmp_path, queue, {"parse_document": handler})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    await _until(lambda: queue.completes == 1)  # handler skończony i wynik zapisany mimo błędu
    stop.set()
    await asyncio.wait_for(run_task, 5)
    assert "task heartbeat failed" in [record.getMessage() for record in caplog.records]


async def test_heartbeat_lost_stops_handler_without_record(monkeypatch: Any, tmp_path: Any) -> None:
    queue = _FakeQueue()
    queue.claim_script = [_task_row()]
    queue.heartbeat_ok = False  # zadanie przejął reaper/obcy worker

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        await asyncio.sleep(10)  # zostałaby przerwana dopiero przez lost

    worker = _make_worker(monkeypatch, tmp_path, queue, {"parse_document": handler})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    await _until(lambda: queue.claims >= 2)  # noqa: PLR2004 — drugi claim: slot wrócił po lost
    stop.set()
    await asyncio.wait_for(run_task, 5)
    assert queue.completes == 0  # nic nie zapisujemy po utracie zadania
    assert queue.fail_calls == 0


async def test_shutdown_during_task_releases_task(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(loop, "SHUTDOWN_GRACE_S", 0.1)  # slot zajęty → cancel po grace
    queue = _FakeQueue()
    queue.claim_script = [_task_row()]
    started = asyncio.Event()

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        started.set()
        await asyncio.sleep(10)  # slot zajęty w chwili stopu

    worker = _make_worker(monkeypatch, tmp_path, queue, {"parse_document": handler})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    await _until(started.is_set)
    stop.set()
    await asyncio.wait_for(run_task, 5)  # bez wyjątku mimo anulowania slotu
    assert queue.releases == 1  # zadanie wraca do kolejki (C9: graceful stop)


async def test_handler_cancelled_task_is_marked_cancelled(monkeypatch: Any, tmp_path: Any) -> None:
    queue = _FakeQueue()
    queue.claim_script = [_task_row()]

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        raise TaskCancelled()

    worker = _make_worker(monkeypatch, tmp_path, queue, {"parse_document": handler})
    stop = asyncio.Event()
    await _run_and_stop(worker, stop, lambda: queue.mark_cancelleds == 1)
    assert queue.mark_cancelleds == 1
    assert queue.completes == 0


@pytest.mark.parametrize("fail_status", ["dead", "failed"])
async def test_fail_status_logs(
    monkeypatch: Any, tmp_path: Any, caplog: Any, fail_status: str
) -> None:
    queue = _FakeQueue()
    queue.claim_script = [_task_row()]
    queue.fail_status = fail_status

    async def handler(task: TaskRow, ctx: TaskContext) -> None:
        raise OSError("handler broke")

    worker = _make_worker(monkeypatch, tmp_path, queue, {"parse_document": handler})
    stop = asyncio.Event()
    await _run_and_stop(worker, stop, lambda: queue.fail_calls == 1)
    expected = "task exceeded attempts" if fail_status == "dead" else "task failed"
    assert expected in [record.getMessage() for record in caplog.records]


@pytest.mark.parametrize(("released", "expected_count"), [(2, 2), (0, None)])
async def test_release_own_host_logs_event(
    monkeypatch: Any, tmp_path: Any, caplog: Any, released: int, expected_count: int | None
) -> None:
    """release_own_host zwolnił zadania → INFO z event; 0 → brak zdarzenia (brief T5)."""
    caplog.set_level(logging.INFO, logger="app.worker")  # log jest INFO
    queue = _FakeQueue()
    queue.released = released
    worker = _make_worker(monkeypatch, tmp_path, queue, {})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    await _until(lambda: queue.upsert.calls >= 1)  # release_own_host jest przed startowym upsertem
    stop.set()
    await asyncio.wait_for(run_task, 5)
    events = [r for r in caplog.records if getattr(r, "event", None) == "task_released_own_host"]
    if expected_count is None:
        assert events == []
    else:
        assert len(events) == 1
        assert events[0].count == expected_count
