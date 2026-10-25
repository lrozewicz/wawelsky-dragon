"""Testy unit DbTaskQueue i repozytorium tasks na atrapie sesji (bramka pokrycia verify-fast).

Wyrocznia szybka wyklucza testy ``-m db``, więc logika statusów (fail/reaper/cancel/release)
i parametry SQL są sprawdzone tu, bez bazy. Semantykę na prawdziwej MariaDB pokrywają
testy ``-m db`` w ``tests/integration/queue`` (brief T2) — te testy ich nie zastępują.
"""

import logging
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import UuidV7Generator
from app.worker.errors import PermanentError, TransientError
from app.worker.queue import DbTaskQueue, NewTask, backoff_ms
from tests.fakes.clock import FrozenClock

_NOW = 1790157600000

# Wiersz tasks po claimu (klucze jak w SELECT repozytorium).
_ROW_OURS: dict[str, Any] = {
    "public_id": "a" * 32,
    "task_type": "parse_document",
    "payload": '{"a": 1}',
    "document_id": "d" * 32,
    "dataset_id": "s" * 32,
    "priority": 0,
    "status": "running",
    "attempts": 1,
    "max_attempts": 3,
    "cancel_requested": 0,
    "progress": 0.0,
    "progress_msg": "",
    "digest": None,
    "error": None,
    "locked_by": "w:1:0",
}


class _FakeResult:
    """Atrapa Result/CursorResult: scalar, mappings().first()/.all(), rowcount."""

    def __init__(
        self,
        scalar: Any = None,
        rows: list[dict[str, Any]] | None = None,
        rowcount: int = 0,
    ) -> None:
        self._scalar = scalar
        self._rows = rows if rows is not None else []
        self.rowcount = rowcount

    def scalar(self) -> Any:
        return self._scalar

    def mappings(self) -> "_FakeResult":
        return self

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _FakeTransaction:
    """Atrapa transakcji sesji (async context manager)."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    """Atrapa AsyncSession: execute zdejmuje wyniki z kolejki i rejestruje wywołania."""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.executed: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.executed.append((str(statement), params))
        return self._results.pop(0)

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSessionmaker:
    """Atrapa async_sessionmaker: każde wywołanie zwraca tę samą sesję."""

    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def __call__(self) -> _FakeSession:
        return self.session


def _queue(session: _FakeSession) -> DbTaskQueue:
    maker = cast(async_sessionmaker[AsyncSession], _FakeSessionmaker(session))
    return DbTaskQueue(maker, FrozenClock(_NOW), UuidV7Generator(), jitter=lambda: 0)


def _sql(session: _FakeSession, index: int) -> str:
    return session.executed[index][0]


def _params(session: _FakeSession, index: int) -> dict[str, Any]:
    return session.executed[index][1] or {}


async def test_enqueue_inserts_queued_row() -> None:
    session = _FakeSession([_FakeResult()])
    queue = _queue(session)
    public_id = await queue.enqueue(NewTask("parse_document", {"a": 1}))
    assert len(public_id) == 32  # noqa: PLR2004 — public_id = 32 hex
    assert "INSERT INTO tasks" in _sql(session, 0)
    params = _params(session, 0)
    assert params["public_id"] == public_id
    assert params["task_type"] == "parse_document"
    assert params["payload"] == '{"a": 1}'
    assert params["next_attempt_at"] == _NOW
    assert params["now"] == _NOW
    assert params["max_attempts"] == 3  # noqa: PLR2004 — domyślny NewTask


async def test_claim_runs_select_update_fetch() -> None:
    session = _FakeSession(
        [
            _FakeResult(rows=[{"id": 1, "public_id": "a" * 32, "cancel_requested": 0}]),
            _FakeResult(),
            _FakeResult(rows=[dict(_ROW_OURS)]),
        ]
    )
    queue = _queue(session)
    row = await queue.claim("w:1:0", ["parse_document"])
    assert row is not None
    assert row.id == "a" * 32
    assert row.status == "running"
    assert row.attempts == 1
    assert row.locked_by == "w:1:0"
    assert row.payload == {"a": 1}
    assert row.cancel_requested is False
    assert row.progress == 0.0
    assert "SKIP LOCKED" in _sql(session, 0)
    assert "cancel_requested" in _sql(session, 0)
    assert _params(session, 0)["types"] == ["parse_document"]
    assert _params(session, 0)["now"] == _NOW
    assert "attempts = attempts + 1" in _sql(session, 1)
    assert _params(session, 1)["worker_id"] == "w:1:0"
    assert _params(session, 1)["id"] == 1
    assert "WHERE id" in _sql(session, 2)


async def test_claim_cancels_queued_cancel_requested_and_takes_next(caplog: Any) -> None:
    """Wyścig Stop/claim (C5): queued z cancel_requested=1 → cancelled, claim bierze następne."""
    caplog.set_level(logging.INFO, logger="app.worker.queue")
    session = _FakeSession(
        [
            _FakeResult(rows=[{"id": 1, "public_id": "b" * 32, "cancel_requested": 1}]),
            _FakeResult(rowcount=1),  # UPDATE zadania → cancelled
            _FakeResult(),  # hook §6.3: cancel_by_task
            _FakeResult(rows=[{"id": 2, "public_id": "a" * 32, "cancel_requested": 0}]),
            _FakeResult(),
            _FakeResult(rows=[dict(_ROW_OURS)]),
        ]
    )
    queue = _queue(session)
    row = await queue.claim("w:1:0", ["parse_document"])
    assert row is not None
    assert row.id == "a" * 32
    assert "status = 'cancelled'" in _sql(session, 1)
    assert _params(session, 1)["public_id"] == "b" * 32
    assert "attempts = attempts + 1" in _sql(session, 4)
    assert _params(session, 4)["id"] == 2  # noqa: PLR2004 — BIGINT drugiego zadania
    assert caplog.records[-1].event == "task_cancelled_on_recovery"
    assert caplog.records[-1].task_id == "b" * 32


async def test_claim_no_task_returns_none_without_update() -> None:
    session = _FakeSession([_FakeResult(rows=[])])
    queue = _queue(session)
    assert await queue.claim("w:1:0", ["parse_document"]) is None
    assert len(session.executed) == 1


async def test_heartbeat_true_from_existence_select() -> None:
    session = _FakeSession([_FakeResult(), _FakeResult(scalar=1)])
    queue = _queue(session)
    assert await queue.heartbeat("a" * 32, "w:1:0", 0.5, "x") is True
    assert "COALESCE(:progress, progress)" in _sql(session, 0)
    assert _params(session, 0)["progress"] == 0.5  # noqa: PLR2004 — FLOAT
    assert _params(session, 0)["msg"] == "x"


async def test_complete_owned() -> None:
    session = _FakeSession([_FakeResult(scalar=1), _FakeResult()])
    queue = _queue(session)
    await queue.complete("a" * 32, "w:1:0")
    assert "FOR UPDATE" in _sql(session, 0)
    assert "status = 'done'" in _sql(session, 1)


async def test_complete_not_ours_is_noop() -> None:
    session = _FakeSession([_FakeResult(scalar=None)])
    queue = _queue(session)
    await queue.complete("a" * 32, "obcy:1:0")
    assert len(session.executed) == 1


async def test_fail_transient_requeues_with_backoff() -> None:
    session = _FakeSession(
        [_FakeResult(rows=[dict(_ROW_OURS)]), _FakeResult(scalar=1), _FakeResult()]
    )
    queue = _queue(session)
    status = await queue.fail("a" * 32, "w:1:0", TransientError("boom"), transient=True)
    assert status == "queued"
    params = _params(session, 2)
    assert params["status"] == "queued"
    assert params["error"] == "TransientError: boom"
    assert params["next_attempt_at"] == _NOW + backoff_ms(1, 0)
    assert params["finished_at"] is None


async def test_fail_transient_dead_at_max_attempts() -> None:
    row = dict(_ROW_OURS, attempts=3)
    # Czwarty wynik — hook §6.3: fail_by_task (DEC-002).
    session = _FakeSession(
        [_FakeResult(rows=[row]), _FakeResult(scalar=1), _FakeResult(), _FakeResult()]
    )
    queue = _queue(session)
    status = await queue.fail("a" * 32, "w:1:0", TransientError("boom"), transient=True)
    assert status == "dead"
    params = _params(session, 2)
    assert params["status"] == "dead"
    assert params["next_attempt_at"] is None
    assert params["finished_at"] == _NOW


async def test_fail_permanent_fails_at_once() -> None:
    # Czwarty wynik — hook §6.3: fail_by_task (DEC-002).
    session = _FakeSession(
        [_FakeResult(rows=[dict(_ROW_OURS)]), _FakeResult(scalar=1), _FakeResult(), _FakeResult()]
    )
    queue = _queue(session)
    status = await queue.fail("a" * 32, "w:1:0", PermanentError("nie wolno"), transient=False)
    assert status == "failed"
    assert _params(session, 2)["status"] == "failed"
    assert _params(session, 2)["error"] == "PermanentError: nie wolno"


async def test_fail_truncates_error_to_4000() -> None:
    session = _FakeSession(
        [_FakeResult(rows=[dict(_ROW_OURS)]), _FakeResult(scalar=1), _FakeResult()]
    )
    queue = _queue(session)
    await queue.fail("a" * 32, "w:1:0", TransientError("x" * 5000), transient=True)
    assert len(_params(session, 2)["error"]) == 4000  # noqa: PLR2004 — limit error (C7)


async def test_fail_not_ours_returns_current_status() -> None:
    row = dict(_ROW_OURS, status="queued", locked_by=None)
    session = _FakeSession([_FakeResult(rows=[row])])
    queue = _queue(session)
    status = await queue.fail("a" * 32, "w:1:0", TransientError("boom"), transient=True)
    assert status == "queued"
    assert len(session.executed) == 1


async def test_mark_cancelled_owned() -> None:
    # Trzeci wynik — hook §6.3: cancel_by_task (DEC-002).
    session = _FakeSession([_FakeResult(scalar=1), _FakeResult(), _FakeResult()])
    queue = _queue(session)
    await queue.mark_cancelled("a" * 32, "w:1:0")
    assert "status = 'cancelled'" in _sql(session, 1)


async def test_release_resets_attempts() -> None:
    session = _FakeSession([_FakeResult(scalar=1), _FakeResult()])
    queue = _queue(session)
    await queue.release("a" * 32, "w:1:0")
    assert "attempts = attempts - 1" in _sql(session, 1)
    assert "next_attempt_at = :now" in _sql(session, 1)


async def test_is_cancel_requested_true() -> None:
    session = _FakeSession([_FakeResult(rows=[dict(_ROW_OURS, cancel_requested=1)])])
    queue = _queue(session)
    assert await queue.is_cancel_requested("a" * 32) is True


async def test_is_cancel_requested_missing_task() -> None:
    session = _FakeSession([_FakeResult(rows=[])])
    queue = _queue(session)
    assert await queue.is_cancel_requested("a" * 32) is False


async def test_request_cancel_sums_rowcounts() -> None:
    # Pierwszy wynik — hook §6.3: cancel_queued PRZED zmianą statusu zadań (DEC-002);
    # indeksy asercji przesunięte o 1 (0→1, 1→2).
    session = _FakeSession([_FakeResult(), _FakeResult(rowcount=1), _FakeResult(rowcount=1)])
    queue = _queue(session)
    assert await queue.request_cancel(document_ids=["d" * 32]) == 2  # noqa: PLR2004 — 2 UPDATE-y
    assert "document_id IN" in _sql(session, 1)
    assert _params(session, 1)["ids"] == ["d" * 32]
    assert "cancel_requested = 1" in _sql(session, 2)


async def test_request_cancel_empty_without_query() -> None:
    session = _FakeSession([])
    queue = _queue(session)
    assert await queue.request_cancel(document_ids=[]) == 0
    assert session.executed == []


async def test_reap_stale_requeues_with_backoff(caplog: Any) -> None:
    # Log reapera jest INFO, a caplog domyślnie łapie tylko WARNING — stąd pusty caplog.
    caplog.set_level(logging.INFO, logger="app.worker.queue")
    stale = {"public_id": "b" * 32, "attempts": 1, "max_attempts": 3, "cancel_requested": 0}
    session = _FakeSession(
        [_FakeResult(scalar=1), _FakeResult(rows=[stale]), _FakeResult(rowcount=1), _FakeResult()]
    )
    queue = _queue(session)
    assert await queue.reap_stale(120) == 1
    assert "GET_LOCK" in _sql(session, 0)
    assert "FOR UPDATE" in _sql(session, 1)
    params = _params(session, 2)
    assert params["status"] == "queued"
    assert params["next_attempt_at"] == _NOW + backoff_ms(1, 0)
    assert "RELEASE_LOCK" in _sql(session, 3)
    assert caplog.records[-1].event == "task_reaped"
    assert caplog.records[-1].task_id == "b" * 32
    assert caplog.records[-1].status == "queued"


async def test_reap_stale_dead_at_max_attempts(caplog: Any) -> None:
    # Log reapera jest INFO, a caplog domyślnie łapie tylko WARNING — stąd pusty caplog.
    caplog.set_level(logging.INFO, logger="app.worker.queue")
    stale = {"public_id": "b" * 32, "attempts": 3, "max_attempts": 3, "cancel_requested": 0}
    # Piąty wynik — hook §6.3: fail_by_task po dead (DEC-002).
    session = _FakeSession(
        [
            _FakeResult(scalar=1),
            _FakeResult(rows=[stale]),
            _FakeResult(rowcount=1),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    queue = _queue(session)
    assert await queue.reap_stale(120) == 1
    params = _params(session, 2)
    assert params["status"] == "dead"
    assert params["error"] == "TaskLost: heartbeat timeout"
    assert params["finished_at"] == _NOW
    assert caplog.records[-1].status == "dead"


async def test_reap_stale_without_lock_does_nothing() -> None:
    session = _FakeSession([_FakeResult(scalar=0)])
    queue = _queue(session)
    assert await queue.reap_stale(120) == 0
    assert len(session.executed) == 1


async def test_reap_stale_cancels_cancel_requested(caplog: Any) -> None:
    """Zadanie z zapisanym anulowaniem kończy się jako cancelled, bez liczenia prób (C5)."""
    caplog.set_level(logging.INFO, logger="app.worker.queue")
    stale = {
        "public_id": "b" * 32,
        "attempts": 1,
        "max_attempts": 3,
        "cancel_requested": 1,
    }
    session = _FakeSession(
        [
            _FakeResult(scalar=1),
            _FakeResult(rows=[stale]),
            _FakeResult(rowcount=1),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    queue = _queue(session)
    assert await queue.reap_stale(120) == 1
    assert "status = 'cancelled'" in _sql(session, 2)
    assert _params(session, 2)["public_id"] == "b" * 32
    assert "documents" in _sql(session, 3)  # hook §6.3: cancel_by_task
    assert "RELEASE_LOCK" in _sql(session, 4)
    assert caplog.records[-1].event == "task_cancelled_on_recovery"
    assert caplog.records[-1].task_id == "b" * 32


async def test_release_own_host_parses_host_only() -> None:
    # Pierwszy wynik — SELECT zadań running z cancel_requested=1 przed zdjęciem do kolejki (C5).
    session = _FakeSession([_FakeResult(rows=[]), _FakeResult(rowcount=2)])
    queue = _queue(session)
    assert await queue.release_own_host("h:100:0") == 2  # noqa: PLR2004 — rowcount 2 zadań
    params = _params(session, 0)
    assert params["host"] == "h"
    # K2: pid usunięty z SQL — po restarcie kontenera pid bywa ten sam.
    assert "pid" not in params
    assert "SUBSTRING_INDEX" in _sql(session, 0)
    assert "SUBSTRING_INDEX" in _sql(session, 1)
    assert _params(session, 1)["host"] == "h"


async def test_release_own_host_cancels_cancel_requested(caplog: Any) -> None:
    """Restart workera z zapisanym anulowaniem: zadanie cancelled, nie wraca do kolejki (C5)."""
    caplog.set_level(logging.INFO, logger="app.worker.queue")
    session = _FakeSession(
        [
            _FakeResult(rows=[{"public_id": "c" * 32}]),  # SELECT anulowanych tego hosta
            _FakeResult(rowcount=1),  # UPDATE zadania → cancelled
            _FakeResult(),  # hook §6.3: cancel_by_task
            _FakeResult(rowcount=1),  # UPDATE pozostałych running → queued
        ]
    )
    queue = _queue(session)
    # Zwracana liczba = zwrócone do kolejki ORAZ anulowane (kontrakt C5).
    assert await queue.release_own_host("h:100:0") == 2  # noqa: PLR2004
    assert "status = 'cancelled'" in _sql(session, 1)
    assert "cancel_requested = 1" in _sql(session, 1)
    assert _params(session, 1)["public_id"] == "c" * 32
    assert "status = 'queued'" in _sql(session, 3)
    assert caplog.records[-1].event == "task_cancelled_on_recovery"
    assert caplog.records[-1].task_id == "c" * 32
