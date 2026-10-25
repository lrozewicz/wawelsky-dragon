"""Funkcje administracyjne repozytorium integracji — SQL wg kontraktu WP E4-3a §1.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.integrations.rows import (
    EventRow,
    IntegrationRow,
    MappingRow,
    RunRow,
    _event_row,
    _integration_row,
    _mapping_row,
    _rowcount,
    _run_row,
)

_INTEGRATION_COLUMNS = (
    "id, type, name, dataset_id, owner_id, config, secret_enc, secret_last4,"
    " max_file_size_bytes, ignored_extensions, scan_interval_seconds, delete_propagation,"
    " is_active, is_running, lock_acquired_at, lock_owner, cancel_requested, last_sync_at,"
    " last_sync_status, created_at, updated_at"
)

_LIST_INTEGRATIONS_SQL = text(
    f"SELECT {_INTEGRATION_COLUMNS} FROM integrations ORDER BY id DESC"  # noqa: S608 — stała
)

_FIND_BY_DATASET_SQL = text(
    f"SELECT {_INTEGRATION_COLUMNS} FROM integrations"  # noqa: S608 — stała
    " WHERE dataset_id = :dataset_id LIMIT 1"
)

_UPDATE_INTEGRATION_SQL = text(
    "UPDATE integrations SET name = :name, dataset_id = :dataset_id,"
    " max_file_size_bytes = :max_file_size_bytes, ignored_extensions = :ignored_extensions,"
    " scan_interval_seconds = :scan_interval_seconds, delete_propagation = :delete_propagation,"
    " is_active = :is_active, updated_at = :now_ms WHERE id = :id"
)

_DELETE_MAPPINGS_SQL = text(
    "DELETE FROM integration_item_mappings WHERE integration_id = :integration_id"
)

_DELETE_CONTAINERS_SQL = text(
    "DELETE FROM integration_containers WHERE integration_id = :integration_id"
)

_DELETE_SHAREPOINT_SQL = text(
    "DELETE FROM integration_sharepoint WHERE integration_id = :integration_id"
)

_DELETE_INTEGRATION_SQL = text("DELETE FROM integrations WHERE id = :id")

_RUN_COLUMNS = (
    "id, integration_id, integration_type, run_trigger, started_at, finished_at, status,"
    " added, updated, renamed, deleted, failed, skipped"
)

_RUNS_SELECT = f"SELECT {_RUN_COLUMNS} FROM integration_sync_runs"  # noqa: S608 — stała
_RUNS_SUFFIX = " ORDER BY id DESC LIMIT :limit"

_EVENT_COLUMNS = (
    "id, run_id, integration_id, integration_type, level, message, file_path, container_id,"
    " container_name, created_at"
)

_EVENTS_SELECT = f"SELECT {_EVENT_COLUMNS} FROM integration_sync_events"  # noqa: S608 — stała
_EVENTS_SUFFIX = " ORDER BY id ASC LIMIT :limit"

_FIND_MAPPING_BY_DOCUMENT_SQL = text(
    "SELECT integration_id, container_id, item_id, document_id, content_tag, meta_tag, name,"
    " path, web_url, last_status, last_error, updated_at FROM integration_item_mappings"
    " WHERE document_id = :document_id LIMIT 1"
)

_MAPPING_DOCUMENT_IDS_SQL = text(
    "SELECT document_id FROM integration_item_mappings"
    " WHERE integration_id = :integration_id AND document_id IS NOT NULL AND document_id <> ''"
)

_UPDATE_MAPPING_LINK_SQL = text(
    "UPDATE integration_item_mappings SET name = :name, path = :path, web_url = :web_url,"
    " updated_at = :now_ms WHERE integration_id = :integration_id"
    " AND container_id = :container_id AND item_id = :item_id"
)

_LIST_DATASET_SUMMARIES_SQL = text(
    "SELECT id, name, document_count, chunk_count, embedding_model FROM datasets ORDER BY name, id"
)


@dataclass(frozen=True)
class DatasetSummary:
    """Skrót datasetu dla trasy ``GET /api/datasets`` (kontrakt E4-3a §1)."""

    id: str
    name: str
    document_count: int
    chunk_count: int
    embedding_model: str


async def list_integrations(session: AsyncSession) -> list[IntegrationRow]:
    """Wszystkie integracje, malejąco po ``id`` (kontrakt E4-3a §1)."""
    rows = (await session.execute(_LIST_INTEGRATIONS_SQL)).mappings().all()
    return [_integration_row(row) for row in rows]


async def find_by_dataset(session: AsyncSession, dataset_id: str) -> IntegrationRow | None:
    """Integracja przypięta do datasetu; ``None`` gdy brak (kontrakt E4-3a §1)."""
    row = (
        (await session.execute(_FIND_BY_DATASET_SQL, {"dataset_id": dataset_id})).mappings().first()
    )
    return None if row is None else _integration_row(row)


async def update_integration(  # noqa: PLR0913 — kształt kontraktu E4-3a §1
    session: AsyncSession,
    integration_id: int,
    *,
    name: str,
    dataset_id: str,
    max_file_size_bytes: int,
    ignored_extensions: list[str],
    scan_interval_seconds: int,
    delete_propagation: bool,
    is_active: bool,
    now_ms: int,
) -> bool:
    """Nadpisuje pola edytowalne (bez sekretu); ``rowcount == 1`` (kontrakt E4-3a §1)."""
    result = await session.execute(
        _UPDATE_INTEGRATION_SQL,
        {
            "id": integration_id,
            "name": name,
            "dataset_id": dataset_id,
            "max_file_size_bytes": max_file_size_bytes,
            "ignored_extensions": json.dumps(ignored_extensions, ensure_ascii=False),
            "scan_interval_seconds": scan_interval_seconds,
            "delete_propagation": delete_propagation,
            "is_active": is_active,
            "now_ms": now_ms,
        },
    )
    return _rowcount(result) == 1


async def delete_integration(session: AsyncSession, integration_id: int) -> bool:
    """Usuwa integrację i jej dane zależne; ``runs``/``events`` zostają (kontrakt E4-3a §1).

    Kolejność kasowania: mapowania, kontenery, wiersz SharePoint, wiersz integracji.
    Zwraca ``True`` tylko wtedy, gdy usunięto wiersz ``integrations``.
    """
    await session.execute(_DELETE_MAPPINGS_SQL, {"integration_id": integration_id})
    await session.execute(_DELETE_CONTAINERS_SQL, {"integration_id": integration_id})
    await session.execute(_DELETE_SHAREPOINT_SQL, {"integration_id": integration_id})
    result = await session.execute(_DELETE_INTEGRATION_SQL, {"id": integration_id})
    return _rowcount(result) == 1


async def list_runs(
    session: AsyncSession,
    *,
    integration_type: str | None,
    integration_id: int | None,
    limit: int,
    before_id: int | None = None,
) -> list[RunRow]:
    """Przebiegi malejąco po ``id``, z opcjonalnymi filtrami (kontrakt E4-3a §1, E4-3b §3)."""
    conditions: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if integration_type is not None:
        conditions.append("integration_type = :integration_type")
        params["integration_type"] = integration_type
    if integration_id is not None:
        conditions.append("integration_id = :integration_id")
        params["integration_id"] = integration_id
    if before_id is not None:
        conditions.append("id < :before_id")
        params["before_id"] = before_id
    where = "" if not conditions else " WHERE " + " AND ".join(conditions)
    statement = text(_RUNS_SELECT + where + _RUNS_SUFFIX)
    rows = (await session.execute(statement, params)).mappings().all()
    return [_run_row(row) for row in rows]


async def list_events_page(
    session: AsyncSession,
    run_id: int,
    *,
    after_id: int,
    level: str | None,
    limit: int,
) -> list[EventRow]:
    """Zdarzenia przebiegu ``id > after_id``, rosnąco, opcjonalnie po ``level`` (E4-3a §1)."""
    conditions = ["run_id = :run_id", "id > :after_id"]
    params: dict[str, Any] = {"run_id": run_id, "after_id": after_id, "limit": limit}
    if level is not None:
        conditions.append("level = :level")
        params["level"] = level
    statement = text(_EVENTS_SELECT + " WHERE " + " AND ".join(conditions) + _EVENTS_SUFFIX)
    rows = (await session.execute(statement, params)).mappings().all()
    return [_event_row(row) for row in rows]


async def find_mapping_by_document(session: AsyncSession, document_id: str) -> MappingRow | None:
    """Mapowanie po ``document_id`` (pierwsze); ``None`` gdy brak (kontrakt E4-3a §1)."""
    row = (
        (await session.execute(_FIND_MAPPING_BY_DOCUMENT_SQL, {"document_id": document_id}))
        .mappings()
        .first()
    )
    return None if row is None else _mapping_row(row)


async def mapping_document_ids(session: AsyncSession, integration_id: int) -> list[str]:
    """Niepuste ``document_id`` mapowań integracji (kontrakt E4-3a §1)."""
    result = await session.execute(_MAPPING_DOCUMENT_IDS_SQL, {"integration_id": integration_id})
    return [str(value) for value in result.scalars().all()]


async def update_mapping_link(  # noqa: PLR0913 — kształt kontraktu E4-3a §1
    session: AsyncSession,
    integration_id: int,
    container_id: str,
    item_id: str,
    *,
    name: str | None,
    path: str | None,
    web_url: str | None,
    now_ms: int,
) -> None:
    """Odświeża ``name``/``path``/``web_url`` i ``updated_at`` mapowania (E4-3a §1)."""
    await session.execute(
        _UPDATE_MAPPING_LINK_SQL,
        {
            "integration_id": integration_id,
            "container_id": container_id,
            "item_id": item_id,
            "name": name,
            "path": path,
            "web_url": web_url,
            "now_ms": now_ms,
        },
    )


async def list_dataset_summaries(session: AsyncSession) -> list[DatasetSummary]:
    """Wszystkie datasety, rosnąco po ``name`` i ``id`` (kontrakt E4-3a §1)."""
    rows = (await session.execute(_LIST_DATASET_SUMMARIES_SQL)).mappings().all()
    return [
        DatasetSummary(
            id=row["id"],
            name=row["name"],
            document_count=int(row["document_count"]),
            chunk_count=int(row["chunk_count"]),
            embedding_model=row["embedding_model"],
        )
        for row in rows
    ]
