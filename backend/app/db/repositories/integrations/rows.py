"""Wiersze integracji i mapowanie ``RowMapping`` → dataclass (kontrakt E4-1 C1).

Wspólne helpery SQL (``_rowcount``, ``_json_value``) dla podmodułów pakietu.
Kolumny JSON czytane tolerancyjnie (``str`` → ``json.loads``, ``dict``/``list`` → jak jest —
sterownik zwraca oba); ``BOOLEAN`` → ``bool``.
"""

import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.engine import CursorResult, RowMapping


@dataclass(frozen=True)
class IntegrationRow:
    """Wiersz ``integrations`` (kontrakt C1)."""

    id: int
    type: str
    name: str
    dataset_id: str
    owner_id: str
    config: dict[str, object]
    secret_enc: str | None
    secret_last4: str | None
    max_file_size_bytes: int
    ignored_extensions: list[str]
    scan_interval_seconds: int
    delete_propagation: bool
    is_active: bool
    is_running: bool
    lock_acquired_at: int | None
    lock_owner: str | None
    cancel_requested: bool
    last_sync_at: int | None
    last_sync_status: str | None
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class ContainerRow:
    """Wiersz ``integration_containers`` (kontrakt C1)."""

    integration_id: int
    container_id: str
    name: str
    delta_cursor: str | None
    last_sync_at: int | None
    discovered_at: int


@dataclass(frozen=True)
class MappingRow:
    """Wiersz ``integration_item_mappings`` (kontrakt C1)."""

    integration_id: int
    container_id: str
    item_id: str
    document_id: str | None
    content_tag: str | None
    meta_tag: str | None
    name: str | None
    path: str | None
    web_url: str | None
    last_status: str
    last_error: str | None
    updated_at: int


@dataclass(frozen=True)
class RunRow:
    """Wiersz ``integration_sync_runs`` (kontrakt C1)."""

    id: int
    integration_id: int
    integration_type: str
    run_trigger: str
    started_at: int
    finished_at: int | None
    status: str
    added: int
    updated: int
    renamed: int
    deleted: int
    failed: int
    skipped: int


@dataclass(frozen=True)
class NewEvent:
    """Zdarzenie do zapisu (kontrakt C1) — bez ``id``."""

    run_id: int
    integration_id: int
    integration_type: str
    level: str
    message: str
    file_path: str | None
    container_id: str | None
    container_name: str | None
    created_at: int


@dataclass(frozen=True)
class EventRow:
    """Wiersz ``integration_sync_events`` (kontrakt C1) — ``NewEvent`` + ``id``."""

    id: int
    run_id: int
    integration_id: int
    integration_type: str
    level: str
    message: str
    file_path: str | None
    container_id: str | None
    container_name: str | None
    created_at: int


def _rowcount(result: object) -> int:
    """Liczba dotkniętych wierszy UPDATE/DELETE (``rowcount`` z ``CursorResult``)."""
    return cast("CursorResult[Any]", result).rowcount


def _json_value(value: object) -> Any:
    """Wartość kolumny JSON: ``str`` → ``json.loads``, ``dict``/``list`` → jak jest."""
    return json.loads(value) if isinstance(value, str) else value


def _integration_row(row: RowMapping) -> IntegrationRow:
    """RowMapping → IntegrationRow (JSON tolerancyjnie, BOOLEAN → bool)."""
    return IntegrationRow(
        id=int(row["id"]),
        type=row["type"],
        name=row["name"],
        dataset_id=row["dataset_id"],
        owner_id=row["owner_id"],
        config=_json_value(row["config"]),
        secret_enc=row["secret_enc"],
        secret_last4=row["secret_last4"],
        max_file_size_bytes=int(row["max_file_size_bytes"]),
        ignored_extensions=list(_json_value(row["ignored_extensions"])),
        scan_interval_seconds=int(row["scan_interval_seconds"]),
        delete_propagation=bool(row["delete_propagation"]),
        is_active=bool(row["is_active"]),
        is_running=bool(row["is_running"]),
        lock_acquired_at=row["lock_acquired_at"],
        lock_owner=row["lock_owner"],
        cancel_requested=bool(row["cancel_requested"]),
        last_sync_at=row["last_sync_at"],
        last_sync_status=row["last_sync_status"],
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
    )


def _container_row(row: RowMapping) -> ContainerRow:
    """RowMapping → ContainerRow."""
    return ContainerRow(
        integration_id=int(row["integration_id"]),
        container_id=row["container_id"],
        name=row["name"],
        delta_cursor=row["delta_cursor"],
        last_sync_at=row["last_sync_at"],
        discovered_at=int(row["discovered_at"]),
    )


def _mapping_row(row: RowMapping) -> MappingRow:
    """RowMapping → MappingRow."""
    return MappingRow(
        integration_id=int(row["integration_id"]),
        container_id=row["container_id"],
        item_id=row["item_id"],
        document_id=row["document_id"],
        content_tag=row["content_tag"],
        meta_tag=row["meta_tag"],
        name=row["name"],
        path=row["path"],
        web_url=row["web_url"],
        last_status=row["last_status"],
        last_error=row["last_error"],
        updated_at=int(row["updated_at"]),
    )


def _run_row(row: RowMapping) -> RunRow:
    """RowMapping → RunRow."""
    return RunRow(
        id=int(row["id"]),
        integration_id=int(row["integration_id"]),
        integration_type=row["integration_type"],
        run_trigger=row["run_trigger"],
        started_at=int(row["started_at"]),
        finished_at=row["finished_at"],
        status=row["status"],
        added=int(row["added"]),
        updated=int(row["updated"]),
        renamed=int(row["renamed"]),
        deleted=int(row["deleted"]),
        failed=int(row["failed"]),
        skipped=int(row["skipped"]),
    )


def _event_row(row: RowMapping) -> EventRow:
    """RowMapping → EventRow."""
    return EventRow(
        id=int(row["id"]),
        run_id=int(row["run_id"]),
        integration_id=int(row["integration_id"]),
        integration_type=row["integration_type"],
        level=row["level"],
        message=row["message"],
        file_path=row["file_path"],
        container_id=row["container_id"],
        container_name=row["container_name"],
        created_at=int(row["created_at"]),
    )
