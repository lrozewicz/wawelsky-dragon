"""Repozytorium worker_heartbeat — tętno procesu workera (K5 §2.6, kontrakt C10).

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class WorkerHeartbeatRow:
    """Wiersz ``worker_heartbeat``; ``capabilities`` po ``json.loads`` (K5 §2.6)."""

    worker_id: str
    started_at: int
    heartbeat_at: int
    capabilities: dict[str, Any]
    version: str


def _row(row: RowMapping) -> WorkerHeartbeatRow:
    """RowMapping → WorkerHeartbeatRow."""
    return WorkerHeartbeatRow(
        worker_id=row["worker_id"],
        started_at=row["started_at"],
        heartbeat_at=row["heartbeat_at"],
        capabilities=json.loads(row["capabilities"]),
        version=row["version"],
    )


async def list_all(session: AsyncSession) -> list[WorkerHeartbeatRow]:
    """Tętna wszystkich workerów po ``worker_id`` — treść /system/status (brief SYS p. 2)."""
    result = await session.execute(
        text(
            "SELECT worker_id, started_at, heartbeat_at, capabilities, version"
            " FROM worker_heartbeat ORDER BY worker_id"
        )
    )
    return [_row(row) for row in result.mappings().all()]


# started_at bez zmian przy UPDATE — czas startu procesu ma zostać (kontrakt C10).
_UPSERT_SQL = text(
    "INSERT INTO worker_heartbeat (worker_id, started_at, heartbeat_at, capabilities, version)"
    " VALUES (:worker_id, :started_at, :heartbeat_at, :capabilities, :version)"
    " ON DUPLICATE KEY UPDATE heartbeat_at = :heartbeat_at, capabilities = :capabilities,"
    " version = :version"
)

# Host = pierwsza część worker_id ("host:pid[:slot]"); indeks ix_worker_heartbeat_heartbeat_at.
_HAS_RECENT_SQL = text(
    "SELECT EXISTS(SELECT 1 FROM worker_heartbeat"
    " WHERE SUBSTRING_INDEX(worker_id, ':', 1) = :host AND heartbeat_at >= :since_ms)"
)


async def upsert(  # noqa: PLR0913 — kształt kontraktu C10
    session: AsyncSession,
    *,
    worker_id: str,
    started_at: int,
    heartbeat_at: int,
    capabilities: Mapping[str, Any],
    version: str,
) -> None:
    """Wstawia lub odświeża tętno workera; capabilities jako JSON (kontrakt C10)."""
    await session.execute(
        _UPSERT_SQL,
        {
            "worker_id": worker_id,
            "started_at": started_at,
            "heartbeat_at": heartbeat_at,
            "capabilities": json.dumps(dict(capabilities)),
            "version": version,
        },
    )


async def has_recent(session: AsyncSession, *, host: str, since_ms: int) -> bool:
    """True, gdy żyje jakiś worker na podanym hoście z tętnem nie starszym niż since_ms."""
    result = await session.execute(_HAS_RECENT_SQL, {"host": host, "since_ms": since_ms})
    return bool(result.scalar_one())
