"""Repozytorium tabeli tasks — SQLAlchemy Core ``text()`` z parametrami (K5 §0.1, kontrakt C8).

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
Duże BIGINT ``id`` nie wychodzi poza repozytorium — na zewnątrz tylko ``public_id``.
"""

from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms
from app.db.repositories import documents as documents_repo

# Kolumny TaskRow (K5 §2.1) — pełne literały SQL, bez interpolacji.
_GET_SQL = text(
    "SELECT public_id, task_type, payload, document_id, dataset_id, priority, status,"
    " attempts, max_attempts, cancel_requested, progress, progress_msg, digest, error, locked_by"
    " FROM tasks WHERE public_id = :public_id"
)

_CLAIM_FETCH_SQL = text(
    "SELECT public_id, task_type, payload, document_id, dataset_id, priority, status,"
    " attempts, max_attempts, cancel_requested, progress, progress_msg, digest, error, locked_by"
    " FROM tasks WHERE id = :id"
)

# Claim dosłownie wg briefu T2 / 04-dane-mariadb.md §7; cancel_requested do rozstrzygnięcia
# wyścigu „Stop tuż przed claimem” (kontrakt C5).
_CLAIM_SELECT_SQL = text(
    "SELECT id, public_id, cancel_requested FROM tasks"
    " WHERE status = 'queued' AND next_attempt_at <= :now AND task_type IN :types"
    " ORDER BY priority DESC, next_attempt_at, id"
    " LIMIT 1"
    " FOR UPDATE SKIP LOCKED"
).bindparams(bindparam("types", expanding=True))

_CLAIM_UPDATE_SQL = text(
    "UPDATE tasks SET status = 'running', attempts = attempts + 1, locked_by = :worker_id,"
    " locked_at = :now, heartbeat_at = :now, started_at = COALESCE(started_at, :now),"
    " update_time = :now, update_date = :now_date WHERE id = :id"
)

_INSERT_SQL = text(
    "INSERT INTO tasks (public_id, task_type, payload, document_id, dataset_id, priority,"
    " status, attempts, max_attempts, next_attempt_at, digest,"
    " create_time, create_date, update_time, update_date)"
    " VALUES (:public_id, :task_type, :payload, :document_id, :dataset_id, :priority,"
    " 'queued', 0, :max_attempts, :next_attempt_at, :digest,"
    " :now, :now_date, :now, :now_date)"
)

# „Nasze” = running + locked_by = worker_id; SELECT ... FOR UPDATE przed UPDATE (kontrakt C7).
_OWNED_SELECT_SQL = text(
    "SELECT 1 FROM tasks"
    " WHERE public_id = :public_id AND locked_by = :worker_id AND status = 'running'"
    " FOR UPDATE"
)

_HEARTBEAT_UPDATE_SQL = text(
    "UPDATE tasks SET heartbeat_at = :now, progress = COALESCE(:progress, progress),"
    " progress_msg = COALESCE(:msg, progress_msg),"
    " update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id AND locked_by = :worker_id AND status = 'running'"
)

_HEARTBEAT_EXISTS_SQL = text(
    "SELECT 1 FROM tasks"
    " WHERE public_id = :public_id AND locked_by = :worker_id AND status = 'running'"
)

_SET_DONE_UPDATE_SQL = text(
    "UPDATE tasks SET status = 'done', progress = 1, finished_at = :now, locked_by = NULL,"
    " update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id AND locked_by = :worker_id AND status = 'running'"
)

_SET_CANCELLED_UPDATE_SQL = text(
    "UPDATE tasks SET status = 'cancelled', finished_at = :now, locked_by = NULL,"
    " update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id AND locked_by = :worker_id AND status = 'running'"
)

# next_attempt_at/finished_at zostają bez zmian, gdy parametr to NULL (COALESCE).
_SET_FAILED_UPDATE_SQL = text(
    "UPDATE tasks SET status = :status, error = :error,"
    " next_attempt_at = COALESCE(:next_attempt_at, next_attempt_at),"
    " finished_at = COALESCE(:finished_at, finished_at),"
    " locked_by = NULL, locked_at = NULL, heartbeat_at = NULL,"
    " update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id AND locked_by = :worker_id AND status = 'running'"
)

_RELEASE_UPDATE_SQL = text(
    "UPDATE tasks SET status = 'queued', locked_by = NULL, locked_at = NULL,"
    " heartbeat_at = NULL, attempts = attempts - 1, next_attempt_at = :now,"
    " update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id AND locked_by = :worker_id AND status = 'running'"
)

_CANCEL_QUEUED_SQL = text(
    "UPDATE tasks SET status = 'cancelled', finished_at = :now,"
    " update_time = :now, update_date = :now_date"
    " WHERE document_id IN :ids AND status = 'queued'"
).bindparams(bindparam("ids", expanding=True))

_CANCEL_RUNNING_SQL = text(
    "UPDATE tasks SET cancel_requested = 1, update_time = :now, update_date = :now_date"
    " WHERE document_id IN :ids AND status = 'running'"
).bindparams(bindparam("ids", expanding=True))

_STALE_SELECT_SQL = text(
    "SELECT public_id, attempts, max_attempts, cancel_requested FROM tasks"
    " WHERE status = 'running' AND heartbeat_at < :before FOR UPDATE"
)

# Restart hosta: wiersze running tego hosta z zapisanym anulowaniem (C5) — zamykane, nie wznawiane.
_HOST_CANCEL_SELECT_SQL = text(
    "SELECT public_id FROM tasks"
    " WHERE status = 'running' AND cancel_requested = 1"
    " AND SUBSTRING_INDEX(locked_by, ':', 1) = :host"
    " FOR UPDATE"
)

# Odzyskiwanie zadania z zapisanym anulowaniem (restart hosta, reaper, wyścig przy claimie): C5.
# Kształt jak _SET_CANCELLED_UPDATE_SQL; wołane na wierszu już zablokowanym FOR UPDATE.
_CANCEL_RECOVERY_SQL = text(
    "UPDATE tasks SET status = 'cancelled', finished_at = :now, locked_by = NULL,"
    " update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id AND cancel_requested = 1"
    " AND status IN ('queued', 'running')"
)

# error/finished_at/next_attempt_at dopisywane tylko, gdy parametr != NULL (COALESCE).
_REQUEUE_UPDATE_SQL = text(
    "UPDATE tasks SET status = :status,"
    " next_attempt_at = COALESCE(:next_attempt_at, next_attempt_at),"
    " error = COALESCE(:error, error),"
    " finished_at = COALESCE(:finished_at, finished_at),"
    " locked_by = NULL, locked_at = NULL, heartbeat_at = NULL,"
    " update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id"
)

_RELEASE_HOST_SQL = text(
    "UPDATE tasks SET status = 'queued', locked_by = NULL, locked_at = NULL,"
    " heartbeat_at = NULL, attempts = attempts - 1, next_attempt_at = :now,"
    " update_time = :now, update_date = :now_date"
    " WHERE status = 'running'"
    " AND SUBSTRING_INDEX(locked_by, ':', 1) = :host"
)

_GET_LOCK_SQL = text("SELECT GET_LOCK('wd_reaper', 0)")
_RELEASE_LOCK_SQL = text("SELECT RELEASE_LOCK('wd_reaper')")


async def insert(  # noqa: PLR0913 — kształt kontraktu C8: kolumny tasks
    session: AsyncSession,
    *,
    public_id: str,
    task_type: str,
    payload_json: str,
    document_id: str | None,
    dataset_id: str | None,
    priority: int,
    max_attempts: int,
    digest: str | None,
    next_attempt_at: int,
    now_ms: int,
) -> None:
    """Wstawia zadanie w stanie queued (kontrakt C7: enqueue)."""
    await session.execute(
        _INSERT_SQL,
        {
            "public_id": public_id,
            "task_type": task_type,
            "payload": payload_json,
            "document_id": document_id,
            "dataset_id": dataset_id,
            "priority": priority,
            "max_attempts": max_attempts,
            "next_attempt_at": next_attempt_at,
            "digest": digest,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def claim_next(
    session: AsyncSession, *, worker_id: str, types: list[str], now_ms: int
) -> tuple[RowMapping | None, list[str]]:
    """Bierze zadanie według 04 §7 (FOR UPDATE SKIP LOCKED) i ustawia running.

    Zadanie ``queued`` z ``cancel_requested=1`` (wyścig: Stop trafił między wygaśnięciem a claimem)
    kończy jako ``cancelled`` bez uruchamiania handlera i szuka następnego (kontrakt C5).
    Zwraca ``(wiersz zadania running albo None, public_id zadań zamkniętych jako cancelled)``.
    """
    cancelled: list[str] = []
    while True:
        row = (
            (await session.execute(_CLAIM_SELECT_SQL, {"types": types, "now": now_ms}))
            .mappings()
            .first()
        )
        if row is None:
            return None, cancelled
        if not bool(row["cancel_requested"]):
            break
        public_id = str(row["public_id"])
        await cancel_on_recovery(session, public_id=public_id, now_ms=now_ms)
        cancelled.append(public_id)
    big_id = cast("int", row["id"])
    await session.execute(
        _CLAIM_UPDATE_SQL,
        {"worker_id": worker_id, "now": now_ms, "now_date": from_ms(now_ms), "id": big_id},
    )
    return (await session.execute(_CLAIM_FETCH_SQL, {"id": big_id})).mappings().first(), cancelled


async def get(session: AsyncSession, public_id: str) -> RowMapping | None:
    """Odczyt wiersza po public_id w dowolnym statusie."""
    return (await session.execute(_GET_SQL, {"public_id": public_id})).mappings().first()


async def _owned(session: AsyncSession, *, public_id: str, worker_id: str) -> bool:
    """Czy zadanie jest „nasze” — SELECT ... FOR UPDATE przed UPDATE (kontrakt C7)."""
    row = (
        await session.execute(_OWNED_SELECT_SQL, {"public_id": public_id, "worker_id": worker_id})
    ).scalar()
    return row is not None


async def heartbeat(  # noqa: PLR0913 — kształt kontraktu C8
    session: AsyncSession,
    *,
    public_id: str,
    worker_id: str,
    progress: float | None,
    msg: str | None,
    now_ms: int,
) -> bool:
    """Heartbeat „naszego” zadania; wynik z SELECT-a, nie z rowcount (kontrakt C7)."""
    await session.execute(
        _HEARTBEAT_UPDATE_SQL,
        {
            "now": now_ms,
            "now_date": from_ms(now_ms),
            "progress": progress,
            "msg": msg,
            "public_id": public_id,
            "worker_id": worker_id,
        },
    )
    exists = (
        await session.execute(
            _HEARTBEAT_EXISTS_SQL, {"public_id": public_id, "worker_id": worker_id}
        )
    ).scalar()
    return exists is not None


async def set_done(session: AsyncSession, *, public_id: str, worker_id: str, now_ms: int) -> bool:
    """done, progress=1, finished_at, locked_by=NULL — tylko „nasze” (kontrakt C7)."""
    if not await _owned(session, public_id=public_id, worker_id=worker_id):
        return False
    await session.execute(
        _SET_DONE_UPDATE_SQL,
        {
            "now": now_ms,
            "now_date": from_ms(now_ms),
            "public_id": public_id,
            "worker_id": worker_id,
        },
    )
    return True


async def set_cancelled(
    session: AsyncSession, *, public_id: str, worker_id: str, now_ms: int
) -> bool:
    """cancelled, finished_at, locked_by=NULL — tylko „nasze” (kontrakt C7)."""
    if not await _owned(session, public_id=public_id, worker_id=worker_id):
        return False
    await session.execute(
        _SET_CANCELLED_UPDATE_SQL,
        {
            "now": now_ms,
            "now_date": from_ms(now_ms),
            "public_id": public_id,
            "worker_id": worker_id,
        },
    )
    # §6.3: dokument → run='2' + linia cancelled (tylko parse_document — filtr w SQL C2.2).
    await documents_repo.cancel_by_task(session, public_id, now_ms=now_ms)
    return True


async def cancel_on_recovery(session: AsyncSession, *, public_id: str, now_ms: int) -> bool:
    """Zadanie (queued/running) z ``cancel_requested=1`` → cancelled + dokument ``run='2'`` (C5).

    Wołane przy odzyskiwaniu zadania po padzie workera (``release_host``, reaper) oraz przy
    wyścigu Stop/claim; wiersz jest już zablokowany ``FOR UPDATE`` przez wołającego
    (kolejność blokad: zadanie → dokument, jak w ``set_cancelled``).
    """
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            _CANCEL_RECOVERY_SQL,
            {"public_id": public_id, "now": now_ms, "now_date": from_ms(now_ms)},
        ),
    )
    if result.rowcount != 1:
        return False
    # §6.3: dokument → run='2' + linia cancelled (tylko parse_document — filtr w SQL C2.2).
    await documents_repo.cancel_by_task(session, public_id, now_ms=now_ms)
    return True


async def cancel_running_of_host(session: AsyncSession, *, host: str, now_ms: int) -> list[str]:
    """Zamyka zadania running tego hosta z ``cancel_requested=1``; zwraca ich public_id (C5).

    Wołane przez ``release_own_host`` PRZED zdjęciem zadań hosta do kolejki — anulowane zadanie
    po restarcie nie może wrócić do ``queued``.
    """
    rows = (await session.execute(_HOST_CANCEL_SELECT_SQL, {"host": host})).mappings().all()
    public_ids = [str(row["public_id"]) for row in rows]
    for public_id in public_ids:
        await cancel_on_recovery(session, public_id=public_id, now_ms=now_ms)
    return public_ids


async def set_failed(  # noqa: PLR0913 — kształt kontraktu C8
    session: AsyncSession,
    *,
    public_id: str,
    worker_id: str,
    status: str,
    error: str,
    next_attempt_at: int | None,
    now_ms: int,
) -> bool:
    """Status po fail (queued/dead/failed); finished_at dla statusów terminalnych (kontrakt C7)."""
    if not await _owned(session, public_id=public_id, worker_id=worker_id):
        return False
    await session.execute(
        _SET_FAILED_UPDATE_SQL,
        {
            "status": status,
            "error": error,
            "next_attempt_at": next_attempt_at,
            "finished_at": now_ms if status != "queued" else None,
            "now": now_ms,
            "now_date": from_ms(now_ms),
            "public_id": public_id,
            "worker_id": worker_id,
        },
    )
    if status in ("failed", "dead"):
        # §6.3: dokument → run='4', error z zadania (tylko parse_document — filtr w SQL C2.2).
        await documents_repo.fail_by_task(session, public_id, now_ms=now_ms)
    return True


async def release(session: AsyncSession, *, public_id: str, worker_id: str, now_ms: int) -> bool:
    """Graceful shutdown: queued, attempts-1, bez backoffu — tylko „nasze” (kontrakt C7)."""
    if not await _owned(session, public_id=public_id, worker_id=worker_id):
        return False
    await session.execute(
        _RELEASE_UPDATE_SQL,
        {
            "now": now_ms,
            "now_date": from_ms(now_ms),
            "public_id": public_id,
            "worker_id": worker_id,
        },
    )
    return True


async def cancel_by_documents(
    session: AsyncSession, *, document_ids: list[str], now_ms: int
) -> int:
    """queued → cancelled, running → cancel_requested=1; zwraca liczbę dotkniętych (kontrakt C7)."""
    params: dict[str, Any] = {
        "ids": document_ids,
        "now": now_ms,
        "now_date": from_ms(now_ms),
    }
    # §6.3 PRZED zmianą statusu zadań: run='2' dla dokumentów z zadaniem queued (decyduje
    # istnienie queued — filtr klasy zadania w SQL C2.2).
    await documents_repo.cancel_queued(session, document_ids, now_ms=now_ms)
    queued = cast("CursorResult[Any]", await session.execute(_CANCEL_QUEUED_SQL, params))
    running = cast("CursorResult[Any]", await session.execute(_CANCEL_RUNNING_SQL, params))
    return queued.rowcount + running.rowcount


async def stale_running(session: AsyncSession, *, before_ms: int) -> list[RowMapping]:
    """Zadania running z heartbeat starszym niż before_ms — FOR UPDATE (kontrakt C7)."""
    result = await session.execute(_STALE_SELECT_SQL, {"before": before_ms})
    return list(result.mappings().all())


async def requeue_or_dead(  # noqa: PLR0913 — kształt kontraktu C8
    session: AsyncSession,
    *,
    public_id: str,
    status: str,
    error: str | None,
    finished_at: int | None,
    next_attempt_at: int | None,
    now_ms: int,
) -> bool:
    """Przejęcie przez reapera: queued z backoffem albo dead (kontrakt C7)."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            _REQUEUE_UPDATE_SQL,
            {
                "status": status,
                "error": error,
                "finished_at": finished_at,
                "next_attempt_at": next_attempt_at,
                "now": now_ms,
                "now_date": from_ms(now_ms),
                "public_id": public_id,
            },
        ),
    )
    if result.rowcount == 1 and status == "dead":
        # §6.3: reaper → dead oznacza dokument run='4' (tylko parse_document — SQL C2.2).
        await documents_repo.fail_by_task(session, public_id, now_ms=now_ms)
    return result.rowcount == 1


async def release_host(session: AsyncSession, *, host: str, now_ms: int) -> int:
    """Zadania running tego hosta (dowolny pid/slot) → queued (kontrakt C7: release_own_host).

    Zwraca liczbę wierszy zdjętych z kolejki przez ten UPDATE; zadania z ``cancel_requested=1``
    zamyka wcześniej ``cancel_running_of_host`` (kontrakt C5) i nie są tu liczone.
    """
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            _RELEASE_HOST_SQL,
            {"host": host, "now": now_ms, "now_date": from_ms(now_ms)},
        ),
    )
    return result.rowcount


async def acquire_reaper_lock(session: AsyncSession) -> int:
    """GET_LOCK('wd_reaper', 0) na połączeniu sesji; 1 = zajęty (kontrakt C7)."""
    return cast("int", (await session.execute(_GET_LOCK_SQL)).scalar())


async def release_reaper_lock(session: AsyncSession) -> None:
    """RELEASE_LOCK('wd_reaper') na tym samym połączeniu, w finally (kontrakt C7)."""
    await session.execute(_RELEASE_LOCK_SQL)
