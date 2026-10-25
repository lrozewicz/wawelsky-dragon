"""Testy jednostkowe pętli workera — bez DB (brief T3, wymaganie 4)."""

import logging
import os

import pytest

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import NotFound, UpstreamError
from app.worker.context import TaskContext
from app.worker.errors import PermanentError, TaskCancelled, TaskLost, TransientError
from app.worker.loop import Worker, classify, host_name, make_worker_id
from app.worker.queue import TaskRow


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (None, "complete"),
        (TaskCancelled(), "cancelled"),
        (TaskLost(), "lost"),
        (TransientError("x"), "fail_transient"),
        (PermanentError("x"), "fail_permanent"),
        (NotFound("x"), "fail_permanent"),  # WDError bez atrybutu transient
        (ValueError(), "fail_transient"),
        (UpstreamError("x"), "fail_permanent"),  # WDError bez atrybutu transient
    ],
)
def test_classify(exc: BaseException | None, expected: str) -> None:
    assert classify(exc) == expected


def test_make_worker_id_process() -> None:
    assert make_worker_id() == f"{host_name()}:{os.getpid()}"


def test_make_worker_id_slot() -> None:
    worker_id = make_worker_id(3)
    assert worker_id.endswith(":3")
    assert len(worker_id) <= 64  # noqa: PLR2004 — kolumna worker_id VARCHAR(64)


def test_host_name_max_length() -> None:
    assert len(host_name()) <= 40  # noqa: PLR2004 — kontrakt C9: gethostname()[:40]


class _FakeQueue:
    """Fałszywa kolejka zwracająca zadaną wartość heartbeat/is_cancel_requested (brief pkt 4)."""

    def __init__(self, heartbeat_ok: bool = True, cancel_requested: bool = False) -> None:
        self.calls: list[tuple[str, str, float | None, str | None]] = []
        self._heartbeat_ok = heartbeat_ok
        self._cancel_requested = cancel_requested

    async def heartbeat(
        self, task_id: str, worker_id: str, progress: float | None, msg: str | None
    ) -> bool:
        self.calls.append((task_id, worker_id, progress, msg))
        return self._heartbeat_ok

    async def is_cancel_requested(self, task_id: str) -> bool:
        return self._cancel_requested


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


def _ctx(queue: _FakeQueue) -> TaskContext:
    return TaskContext(
        task=_task_row(),
        worker_id="host:1:0",
        container=Container(Settings(env="test")),
        logger=logging.LoggerAdapter(logging.getLogger("app.worker.task"), {}),
        queue=queue,
    )


async def test_report_lost_when_heartbeat_false() -> None:
    ctx = _ctx(_FakeQueue(heartbeat_ok=False))
    with pytest.raises(TaskLost):
        await ctx.report(0.5, "m")


async def test_report_calls_queue_with_arguments() -> None:
    queue = _FakeQueue(heartbeat_ok=True)
    ctx = _ctx(queue)
    await ctx.report(0.5, "m")
    assert queue.calls == [(ctx.task.id, "host:1:0", 0.5, "m")]


async def test_check_cancel_raises_when_requested() -> None:
    ctx = _ctx(_FakeQueue(cancel_requested=True))
    with pytest.raises(TaskCancelled):
        await ctx.check_cancel()


async def test_check_cancel_passes_when_not_requested() -> None:
    ctx = _ctx(_FakeQueue(cancel_requested=False))
    await ctx.check_cancel()  # nie rzuca


def test_worker_constructs_without_io() -> None:
    worker = Worker(Container(Settings(env="test")), {})
    assert worker is not None
