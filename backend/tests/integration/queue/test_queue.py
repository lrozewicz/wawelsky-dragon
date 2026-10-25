"""Testy kolejki DbTaskQueue na prawdziwej MariaDB (brief T2, wymaganie 8)."""

from typing import cast

import pymysql
import pytest
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.worker.errors import PermanentError, TransientError
from app.worker.queue import DbTaskQueue, NewTask, TaskRow, backoff_ms
from tests.fakes.clock import FrozenClock
from tests.integration.queue.conftest import insert_document

pytestmark = pytest.mark.db

_WORKER = "h:1:0"


def _queue(sm: async_sessionmaker[AsyncSession], clock: FrozenClock) -> DbTaskQueue:
    """Kolejka na fixture'owej sesji, zegar przesuwalny, jitter 0 (deterministycznie)."""
    return DbTaskQueue(sm, clock, UuidV7Generator(), jitter=lambda: 0)


async def _row(sm: async_sessionmaker[AsyncSession], public_id: str) -> RowMapping:
    """Odczyt wiersza tasks po public_id, poza kolejką."""
    async with sm() as session:
        result = await session.execute(
            text("SELECT * FROM tasks WHERE public_id = :public_id"), {"public_id": public_id}
        )
        return result.mappings().one()


async def _claim(queue: DbTaskQueue, worker_id: str = _WORKER) -> TaskRow:
    """Claim z asercją, że zadanie było; zwraca TaskRow."""
    row = await queue.claim(worker_id, ["parse_document"])
    assert row is not None
    return row


async def test_enqueue_then_claim(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    _, document_id = insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    public_id = await queue.enqueue(NewTask("parse_document", {"a": 1}, document_id=document_id))
    assert len(public_id) == 32  # noqa: PLR2004 — public_id = 32 hex
    row = await _row(sm, public_id)
    assert row["status"] == "queued"
    assert row["attempts"] == 0
    assert row["next_attempt_at"] == clock.now_ms()
    claimed = await _claim(queue)
    assert claimed.id == public_id
    assert claimed.status == "running"
    assert claimed.attempts == 1
    assert claimed.locked_by == _WORKER
    assert claimed.payload == {"a": 1}


async def test_claim_empty_types_returns_none(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    public_id = await queue.enqueue(NewTask("parse_document"))
    assert await queue.claim(_WORKER, []) is None
    assert (await _row(sm, public_id))["status"] == "queued"


async def test_claim_other_type_returns_none(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    public_id = await queue.enqueue(NewTask("parse_document"))
    assert await queue.claim(_WORKER, ["reembed_dataset"]) is None
    assert (await _row(sm, public_id))["status"] == "queued"


async def test_priority_and_fifo(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    first = await queue.enqueue(NewTask("parse_document", priority=0))
    high = await queue.enqueue(NewTask("parse_document", priority=1))
    second = await queue.enqueue(NewTask("parse_document", priority=0))
    claimed = [await _claim(queue) for _ in range(3)]
    assert [task.id for task in claimed] == [high, first, second]


async def test_transient_fail_backs_off_until_clock_advances(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    assert await queue.fail(task_id, _WORKER, TransientError("boom"), transient=True) == "queued"
    row = await _row(sm, task_id)
    assert row["next_attempt_at"] == clock.now_ms() + 20_000
    assert await queue.claim("h:2:0", ["parse_document"]) is None
    clock.advance(20_000)
    retry = await _claim(queue, "h:2:0")
    assert retry.attempts == 2  # noqa: PLR2004 — druga próba po backoffzie


async def test_heartbeat_own_saves_progress(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    assert await queue.heartbeat(task_id, _WORKER, 0.5, "parsowanie") is True
    row = await _row(sm, task_id)
    assert float(row["progress"]) == 0.5  # noqa: PLR2004 — FLOAT
    assert row["progress_msg"] == "parsowanie"


async def test_heartbeat_foreign_worker_false(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    assert await queue.heartbeat(task_id, "obcy:1:0", 0.5, "x") is False


async def test_heartbeat_after_complete_false(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    await queue.complete(task_id, _WORKER)
    assert await queue.heartbeat(task_id, _WORKER, 0.9, None) is False


async def test_heartbeat_none_keeps_progress(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    assert await queue.heartbeat(task_id, _WORKER, 0.25, "a") is True
    assert await queue.heartbeat(task_id, _WORKER, None, None) is True
    row = await _row(sm, task_id)
    assert float(row["progress"]) == 0.25  # noqa: PLR2004 — FLOAT
    assert row["progress_msg"] == "a"


async def test_complete_sets_done(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    await queue.complete(task_id, _WORKER)
    row = await _row(sm, task_id)
    assert row["status"] == "done"
    assert float(row["progress"]) == 1
    assert row["finished_at"] == clock.now_ms()
    assert row["locked_by"] is None


async def test_complete_foreign_worker_is_noop(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    await queue.complete(task_id, "obcy:1:0")
    row = await _row(sm, task_id)
    assert row["status"] == "running"
    assert row["attempts"] == 1


async def test_mark_cancelled_sets_finished(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    await queue.mark_cancelled(task_id, _WORKER)
    row = await _row(sm, task_id)
    assert row["status"] == "cancelled"
    assert row["finished_at"] == clock.now_ms()
    assert row["locked_by"] is None
    # Obcy worker nie anuluje cudzego zadania.
    task2 = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue, "h:9:9")
    await queue.mark_cancelled(task2, "obcy:1:0")
    assert (await _row(sm, task2))["status"] == "running"


async def test_transient_fail_requeues_with_error(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    status = await queue.fail(task_id, _WORKER, TransientError("boom"), transient=True)
    assert status == "queued"
    row = await _row(sm, task_id)
    assert row["error"] == "TransientError: boom"
    assert row["next_attempt_at"] == clock.now_ms() + backoff_ms(1, 0)
    assert row["locked_by"] is None


async def test_transient_fail_dead_after_max_attempts(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    task_id = await queue.enqueue(NewTask("parse_document"))
    for attempt, expected in enumerate(("queued", "queued"), start=1):
        await _claim(queue)
        status = await queue.fail(task_id, _WORKER, TransientError("boom"), transient=True)
        assert status == expected
        # Backoff rośnie wykładniczo: 20 s, potem 40 s.
        backoff = backoff_ms(attempt, 0)
        assert (await _row(sm, task_id))["next_attempt_at"] == clock.now_ms() + backoff
        clock.advance(backoff)
    await _claim(queue)
    assert await queue.fail(task_id, _WORKER, TransientError("boom"), transient=True) == "dead"
    assert (await _row(sm, task_id))["status"] == "dead"


async def test_permanent_fail_fails_at_once(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    status = await queue.fail(task_id, _WORKER, PermanentError("nie wolno"), transient=False)
    assert status == "failed"
    row = await _row(sm, task_id)
    assert row["status"] == "failed"
    assert row["attempts"] == 1
    assert row["error"] == "PermanentError: nie wolno"


async def test_fail_error_truncated_to_4000(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    await queue.fail(task_id, _WORKER, TransientError("x" * 5000), transient=True)
    assert len((await _row(sm, task_id))["error"]) == 4000  # noqa: PLR2004 — limit error (C7)


async def test_fail_foreign_worker_returns_current_status(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    status = await queue.fail(task_id, "obcy:1:0", TransientError("boom"), transient=True)
    assert status == "running"
    assert (await _row(sm, task_id))["status"] == "running"


async def test_release_requeues_with_attempts_reset(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    await queue.release(task_id, _WORKER)
    row = await _row(sm, task_id)
    assert row["status"] == "queued"
    assert row["attempts"] == 0
    assert row["locked_by"] is None
    again = await _claim(queue, "h:2:0")
    assert again.id == task_id
    assert again.attempts == 1


async def test_release_foreign_worker_is_noop(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    await queue.release(task_id, "obcy:1:0")
    row = await _row(sm, task_id)
    assert row["status"] == "running"
    assert row["attempts"] == 1
    assert row["locked_by"] == _WORKER


async def test_release_own_host(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    ids = [await queue.enqueue(NewTask("parse_document")) for _ in range(4)]
    claimed = {
        "h:99:0": await _claim(queue, "h:99:0"),
        "h:99:1": await _claim(queue, "h:99:1"),
        "h:100:1": await _claim(queue, "h:100:1"),
        "other:99:0": await _claim(queue, "other:99:0"),
    }
    assert claimed["h:99:0"].id == ids[0]
    # Nowa semantyka (kontrakt K2): zwalniamy WSZYSTKIE running tego hosta, niezależnie od
    # pid/slotu — po restarcie kontenera pid bywa ten sam, więc nie odróżnia osieroconego zadania.
    assert await queue.release_own_host("h:100:0") == 3  # noqa: PLR2004 — 3 zadania
    assert (await _row(sm, ids[0]))["status"] == "queued"
    assert (await _row(sm, ids[1]))["status"] == "queued"
    assert (await _row(sm, ids[2]))["status"] == "queued"
    assert (await _row(sm, ids[3]))["status"] == "running"


async def test_release_own_host_same_pid_after_container_restart(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    """Po restarcie kontenera worker ma ten sam host i znów PID 1 (kontrakt K1)."""
    insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    task_id = await queue.enqueue(NewTask("parse_document"))
    claimed = await _claim(queue, "h:1:0")
    assert claimed.attempts == 1
    # Ten sam host i pid jak po `docker kill` + restarcie: zadanie musi wrócić do kolejki.
    assert await queue.release_own_host("h:1:0") == 1
    row = await _row(sm, task_id)
    assert row["status"] == "queued"
    assert row["locked_by"] is None
    assert row["attempts"] == claimed.attempts - 1


async def test_request_cancel(sm: async_sessionmaker[AsyncSession], migrated_db: Settings) -> None:
    _, doc_a = insert_document(migrated_db)
    _, doc_b = insert_document(migrated_db)
    queue = _queue(sm, FrozenClock())
    running_id = await queue.enqueue(NewTask("parse_document", document_id=doc_a))
    queued_id = await queue.enqueue(NewTask("parse_document", document_id=doc_a))
    other_id = await queue.enqueue(NewTask("parse_document", document_id=doc_b))
    await _claim(queue)
    assert await queue.request_cancel(document_ids=[doc_a]) == 2  # noqa: PLR2004 — 2 UPDATE-y
    row_running = await _row(sm, running_id)
    assert row_running["status"] == "running"
    assert int(row_running["cancel_requested"]) == 1
    assert await queue.is_cancel_requested(running_id) is True
    assert (await _row(sm, queued_id))["status"] == "cancelled"
    assert (await _row(sm, other_id))["status"] == "queued"
    assert await queue.is_cancel_requested(other_id) is False
    assert await queue.request_cancel(document_ids=[]) == 0


async def test_reap_stale_requeues_and_keeps_fresh(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    stale_id = await queue.enqueue(NewTask("parse_document"))
    fresh_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue, "h:1:0")
    await _claim(queue, "h:1:1")
    clock.advance(121_000)
    # Świeżemu odświeżamy heartbeat — przestaje być przestarzały.
    assert await queue.heartbeat(fresh_id, "h:1:1", None, None) is True
    assert await queue.reap_stale(120) == 1
    row = await _row(sm, stale_id)
    assert row["status"] == "queued"
    assert row["next_attempt_at"] == clock.now_ms() + backoff_ms(1, 0)
    assert row["locked_by"] is None
    assert (await _row(sm, fresh_id))["status"] == "running"


async def test_reap_stale_dead_at_max_attempts(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    task_id = await queue.enqueue(NewTask("parse_document", max_attempts=1))
    await _claim(queue)
    clock.advance(121_000)
    assert await queue.reap_stale(120) == 1
    row = await _row(sm, task_id)
    assert row["status"] == "dead"
    assert row["error"] == "TaskLost: heartbeat timeout"
    assert row["finished_at"] == clock.now_ms()


async def test_reap_stale_skips_when_reaper_lock_taken(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    insert_document(migrated_db)
    clock = FrozenClock()
    queue = _queue(sm, clock)
    task_id = await queue.enqueue(NewTask("parse_document"))
    await _claim(queue)
    clock.advance(121_000)
    connection = pymysql.connect(
        host=migrated_db.db_host,
        port=migrated_db.db_port,
        user=migrated_db.db_user,
        password=migrated_db.db_password.get_secret_value(),
        database=migrated_db.db_name,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK('wd_reaper', 0)")
            assert cursor.fetchone() == (1,)
        assert await queue.reap_stale(120) == 0
        assert (await _row(sm, task_id))["status"] == "running"
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT RELEASE_LOCK('wd_reaper')")
        connection.close()


async def test_read_committed_isolation(sm: async_sessionmaker[AsyncSession]) -> None:
    async with sm() as session:
        result = await session.execute(text("SELECT @@transaction_isolation"))
        value = cast("str | None", result.scalar())
    assert value == "READ-COMMITTED"
