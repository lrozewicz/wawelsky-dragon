"""DTO powierzchni SVC integracji SharePoint (03 §5, kontrakt E4-3a §4).

Wiersze i widoki pochodzą z fasady ``app.services.integrations``, a nie z ``app.db``: kontrakt
import-lintera „API nie dotyka bazy bezpośrednio” obowiązuje także dla importów pod
``TYPE_CHECKING`` (re-eksport przez ``__all__`` fasady — DEC-075).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.integrations import (
    ContainerRow,
    EventRow,
    IntegrationView,
    RunRow,
    StatusView,
)

MASKED = "••••"  # cztery znaki U+2022 (kontrakt §4)
_MILLIS_PER_SECOND = 1000
_MICROS_PER_MILLI = 1000


def iso_ms(ms: int | None) -> str | None:
    """Milisekundy epoki → ISO 8601 UTC z milisekundami (`…Z`); `None` → `None` (kontrakt §4)."""
    if ms is None:
        return None
    moment = datetime.fromtimestamp(ms / _MILLIS_PER_SECOND, UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // _MICROS_PER_MILLI:03d}Z"


def integration_dto(view: IntegrationView) -> dict[str, object]:
    """Integracja z konfiguracją SharePoint; 19 kluczy kontraktu §4, sekret tylko jako maska."""
    row = view.row
    sharepoint = view.sharepoint
    return {
        "id": row.id,
        "name": row.name,
        "dataset_id": row.dataset_id,
        "tenant_id": sharepoint.tenant_id,
        "client_id": sharepoint.client_id,
        "client_secret_masked": _masked_secret(row.secret_last4),
        "site_url": sharepoint.site_url,
        "site_id": sharepoint.site_id,
        "excluded_library_names": sharepoint.excluded_library_names,
        "max_file_size_bytes": row.max_file_size_bytes,
        "ignored_extensions": row.ignored_extensions,
        "scan_interval_seconds": row.scan_interval_seconds,
        "delete_propagation": row.delete_propagation,
        "is_active": row.is_active,
        "is_running": row.is_running,
        "last_sync_at": iso_ms(row.last_sync_at),
        "last_sync_status": row.last_sync_status,
        "created_at": iso_ms(row.created_at),
        "updated_at": iso_ms(row.updated_at),
    }


def run_dto(run: RunRow) -> dict[str, object]:
    """Przebieg synchronizacji (kontrakt §4)."""
    return {
        "id": run.id,
        "integration_id": run.integration_id,
        "integration_type": run.integration_type,
        "started_at": iso_ms(run.started_at),
        "finished_at": iso_ms(run.finished_at),
        "status": run.status,
        "added": run.added,
        "updated": run.updated,
        "deleted": run.deleted,
        "failed": run.failed,
    }


def event_dto(event: EventRow) -> dict[str, object]:
    """Zdarzenie przebiegu; kontener jedzie jako `drive_id`/`drive_name` (kontrakt §4)."""
    return {
        "id": event.id,
        "run_id": event.run_id,
        "integration_id": event.integration_id,
        "integration_type": event.integration_type,
        "level": event.level,
        "message": event.message,
        "file_path": event.file_path,
        "drive_id": event.container_id,
        "drive_name": event.container_name,
        "created_at": iso_ms(event.created_at),
    }


def drive_dto(container: ContainerRow) -> dict[str, object]:
    """Kontener integracji; `has_delta` = zapisany kursor delty (kontrakt §4)."""
    return {
        "drive_id": container.container_id,
        "drive_name": container.name,
        "has_delta": container.delta_cursor is not None,
        "last_sync_at": iso_ms(container.last_sync_at),
        "discovered_at": iso_ms(container.discovered_at),
    }


def status_dto(view: StatusView) -> dict[str, object]:
    """Stan integracji + ostatni przebieg albo `null` (kontrakt §4)."""
    row = view.row
    return {
        "id": row.id,
        "is_active": row.is_active,
        "is_running": row.is_running,
        "last_sync_at": iso_ms(row.last_sync_at),
        "last_sync_status": row.last_sync_status,
        "latest_run": _latest_run(view.latest_run),
    }


def _masked_secret(secret_last4: str | None) -> str:
    """Maska sekretu: `••••` + ostatnie 4 znaki, gdy znane (kontrakt §4)."""
    return MASKED + secret_last4 if secret_last4 else MASKED


def _latest_run(run: RunRow | None) -> dict[str, object] | None:
    """Skrót ostatniego przebiegu w `status_dto` (kontrakt §4)."""
    if run is None:
        return None
    return {
        "id": run.id,
        "started_at": iso_ms(run.started_at),
        "finished_at": iso_ms(run.finished_at),
        "status": run.status,
        "added": run.added,
        "updated": run.updated,
        "deleted": run.deleted,
        "failed": run.failed,
    }
