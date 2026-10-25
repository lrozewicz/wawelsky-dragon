"""DTO powierzchni SVC integracji SharePoint (brief T4 p. 10a, kontrakt E4-3a §4)."""

from datetime import UTC, datetime

from app.api.hub_compat.sharepoint.dto import (
    drive_dto,
    event_dto,
    integration_dto,
    iso_ms,
    status_dto,
)
from app.db.repositories.integrations import (
    ContainerRow,
    EventRow,
    IntegrationRow,
    RunRow,
    SharePointRow,
)
from app.services.integration_ops import IntegrationView, StatusView

_MOMENT_MS = 1790157600123
_MOMENT_ISO = "2026-09-23T10:00:00.123Z"
_LATER_ISO = "2026-09-23T10:00:05.123Z"

INTEGRATION_KEYS = {
    "id",
    "name",
    "dataset_id",
    "tenant_id",
    "client_id",
    "client_secret_masked",
    "site_url",
    "site_id",
    "excluded_library_names",
    "max_file_size_bytes",
    "ignored_extensions",
    "scan_interval_seconds",
    "delete_propagation",
    "is_active",
    "is_running",
    "last_sync_at",
    "last_sync_status",
    "created_at",
    "updated_at",
}


def _row(secret_last4: str | None) -> IntegrationRow:
    """Wiersz integracji do DTO; znaczenie ma tylko maska sekretu i znaczniki czasu."""
    return IntegrationRow(
        id=7,
        type="sharepoint",
        name="Docs",
        dataset_id="ds-1",
        owner_id="owner-1",
        config={},
        secret_enc="enc",  # noqa: S106 — atrapa szyfrogramu, nie sekret
        secret_last4=secret_last4,
        max_file_size_bytes=1024,
        ignored_extensions=["exe"],
        scan_interval_seconds=300,
        delete_propagation=False,
        is_active=True,
        is_running=False,
        lock_acquired_at=None,
        lock_owner=None,
        cancel_requested=False,
        last_sync_at=None,
        last_sync_status=None,
        created_at=_MOMENT_MS,
        updated_at=_MOMENT_MS,
    )


def _view(secret_last4: str | None) -> IntegrationView:
    """Widok integracji z konfiguracją SharePoint."""
    return IntegrationView(
        row=_row(secret_last4),
        sharepoint=SharePointRow(
            integration_id=7,
            tenant_id="tenant-1",
            client_id="client-1",
            site_url="https://contoso.sharepoint.com/sites/eng",
            site_id="site-1",
            site_display_name="Eng",
            excluded_library_names=["Site Assets"],
        ),
    )


def _run() -> RunRow:
    """Wiersz przebiegu do DTO."""
    return RunRow(
        id=3,
        integration_id=7,
        integration_type="sharepoint",
        run_trigger="manual",
        started_at=_MOMENT_MS,
        finished_at=_MOMENT_MS + 5000,
        status="ok",
        added=1,
        updated=2,
        renamed=0,
        deleted=3,
        failed=0,
        skipped=4,
    )


def test_iso_ms_formats_utc_milliseconds() -> None:
    """`iso_ms` → ISO 8601 UTC z milisekundami; wartość policzona z `datetime` (brief p. 10a)."""
    moment = datetime.fromtimestamp(_MOMENT_MS / 1000, UTC)
    expected = moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
    assert expected == _MOMENT_ISO  # wartość dosłowna, niezależna od implementacji
    assert iso_ms(_MOMENT_MS) == expected


def test_iso_ms_none() -> None:
    """Brak znacznika czasu → `None` (nie pusty string)."""
    assert iso_ms(None) is None


def test_integration_dto_keys() -> None:
    """Zbiór kluczy `integration_dto` == lista 19 kluczy z kontraktu §4."""
    assert set(integration_dto(_view("abcd"))) == INTEGRATION_KEYS


def test_client_secret_masked() -> None:
    """Maska sekretu: `••••` + ostatnie 4 znaki, a bez nich samo `••••` (kontrakt §4)."""
    with_last4 = integration_dto(_view("abcd"))["client_secret_masked"]
    without_last4 = integration_dto(_view(None))["client_secret_masked"]
    assert with_last4 == "••••abcd"
    assert without_last4 == "••••"


def test_status_dto_latest_run() -> None:
    """`status_dto` wstawia skrót przebiegu albo `null` (kontrakt §4)."""
    dto = status_dto(StatusView(row=_row(None), latest_run=_run()))
    assert dto["id"] == 7  # noqa: PLR2004 — id z `_row()`
    assert dto["latest_run"] == {
        "id": 3,
        "started_at": _MOMENT_ISO,
        "finished_at": _LATER_ISO,
        "status": "ok",
        "added": 1,
        "updated": 2,
        "deleted": 3,
        "failed": 0,
    }
    assert status_dto(StatusView(row=_row(None), latest_run=None))["latest_run"] is None


def test_drive_dto_has_delta() -> None:
    """`has_delta` = zapisany kursor delty; znaczniki czasu jako ISO (kontrakt §4)."""
    with_cursor = ContainerRow(
        integration_id=7,
        container_id="drive-1",
        name="Docs",
        delta_cursor="cursor",
        last_sync_at=None,
        discovered_at=_MOMENT_MS,
    )
    without_cursor = ContainerRow(
        integration_id=7,
        container_id="drive-2",
        name="Archive",
        delta_cursor=None,
        last_sync_at=_MOMENT_MS,
        discovered_at=_MOMENT_MS,
    )
    assert drive_dto(with_cursor) == {
        "drive_id": "drive-1",
        "drive_name": "Docs",
        "has_delta": True,
        "last_sync_at": None,
        "discovered_at": _MOMENT_ISO,
    }
    assert drive_dto(without_cursor)["has_delta"] is False


def test_event_dto_maps_container_to_drive() -> None:
    """Kontener zdarzenia jedzie jako `drive_id`/`drive_name` (kontrakt §4)."""
    dto = event_dto(
        EventRow(
            id=1,
            run_id=3,
            integration_id=7,
            integration_type="sharepoint",
            level="info",
            message="m",
            file_path=None,
            container_id="drive-1",
            container_name="Docs",
            created_at=_MOMENT_MS,
        )
    )
    assert dto["drive_id"] == "drive-1"
    assert dto["drive_name"] == "Docs"
    assert dto["created_at"] == _MOMENT_ISO
