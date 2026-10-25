"""Integracje i locki — SQL wg kontraktu E4-1 C2 (część pakietu ``integrations``).

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

import json
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.integrations.rows import (
    IntegrationRow,
    _integration_row,
    _rowcount,
)

_INSERT_INTEGRATION_SQL = text(
    "INSERT INTO integrations (type, name, dataset_id, owner_id, config, ignored_extensions,"
    " max_file_size_bytes, scan_interval_seconds, delete_propagation, is_active,"
    " created_at, updated_at)"
    " VALUES (:type, :name, :dataset_id, :owner_id, :config, :ignored_extensions,"
    " :max_file_size_bytes, :scan_interval_seconds, :delete_propagation, :is_active,"
    " :now_ms, :now_ms)"
)

_INTEGRATION_COLUMNS = (
    "id, type, name, dataset_id, owner_id, config, secret_enc, secret_last4,"
    " max_file_size_bytes, ignored_extensions, scan_interval_seconds, delete_propagation,"
    " is_active, is_running, lock_acquired_at, lock_owner, cancel_requested, last_sync_at,"
    " last_sync_status, created_at, updated_at"
)

_GET_INTEGRATION_SQL = text(
    f"SELECT {_INTEGRATION_COLUMNS} FROM integrations WHERE id = :id"  # noqa: S608 — stała
)

# 09 §5 „due”: aktywne, bez locka i po upływie interwału od ostatniej synchronizacji.
_LIST_DUE_SQL = text(
    "SELECT id FROM integrations"
    " WHERE is_active = 1 AND is_running = 0"
    " AND (last_sync_at IS NULL OR last_sync_at < :now_ms - scan_interval_seconds * 1000)"
    " ORDER BY id"
)

_TRY_LOCK_SQL = text(
    "UPDATE integrations SET is_running = 1, lock_acquired_at = :now_ms, lock_owner = :owner,"
    " cancel_requested = 0 WHERE id = :id AND is_running = 0"
)

_HEARTBEAT_LOCK_SQL = text(
    "UPDATE integrations SET lock_acquired_at = :now_ms"
    " WHERE id = :id AND lock_owner = :owner AND is_running = 1"
)

_RELEASE_LOCK_SQL = text(
    "UPDATE integrations SET is_running = 0, lock_owner = NULL, cancel_requested = 0,"
    " last_sync_at = :now_ms, last_sync_status = :status"
    " WHERE id = :id AND lock_owner = :owner AND is_running = 1"
)

_RECOVER_STALE_SELECT_SQL = text(
    "SELECT id FROM integrations WHERE is_running = 1 AND lock_acquired_at < :threshold FOR UPDATE"
)

_RECOVER_STALE_UPDATE_SQL = text(
    "UPDATE integrations SET is_running = 0, lock_owner = NULL WHERE id IN :ids AND is_running = 1"
).bindparams(bindparam("ids", expanding=True))

_REQUEST_CANCEL_SQL = text(
    "UPDATE integrations SET cancel_requested = 1 WHERE id = :id AND is_running = 1"
)

_IS_CANCEL_REQUESTED_SQL = text("SELECT cancel_requested FROM integrations WHERE id = :id")

_FORCE_UNLOCK_SQL = text(
    "UPDATE integrations SET is_running = 0, lock_owner = NULL, cancel_requested = 0"
    " WHERE id = :id AND is_running = 1"
)


async def insert_integration(  # noqa: PLR0913 — kształt kontraktu C2
    session: AsyncSession,
    *,
    type: str,
    name: str,
    dataset_id: str,
    owner_id: str,
    config: dict[str, object],
    now_ms: int,
    ignored_extensions: list[str] | None = None,
    max_file_size_bytes: int = 209_715_200,
    scan_interval_seconds: int = 300,
    delete_propagation: bool = True,
    is_active: bool = True,
) -> int:
    """Wstawia integrację (kontrakt C2); zwraca ``id``. ``ignored_extensions=None`` → ``[]``."""
    result = await session.execute(
        _INSERT_INTEGRATION_SQL,
        {
            "type": type,
            "name": name,
            "dataset_id": dataset_id,
            "owner_id": owner_id,
            "config": json.dumps(config, ensure_ascii=False),
            "ignored_extensions": json.dumps(
                ignored_extensions if ignored_extensions is not None else [], ensure_ascii=False
            ),
            "max_file_size_bytes": max_file_size_bytes,
            "scan_interval_seconds": scan_interval_seconds,
            "delete_propagation": delete_propagation,
            "is_active": is_active,
            "now_ms": now_ms,
        },
    )
    return int(cast("CursorResult[Any]", result).lastrowid)


async def get_integration(session: AsyncSession, integration_id: int) -> IntegrationRow | None:
    """Wiersz integracji po ``id``; ``None`` gdy brak (kontrakt C2)."""
    row = (await session.execute(_GET_INTEGRATION_SQL, {"id": integration_id})).mappings().first()
    return None if row is None else _integration_row(row)


async def list_due(session: AsyncSession, *, now_ms: int) -> list[int]:
    """Id integracji gotowych do przebiegu wg 09 §5, po ``id`` (kontrakt C2)."""
    result = await session.execute(_LIST_DUE_SQL, {"now_ms": now_ms})
    return [int(value) for value in result.scalars().all()]


async def try_lock(session: AsyncSession, integration_id: int, *, owner: str, now_ms: int) -> bool:
    """Zakłada lock, gdy wolny; zeruje ``cancel_requested``; ``rowcount == 1`` (kontrakt C2)."""
    result = await session.execute(
        _TRY_LOCK_SQL, {"id": integration_id, "owner": owner, "now_ms": now_ms}
    )
    return _rowcount(result) == 1


async def heartbeat_lock(
    session: AsyncSession, integration_id: int, *, owner: str, now_ms: int
) -> bool:
    """Odświeża ``lock_acquired_at`` tylko dla właściciela aktywnego locka (kontrakt C2)."""
    result = await session.execute(
        _HEARTBEAT_LOCK_SQL, {"id": integration_id, "owner": owner, "now_ms": now_ms}
    )
    return _rowcount(result) == 1


async def release_lock(
    session: AsyncSession, integration_id: int, *, owner: str, now_ms: int, status: str
) -> bool:
    """Zwalnia lock właściciela; zapisuje ``last_sync_at``/``last_sync_status`` (kontrakt C2)."""
    result = await session.execute(
        _RELEASE_LOCK_SQL,
        {"id": integration_id, "owner": owner, "now_ms": now_ms, "status": status},
    )
    return _rowcount(result) == 1


async def recover_stale(session: AsyncSession, *, now_ms: int, stale_ms: int) -> list[int]:
    """Zwalnia locki starsze niż ``stale_ms``; zwraca odzyskane ``id`` (kontrakt C2)."""
    threshold = now_ms - stale_ms
    ids = [
        int(value)
        for value in (await session.execute(_RECOVER_STALE_SELECT_SQL, {"threshold": threshold}))
        .scalars()
        .all()
    ]
    if not ids:
        return []
    await session.execute(_RECOVER_STALE_UPDATE_SQL, {"ids": ids})
    return ids


async def request_cancel(session: AsyncSession, integration_id: int) -> bool:
    """Żąda anulowania, gdy przebieg trwa; ``rowcount == 1`` (kontrakt C2)."""
    result = await session.execute(_REQUEST_CANCEL_SQL, {"id": integration_id})
    return _rowcount(result) == 1


async def is_cancel_requested(session: AsyncSession, integration_id: int) -> bool:
    """Czy trwa żądanie anulowania; brak wiersza → ``False`` (kontrakt C2)."""
    value = (await session.execute(_IS_CANCEL_REQUESTED_SQL, {"id": integration_id})).scalar()
    return bool(value)


async def force_unlock(session: AsyncSession, integration_id: int) -> bool:
    """Zdejmuje lock bez względu na właściciela; ``rowcount == 1`` (kontrakt C2)."""
    result = await session.execute(_FORCE_UNLOCK_SQL, {"id": integration_id})
    return _rowcount(result) == 1
