"""Port kolejki zadań i implementacja na MariaDB (K5 §2.1-§2.2, kontrakt C7)."""

import json
import logging
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import IdGenerator
from app.core.timeutil import Clock
from app.db.repositories import tasks as tasks_repo
from app.db.repositories import wd_tasks as wd_tasks_repo
from app.db.uow import transaction

logger = logging.getLogger("app.worker.queue")

TaskType = Literal[
    "parse_document",
    "reembed_dataset",
    "integration_sync",
    "delete_dataset_files",
    "cleanup_sessions",
    "purge_cache",
    "export_dataset",
    "import_dataset",
    "build_outline",
]
TaskStatus = Literal["queued", "running", "done", "failed", "cancelled", "dead"]


@dataclass(frozen=True)
class NewTask:
    task_type: TaskType
    payload: Mapping[str, Any] = field(default_factory=dict)
    document_id: str | None = None
    dataset_id: str | None = None
    priority: int = 0  # 1 wysoki, 0 normalny, -1 tło
    max_attempts: int = 3
    digest: str | None = None


@dataclass(frozen=True)
class TaskRow:
    # id = tasks.public_id (32 hex); BIGINT id nie wychodzi poza repozytorium
    id: str
    task_type: TaskType
    payload: dict[str, Any]
    document_id: str | None
    dataset_id: str | None
    priority: int
    status: TaskStatus
    attempts: int
    max_attempts: int
    cancel_requested: bool
    progress: float
    progress_msg: str
    digest: str | None
    error: str | None
    locked_by: str | None


@dataclass(frozen=True)
class TaskSnapshot:
    """Widok wiersza ``tasks`` dla tras WD (K19 §3 trasy 3-4).

    Różni się od ``TaskRow`` (widok claimu) czasami życia zadania i brakiem kolumn
    przypisania do workera — trasy nie potrzebują ``locked_by``/``attempts``.
    """

    id: str
    task_type: TaskType
    payload: dict[str, Any]
    dataset_id: str | None
    status: TaskStatus
    progress: float
    progress_msg: str
    error: str | None
    created_at: int
    finished_at: int | None


class TaskQueue(Protocol):
    # enqueue → public_id; next_attempt_at = now
    async def enqueue(self, t: NewTask) -> str: ...

    # SQL 04 §7 + filtr task_type IN :types; READ COMMITTED; osobna krótka transakcja
    # zadanie queued z cancel_requested=1 kończymy jako cancelled i szukamy następnego (C5)
    async def claim(self, worker_id: str, types: Sequence[str]) -> TaskRow | None: ...

    # False = zadanie nie jest już nasze (locked_by != worker_id lub status != running)
    # → handler przerywa bez zapisu
    async def heartbeat(
        self, task_id: str, worker_id: str, progress: float | None, msg: str | None
    ) -> bool: ...

    # done, progress=1, finished_at
    async def complete(self, task_id: str, worker_id: str) -> None: ...

    # transient i attempts < max_attempts → queued + backoff; transient i attempts >= max → dead;
    # not transient → failed; error = f"{type(err).__name__}: {err}"[:4000]; zwraca nowy status
    async def fail(
        self, task_id: str, worker_id: str, err: BaseException, *, transient: bool
    ) -> TaskStatus: ...

    # cancelled, finished_at
    async def mark_cancelled(self, task_id: str, worker_id: str) -> None: ...

    # graceful shutdown: queued, locked_by NULL, attempts-1, bez backoffu
    async def release(self, task_id: str, worker_id: str) -> None: ...

    async def is_cancel_requested(self, task_id: str) -> bool: ...

    # queued → cancelled od razu; running → cancel_requested=1; zwraca dotknięte zadania (05 §3.4)
    async def request_cancel(self, *, document_ids: Sequence[str]) -> int: ...

    # pod GET_LOCK('wd_reaper', 0) (brak locka → 0); running z heartbeat_at < now - stale →
    # queued z backoffem albo dead (attempts >= max_attempts); z cancel_requested=1 → cancelled (C5)
    async def reap_stale(self, stale_after_s: int) -> int: ...

    # przy starcie: running z locked_by o tym samym hoście (dowolny pid/slot — po restarcie
    # kontenera pid bywa ten sam) → queued, a z cancel_requested=1 → cancelled (C5);
    # zwraca liczbę zadań dotkniętych (jedne i drugie)
    async def release_own_host(self, worker_id: str) -> int: ...

    # K19 §3 trasa 3: wiersz zadania dla tras WD; None gdy brak public_id
    async def snapshot(self, task_id: str) -> TaskSnapshot | None: ...

    # K19 §3 trasa 4: queued|running → cancel_requested=1; False dla statusu terminalnego
    # (albo braku zadania) — zamknięcie zadania należy do claimu/handlera (C5)
    async def request_cancel_task(self, task_id: str) -> bool: ...


def backoff_ms(attempts: int, jitter_ms: int) -> int:
    """Backoff retry wg 05 §3.3: min(2**attempts * 10 s, 10 min) + jitter."""
    base: int = min(2**attempts * 10_000, 600_000)
    return base + jitter_ms


def _to_task_row(row: RowMapping) -> TaskRow:
    """Mapowanie wiersza DB na TaskRow: payload z JSON, cancel_requested jako int (kontrakt C7)."""
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return TaskRow(
        id=str(row["public_id"]),
        task_type=cast(TaskType, row["task_type"]),
        payload=cast("dict[str, Any]", payload),
        document_id=row["document_id"],
        dataset_id=row["dataset_id"],
        priority=int(row["priority"]),
        status=cast(TaskStatus, row["status"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        cancel_requested=bool(row["cancel_requested"]),
        progress=float(row["progress"]),
        progress_msg=row["progress_msg"],
        digest=row["digest"],
        error=row["error"],
        locked_by=row["locked_by"],
    )


def _log_cancelled_on_recovery(task_ids: Sequence[str]) -> None:
    """Jedno zdarzenie logu na zadanie zamknięte jako cancelled przy odzyskiwaniu (kontrakt C5)."""
    for task_id in task_ids:
        logger.info(
            "task cancelled on recovery",
            extra={"event": "task_cancelled_on_recovery", "task_id": task_id},
        )


class DbTaskQueue:
    """TaskQueue na tabeli tasks: każda metoda = krótka transakcja, SQL w repozytorium (C7)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        id_gen: IdGenerator,
        *,
        jitter: Callable[[], int] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._id_gen = id_gen
        # Domyślny jitter 0..5000 ms; secrets zamiast random (ruff S311).
        self._jitter: Callable[[], int] = (
            jitter if jitter is not None else (lambda: secrets.randbelow(5001))
        )

    async def enqueue(self, t: NewTask) -> str:
        now = self._clock.now_ms()
        public_id = self._id_gen.new_id()
        async with transaction(self._sessionmaker) as session:
            await tasks_repo.insert(
                session,
                public_id=public_id,
                task_type=t.task_type,
                payload_json=json.dumps(dict(t.payload)),
                document_id=t.document_id,
                dataset_id=t.dataset_id,
                priority=t.priority,
                max_attempts=t.max_attempts,
                digest=t.digest,
                next_attempt_at=now,
                now_ms=now,
            )
        return public_id

    async def claim(self, worker_id: str, types: Sequence[str]) -> TaskRow | None:
        if not types:
            return None
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            row, cancelled = await tasks_repo.claim_next(
                session, worker_id=worker_id, types=list(types), now_ms=now
            )
        _log_cancelled_on_recovery(cancelled)
        return _to_task_row(row) if row is not None else None

    async def heartbeat(
        self, task_id: str, worker_id: str, progress: float | None, msg: str | None
    ) -> bool:
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            return await tasks_repo.heartbeat(
                session,
                public_id=task_id,
                worker_id=worker_id,
                progress=progress,
                msg=msg,
                now_ms=now,
            )

    async def complete(self, task_id: str, worker_id: str) -> None:
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            await tasks_repo.set_done(session, public_id=task_id, worker_id=worker_id, now_ms=now)

    async def fail(
        self, task_id: str, worker_id: str, err: BaseException, *, transient: bool
    ) -> TaskStatus:
        error = f"{type(err).__name__}: {err}"[:4000]
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            row = await tasks_repo.get(session, public_id=task_id)
            if row is None:
                raise ValueError(f"task not found: {task_id}")
            if row["locked_by"] != worker_id or row["status"] != "running":
                # Nie nasze → bez zmian, bieżący status z DB (kontrakt C7).
                return cast(TaskStatus, row["status"])
            attempts = int(row["attempts"])
            next_attempt_at: int | None
            if transient and attempts < int(row["max_attempts"]):
                new_status: TaskStatus = "queued"
                next_attempt_at = now + backoff_ms(attempts, self._jitter())
            else:
                new_status = "dead" if transient else "failed"
                next_attempt_at = None
            updated = await tasks_repo.set_failed(
                session,
                public_id=task_id,
                worker_id=worker_id,
                status=new_status,
                error=error,
                next_attempt_at=next_attempt_at,
                now_ms=now,
            )
            if updated:
                return new_status
            fresh = await tasks_repo.get(session, public_id=task_id)
            if fresh is None:
                raise ValueError(f"task not found: {task_id}")
            return cast(TaskStatus, fresh["status"])

    async def mark_cancelled(self, task_id: str, worker_id: str) -> None:
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            await tasks_repo.set_cancelled(
                session, public_id=task_id, worker_id=worker_id, now_ms=now
            )

    async def release(self, task_id: str, worker_id: str) -> None:
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            await tasks_repo.release(session, public_id=task_id, worker_id=worker_id, now_ms=now)

    async def is_cancel_requested(self, task_id: str) -> bool:
        async with transaction(self._sessionmaker) as session:
            row = await tasks_repo.get(session, public_id=task_id)
        return row is not None and bool(row["cancel_requested"])

    async def request_cancel(self, *, document_ids: Sequence[str]) -> int:
        if not document_ids:
            return 0
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            return await tasks_repo.cancel_by_documents(
                session, document_ids=list(document_ids), now_ms=now
            )

    async def reap_stale(self, stale_after_s: int) -> int:
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            # GET_LOCK i RELEASE_LOCK na tym samym połączeniu sesji (kontrakt C7).
            if await tasks_repo.acquire_reaper_lock(session) != 1:
                return 0
            try:
                rows = await tasks_repo.stale_running(session, before_ms=now - stale_after_s * 1000)
                reaped = 0
                cancelled: list[str] = []
                for row in rows:
                    public_id = str(row["public_id"])
                    if bool(row["cancel_requested"]):
                        # Zapamiętane anulowanie: zadanie kończymy, nie wznawiamy (kontrakt C5).
                        await tasks_repo.cancel_on_recovery(
                            session, public_id=public_id, now_ms=now
                        )
                        cancelled.append(public_id)
                        reaped += 1
                        continue
                    attempts = int(row["attempts"])
                    error: str | None
                    finished_at: int | None
                    next_attempt_at: int | None
                    if attempts >= int(row["max_attempts"]):
                        status: TaskStatus = "dead"
                        error = "TaskLost: heartbeat timeout"
                        finished_at = now
                        next_attempt_at = None
                    else:
                        status = "queued"
                        error = None
                        finished_at = None
                        next_attempt_at = now + backoff_ms(attempts, self._jitter())
                    await tasks_repo.requeue_or_dead(
                        session,
                        public_id=public_id,
                        status=status,
                        error=error,
                        finished_at=finished_at,
                        next_attempt_at=next_attempt_at,
                        now_ms=now,
                    )
                    reaped += 1
                    logger.info(
                        "task reaped",
                        extra={
                            "event": "task_reaped",
                            "task_id": public_id,
                            "status": status,
                        },
                    )
                _log_cancelled_on_recovery(cancelled)
                return reaped
            finally:
                await tasks_repo.release_reaper_lock(session)

    async def release_own_host(self, worker_id: str) -> int:
        """Zadania poprzedniego workera tego hosta: anulowane kończymy, resztę wracamy do kolejki.

        Kontrakt C5: ``running`` z ``cancel_requested=1`` → ``cancelled`` (+ dokument ``run='2'``).
        Zwracana liczba to wszystkie dotknięte zadania — zwrócone do kolejki ORAZ anulowane.
        """
        host = worker_id.split(":", maxsplit=1)[0]
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            cancelled = await tasks_repo.cancel_running_of_host(session, host=host, now_ms=now)
            released = await tasks_repo.release_host(session, host=host, now_ms=now)
        _log_cancelled_on_recovery(cancelled)
        return released + len(cancelled)

    async def snapshot(self, task_id: str) -> TaskSnapshot | None:
        """Wiersz zadania dla tras WD (K19 §3 trasa 3); ``None`` gdy brak ``public_id``."""
        async with transaction(self._sessionmaker) as session:
            row = await wd_tasks_repo.get(session, task_id)
        if row is None:
            return None
        return TaskSnapshot(
            id=str(row["public_id"]),
            task_type=cast(TaskType, row["task_type"]),
            payload=cast("dict[str, Any]", row["payload"]),
            dataset_id=cast("str | None", row["dataset_id"]),
            status=cast(TaskStatus, row["status"]),
            progress=float(row["progress"]),
            progress_msg=cast(str, row["progress_msg"]),
            error=cast("str | None", row["error"]),
            created_at=int(row["create_time"]),
            finished_at=cast("int | None", row["finished_at"]),
        )

    async def request_cancel_task(self, task_id: str) -> bool:
        """Zatrzymanie jednego zadania (K19 §3 trasa 4); ``False`` dla statusu terminalnego."""
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            return await wd_tasks_repo.request_cancel(session, public_id=task_id, now_ms=now)
