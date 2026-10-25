"""Runy i zdarzenia synchronizacji — SQL wg kontraktu E4-1 C2 (część pakietu ``integrations``).

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.integrations.rows import (
    EventRow,
    NewEvent,
    RunRow,
    _event_row,
    _rowcount,
    _run_row,
)
from app.integrations.base import SyncCounts

_INSERT_RUN_SQL = text(
    "INSERT INTO integration_sync_runs (integration_id, integration_type, run_trigger,"
    " started_at, status) VALUES (:integration_id, :integration_type, :run_trigger, :now_ms,"
    " 'running')"
)

_RUN_COLUMNS = (
    "id, integration_id, integration_type, run_trigger, started_at, finished_at, status,"
    " added, updated, renamed, deleted, failed, skipped"
)

_GET_RUN_SQL = text(
    f"SELECT {_RUN_COLUMNS} FROM integration_sync_runs WHERE id = :id"  # noqa: S608 — stała
)

_LATEST_RUN_SQL = text(
    f"SELECT {_RUN_COLUMNS} FROM integration_sync_runs"  # noqa: S608 — stała
    " WHERE integration_id = :integration_id ORDER BY id DESC LIMIT 1"
)

_UPDATE_RUN_COUNTS_SQL = text(
    "UPDATE integration_sync_runs SET added = :added, updated = :updated, renamed = :renamed,"
    " deleted = :deleted, failed = :failed, skipped = :skipped WHERE id = :id"
)

_FINISH_RUN_SQL = text(
    "UPDATE integration_sync_runs SET status = :status, finished_at = :now_ms, added = :added,"
    " updated = :updated, renamed = :renamed, deleted = :deleted, failed = :failed,"
    " skipped = :skipped WHERE id = :id"
)

_RUNNING_RUN_IDS_SQL = text(
    "SELECT id FROM integration_sync_runs WHERE integration_id = :integration_id"
    " AND status = 'running' ORDER BY id"
)

_MARK_RUNNING_RUNS_SQL = text(
    "UPDATE integration_sync_runs SET status = :status, finished_at = :now_ms"
    " WHERE integration_id = :integration_id AND status = 'running'"
)

_INSERT_EVENT_SQL = text(
    "INSERT INTO integration_sync_events (run_id, integration_id, integration_type, level,"
    " message, file_path, container_id, container_name, created_at)"
    " VALUES (:run_id, :integration_id, :integration_type, :level, :message, :file_path,"
    " :container_id, :container_name, :created_at)"
)

_EVENT_COLUMNS = (
    "id, run_id, integration_id, integration_type, level, message, file_path, container_id,"
    " container_name, created_at"
)

_LIST_EVENTS_SQL = text(
    f"SELECT {_EVENT_COLUMNS} FROM integration_sync_events WHERE run_id = :run_id"  # noqa: S608
    " ORDER BY id"
)

_PURGE_EVENTS_SQL = text("DELETE FROM integration_sync_events WHERE created_at < :before_ms")


async def insert_run(
    session: AsyncSession,
    *,
    integration_id: int,
    integration_type: str,
    run_trigger: str,
    now_ms: int,
) -> int:
    """Wstawia przebieg w stanie ``running``; zwraca ``id`` (kontrakt C2)."""
    result = await session.execute(
        _INSERT_RUN_SQL,
        {
            "integration_id": integration_id,
            "integration_type": integration_type,
            "run_trigger": run_trigger,
            "now_ms": now_ms,
        },
    )
    return int(cast("CursorResult[Any]", result).lastrowid)


async def get_run(session: AsyncSession, run_id: int) -> RunRow | None:
    """Przebieg po ``id``; ``None`` gdy brak (kontrakt C2)."""
    row = (await session.execute(_GET_RUN_SQL, {"id": run_id})).mappings().first()
    return None if row is None else _run_row(row)


async def latest_run(session: AsyncSession, integration_id: int) -> RunRow | None:
    """Najnowszy przebieg integracji (najwyższe ``id``); ``None`` gdy brak (kontrakt C2)."""
    row = (
        (await session.execute(_LATEST_RUN_SQL, {"integration_id": integration_id}))
        .mappings()
        .first()
    )
    return None if row is None else _run_row(row)


async def update_run_counts(session: AsyncSession, run_id: int, counts: SyncCounts) -> None:
    """Ustawia 6 liczników przebiegu (nie dodaje) (kontrakt C2)."""
    await session.execute(
        _UPDATE_RUN_COUNTS_SQL,
        {
            "id": run_id,
            "added": counts.added,
            "updated": counts.updated,
            "renamed": counts.renamed,
            "deleted": counts.deleted,
            "failed": counts.failed,
            "skipped": counts.skipped,
        },
    )


async def finish_run(
    session: AsyncSession, run_id: int, *, status: str, counts: SyncCounts, now_ms: int
) -> None:
    """Kończy przebieg: ``status`` + ``finished_at`` + liczniki (kontrakt C2)."""
    await session.execute(
        _FINISH_RUN_SQL,
        {
            "id": run_id,
            "status": status,
            "now_ms": now_ms,
            "added": counts.added,
            "updated": counts.updated,
            "renamed": counts.renamed,
            "deleted": counts.deleted,
            "failed": counts.failed,
            "skipped": counts.skipped,
        },
    )


async def running_run_ids(session: AsyncSession, integration_id: int) -> list[int]:
    """Id przebiegów w stanie ``running``, po ``id`` (kontrakt C2)."""
    result = await session.execute(_RUNNING_RUN_IDS_SQL, {"integration_id": integration_id})
    return [int(value) for value in result.scalars().all()]


async def mark_running_runs(
    session: AsyncSession, integration_id: int, *, status: str, now_ms: int
) -> int:
    """Zamyka wszystkie przebiegi ``running`` integracji; zwraca ``rowcount`` (kontrakt C2)."""
    result = await session.execute(
        _MARK_RUNNING_RUNS_SQL,
        {"integration_id": integration_id, "status": status, "now_ms": now_ms},
    )
    return _rowcount(result)


async def insert_events(session: AsyncSession, events: Sequence[NewEvent]) -> None:
    """Zapisuje zdarzenia jednym ``executemany``; pusta lista → no-op (kontrakt C2)."""
    if not events:
        return
    await session.execute(
        _INSERT_EVENT_SQL,
        [
            {
                "run_id": event.run_id,
                "integration_id": event.integration_id,
                "integration_type": event.integration_type,
                "level": event.level,
                "message": event.message,
                "file_path": event.file_path,
                "container_id": event.container_id,
                "container_name": event.container_name,
                "created_at": event.created_at,
            }
            for event in events
        ],
    )


async def list_events(session: AsyncSession, run_id: int) -> list[EventRow]:
    """Zdarzenia przebiegu po ``id`` (kontrakt C2)."""
    rows = (await session.execute(_LIST_EVENTS_SQL, {"run_id": run_id})).mappings().all()
    return [_event_row(row) for row in rows]


async def purge_events_before(session: AsyncSession, *, before_ms: int) -> int:
    """Usuwa zdarzenia starsze niż ``before_ms``; zwraca ``rowcount`` (kontrakt C2)."""
    result = await session.execute(_PURGE_EVENTS_SQL, {"before_ms": before_ms})
    return _rowcount(result)
