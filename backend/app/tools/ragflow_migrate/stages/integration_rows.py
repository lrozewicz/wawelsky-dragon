"""Czyste mapowanie wierszy ``ai_hub_*`` na wiersze tabel integracji WD (kontrakt §8, §9).

Wydzielone z ``stages/integrations.py`` (limit rozmiaru pliku, kontrakt C2) — bez I/O i bez SQL.
"""

import json
from collections.abc import Mapping
from typing import Any

from app.integrations.secrets import encrypt_secret
from app.tools.ragflow_migrate.stages.base import Issue
from app.tools.ragflow_migrate.stages.common import datetime_ms

#: Wiersz tabeli (źródłowej albo celu) jako słownik kolumn.
Row = dict[str, Any]

#: Minimalny ``scan_interval_seconds`` w celu (CHECK w DDL; kontrakt §8).
MIN_SCAN_INTERVAL = 30

#: Statusy biegu akceptowane przez ENUM celu; ``running`` domykamy jako ``failed`` (kontrakt §8).
RUN_STATUSES = frozenset({"success", "partial", "failed", "cancelled"})

#: Status sekretu integracji zapisywany w kolumnie ``integrations.type``.
INTEGRATION_TYPE = "sharepoint"

#: Dopuszczalne ``last_sync_status`` celu; inne wartości → NULL (kontrakt §8).
LAST_SYNC_STATUSES = frozenset({"success", "partial", "failed", "cancelled"})

#: Poziomy zdarzeń: ``warning`` → ``warn``, ``info``/``error`` bez zmian, inne → ``info``.
EVENT_LEVELS = {"warning": "warn", "info": "info", "error": "error"}

#: Limity długości kolumn tekstowych celu (DDL: ``message``/``last_error``).
MESSAGE_LIMIT = 2000


def flag(value: Any) -> int:
    """Wartość źródłowa → 0/1 dla kolumny BOOLEAN/TINYINT(1)."""
    return 1 if value else 0


def json_text(value: Any) -> str | None:
    """Kolumna JSON źródła (tekst albo obiekt) → tekst JSON; NULL zostaje NULL-em."""
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def truncate(value: Any, limit: int) -> str | None:
    """Tekst skrócony do ``limit`` znaków; NULL zostaje NULL-em."""
    return None if value is None else str(value)[:limit]


def integration_row(
    row: Mapping[str, Any], plaintext: str, owner_id: str, wd_key: str
) -> tuple[Row, list[Issue]]:
    """Wiersz ``ai_hub_sharepoint_integrations`` → kolumny ``integrations`` (kontrakt §8)."""
    integration_id = int(row["id"])
    scan_source = int(row["scan_interval_seconds"])
    scan_interval = max(MIN_SCAN_INTERVAL, scan_source)
    issues: list[Issue] = []
    if scan_interval != scan_source:
        issues.append(
            Issue(
                severity="warning",
                code="scan_interval_clamped",
                message=f"scan_interval_seconds podniesione z {scan_source} do {scan_interval}",
                ids=[str(integration_id)],
            )
        )
    created_at = datetime_ms(row["created_at"])
    secret_enc, secret_last4 = encrypt_secret(wd_key, integration_id, plaintext)
    last_sync_status = str(row["last_sync_status"]) if row["last_sync_status"] else None
    return {
        "id": integration_id,
        "type": INTEGRATION_TYPE,
        "name": str(row["name"]),
        "dataset_id": str(row["dataset_id"]),
        "owner_id": owner_id,
        "config": "{}",
        "secret_enc": secret_enc,
        "secret_last4": secret_last4,
        "max_file_size_bytes": int(row["max_file_size_bytes"]),
        "ignored_extensions": json_text(row["ignored_extensions"]),
        "scan_interval_seconds": scan_interval,
        "delete_propagation": flag(row["delete_propagation"]),
        "is_active": flag(row["is_active"]),
        "is_running": 0,
        "lock_acquired_at": None,
        "lock_owner": None,
        "cancel_requested": 0,
        "last_sync_at": datetime_ms(row["last_sync_at"]),
        "last_sync_status": (last_sync_status if last_sync_status in LAST_SYNC_STATUSES else None),
        "created_at": created_at,
        "updated_at": datetime_ms(row["updated_at"]) or created_at,
    }, issues


def sharepoint_row(row: Mapping[str, Any]) -> Row:
    """Wiersz źródła → kolumny ``integration_sharepoint`` (kontrakt §8)."""
    return {
        "integration_id": int(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "client_id": str(row["client_id"]),
        "site_url": str(row["site_url"]),
        "site_id": row["site_id"],
        "site_display_name": None,
        "excluded_library_names": json_text(row["excluded_library_names"]),
    }


def container_row(row: Mapping[str, Any]) -> Row:
    """``ai_hub_sharepoint_integration_drives`` → ``integration_containers`` (kontrakt §8)."""
    return {
        "integration_id": int(row["integration_id"]),
        "container_id": str(row["drive_id"]),
        "name": str(row["drive_name"]),
        "delta_cursor": row["delta_link"],
        "last_sync_at": datetime_ms(row["last_sync_at"]),
        "discovered_at": datetime_ms(row["discovered_at"]),
    }


def run_row(row: Mapping[str, Any]) -> tuple[Row, list[Issue]]:
    """``ai_hub_integration_sync_runs`` → ``integration_sync_runs`` (kontrakt §8)."""
    run_id = int(row["id"])
    started_at = datetime_ms(row["started_at"])
    finished_at = datetime_ms(row["finished_at"])
    status = str(row["status"])
    issues: list[Issue] = []
    if status == "running":
        status = "failed"
        finished_at = started_at
        issues.append(
            Issue(
                severity="info",
                code="run_running_closed",
                message="bieg źródłowy w stanie `running` zamknięty jako `failed`",
                ids=[str(run_id)],
            )
        )
    elif status not in RUN_STATUSES:
        status = "failed"
    return {
        "id": run_id,
        "integration_id": int(row["integration_id"]),
        "integration_type": str(row["integration_type"]),
        "run_trigger": "schedule",
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "added": int(row["added"]),
        "updated": int(row["updated"]),
        "renamed": 0,
        "deleted": int(row["deleted"]),
        "failed": int(row["failed"]),
        "skipped": 0,
    }, issues


def event_row(row: Mapping[str, Any]) -> Row:
    """``ai_hub_integration_sync_events`` → ``integration_sync_events`` (kontrakt §8)."""
    return {
        "id": int(row["id"]),
        "run_id": int(row["run_id"]),
        "integration_id": int(row["integration_id"]),
        "integration_type": str(row["integration_type"]),
        "level": EVENT_LEVELS.get(str(row["level"]), "info"),
        "message": truncate(row["message"], MESSAGE_LIMIT),
        "file_path": row["file_path"],
        "container_id": row["drive_id"],
        "container_name": row["drive_name"],
        "created_at": datetime_ms(row["created_at"]),
    }


def mapping_row(row: Mapping[str, Any], known_documents: set[str]) -> tuple[Row, list[Issue]]:
    """``ai_hub_integration_file_mappings`` → ``integration_item_mappings`` (kontrakt §8)."""
    document_id = str(row["ragflow_document_id"])
    issues: list[Issue] = []
    if document_id not in known_documents:
        issues.append(
            Issue(
                severity="warning",
                code="mapping_document_missing",
                message=f"dokument {document_id} nie istnieje jeszcze w tabeli documents celu",
                ids=[document_id],
            )
        )
    return {
        "integration_id": int(row["integration_id"]),
        "container_id": str(row["drive_id"]),
        "item_id": str(row["external_item_id"]),
        "document_id": document_id if document_id in known_documents else None,
        "content_tag": row["external_etag"],
        "meta_tag": None,
        "name": None,
        "path": None,
        "web_url": None,
        "last_status": "ok" if str(row["last_status"]) == "done" else "failed",
        "last_error": truncate(row["last_error"], MESSAGE_LIMIT),
        "updated_at": datetime_ms(row["updated_at"]),
    }, issues
