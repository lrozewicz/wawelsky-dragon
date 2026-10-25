"""Testy backoffu, błędów kolejki i domyślnego jittera (brief T2, wymaganie 7)."""

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import OperationNotAllowed, UpstreamError, WDError
from app.core.ids import UuidV7Generator
from app.worker.errors import PermanentError, TaskCancelled, TaskLost, TransientError
from app.worker.queue import DbTaskQueue, backoff_ms
from tests.fakes.clock import FrozenClock


def test_backoff_ms_values() -> None:
    assert backoff_ms(1, 0) == 20_000  # noqa: PLR2004 — wartości dosłownie z briefu T2
    assert backoff_ms(0, 0) == 10_000  # noqa: PLR2004
    assert backoff_ms(5, 0) == 320_000  # noqa: PLR2004
    assert backoff_ms(6, 0) == 600_000  # noqa: PLR2004
    assert backoff_ms(20, 0) == 600_000  # noqa: PLR2004


def test_backoff_ms_with_jitter() -> None:
    assert backoff_ms(1, 5000) == 25_000  # noqa: PLR2004 — wartości dosłownie z briefu T2


def test_transient_error_is_transient() -> None:
    assert TransientError("x").transient is True


def test_permanent_error_is_not_transient() -> None:
    assert PermanentError("x").transient is False


def test_permanent_error_subclasses_operation_not_allowed() -> None:
    assert issubclass(PermanentError, OperationNotAllowed)


def test_transient_error_subclasses_upstream_error() -> None:
    assert issubclass(TransientError, UpstreamError)


def test_control_errors_are_not_wd_errors() -> None:
    assert not issubclass(TaskCancelled, WDError)
    assert not issubclass(TaskLost, WDError)


def test_db_task_queue_constructs_without_io() -> None:
    queue = DbTaskQueue(
        cast(async_sessionmaker[AsyncSession], object()), FrozenClock(), UuidV7Generator()
    )
    assert queue is not None


def test_default_jitter_in_range() -> None:
    queue = DbTaskQueue(
        cast(async_sessionmaker[AsyncSession], object()), FrozenClock(), UuidV7Generator()
    )
    for _ in range(100):
        assert 0 <= queue._jitter() <= 5000  # noqa: PLR2004 — domyślny jitter 0..5000 ms (C7)
