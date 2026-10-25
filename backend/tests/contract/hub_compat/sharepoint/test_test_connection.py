"""`POST /api/integrations/test-connection` — AG-24 (kontrakt E4-3a §4, 03 §5, 09 §10).

Sekwencja etapów `graph_auth` → `site_resolution` → `dataset_exists`, płaski DTO bez kluczy
z `None`, wczesny powrót przy porażce autoryzacji. Ostatni test używa prawdziwego
`SharePointConnector` na `httpx.MockTransport` (bez sieci), żeby potwierdzić filtr bibliotek
`system`/wykluczonych po nazwie.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.integrations import registry
from app.integrations.base import ConnectionReport
from app.integrations.sharepoint.connector import SharePointConnector
from app.integrations.sharepoint.graph import GRAPH_BASE_URL
from tests.contract.hub_compat.sharepoint.conftest import (
    SITE_ID,
    SITE_NAME,
    connection_body,
)
from tests.fakes.integrations import fake_load_config

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

OK = 200
BAD_REQUEST = 400
DATASET_NAME = "Korpus"

TOKEN_HOST = "login.microsoftonline.com"  # noqa: S105 — nazwa hosta, nie sekret
REAL_TENANT = "t-ag24-real"
SITE_CALL_PATH = "/v1.0/sites/contoso.sharepoint.com:/sites/eng"
DRIVES_PATH = f"/v1.0/sites/{SITE_ID}/drives"

OK_CHECKS = [
    {"name": "graph_auth", "status": "ok", "detail": ""},
    {"name": "site_resolution", "status": "ok", "detail": ""},
]
OK_RESOLVED: dict[str, object] = {
    "site_id": SITE_ID,
    "site_display_name": SITE_NAME,
    "libraries_total": 4,
    "libraries_included": 2,
}

# Biblioteki witryny: `Site Assets` niesie `system` (filtr po kluczu), `Site Pages`
# wypada z domyślnych wykluczeń po nazwie — dlatego `libraries_total` != `libraries_included`.
REAL_DRIVES = [
    {"id": "d1", "name": "Dokumenty"},
    {"id": "d2", "name": "Site Assets", "system": {}},
    {"id": "d3", "name": "Site Pages"},
    {"id": "d4", "name": "Wspólne"},
]
REAL_TOTAL = 3
REAL_INCLUDED = 2

_MISSING_CASES = [
    ({"client_secret": None}, "client_secret is required and must be a non-empty string"),
    ({"client_id": ""}, "client_id is required and must be a non-empty string"),
    ({"site_url": 5}, "site_url is required and must be a non-empty string"),
    ({"dataset_id": 7}, "dataset_id must be a string"),
]


def ok_report() -> ConnectionReport:
    """Raport udanej autoryzacji i rozwiązywania witryny (09 §10)."""
    return ConnectionReport(ok=True, checks=list(OK_CHECKS), resolved=dict(OK_RESOLVED))


async def test_ag24_all_stages_ok(svc: Any, prefix: str, connector: Any, seed_dataset: Any) -> None:
    """AG-24(a): wszystkie etapy `ok` → dokładne klucze DTO z `drive_names` i nazwą datasetu."""
    _owner, dataset_id = await seed_dataset()
    connector.report = ok_report()

    response = await svc.post(
        f"{prefix}/api/integrations/test-connection",
        json=connection_body(dataset_id=dataset_id),
    )

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert set(data) == {
        "graph_auth",
        "site_resolution",
        "site_id",
        "site_display_name",
        "drives_visible",
        "drives_after_exclusion",
        "drive_names",
        "dataset_exists",
        "dataset_name",
    }
    assert data["graph_auth"] == "ok"
    assert data["site_resolution"] == "ok"
    assert data["site_id"] == SITE_ID
    assert data["site_display_name"] == SITE_NAME
    assert data["drives_visible"] == OK_RESOLVED["libraries_total"]
    assert data["drives_after_exclusion"] == OK_RESOLVED["libraries_included"]
    assert data["drive_names"] == ["Dokumenty", "Wspólne"]
    assert data["dataset_exists"] == "ok"
    assert data["dataset_name"] == DATASET_NAME


async def test_ag24_graph_auth_failure_returns_early(
    svc: Any, prefix: str, connector: Any, seed_dataset: Any
) -> None:
    """AG-24(b): porażka `graph_auth` → wczesny powrót i `skipped` na dalszych etapach."""
    _owner, dataset_id = await seed_dataset()
    connector.report = ConnectionReport(
        ok=False,
        checks=[{"name": "graph_auth", "status": "failed", "detail": "AADSTS7000215"}],
        resolved={},
    )

    response = await svc.post(
        f"{prefix}/api/integrations/test-connection",
        json=connection_body(dataset_id=dataset_id),
    )

    assert response.status_code == OK, response.text
    assert response.json()["data"] == {
        "graph_auth": "failed",
        "graph_auth_error": "AADSTS7000215",
        "site_resolution": "skipped",
        "dataset_exists": "skipped",
    }


async def test_ag24_site_resolution_failure(
    svc: Any, prefix: str, connector: Any, seed_dataset: Any
) -> None:
    """AG-24(c): porażka `site_resolution` → `site_resolution_error`, bez pól witryny."""
    _owner, dataset_id = await seed_dataset()
    connector.report = ConnectionReport(
        ok=False,
        checks=[
            {"name": "graph_auth", "status": "ok", "detail": ""},
            {"name": "site_resolution", "status": "failed", "detail": "site not found"},
        ],
        resolved={},
    )

    response = await svc.post(
        f"{prefix}/api/integrations/test-connection",
        json=connection_body(dataset_id=dataset_id),
    )

    assert response.status_code == OK, response.text
    assert response.json()["data"] == {
        "graph_auth": "ok",
        "site_resolution": "failed",
        "site_resolution_error": "site not found",
        "dataset_exists": "ok",
        "dataset_name": DATASET_NAME,
    }


async def test_ag24_dataset_not_found_locally(svc: Any, prefix: str, connector: Any) -> None:
    """AG-24(d): nieistniejący `dataset_id` → `not_found` sprawdzone lokalnie (bez HTTP)."""
    connector.report = ok_report()

    response = await svc.post(
        f"{prefix}/api/integrations/test-connection",
        json=connection_body(dataset_id=uuid.uuid4().hex),
    )

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert data["dataset_exists"] == "not_found"
    assert "dataset_name" not in data


async def test_ag24_without_dataset_id_is_skipped(svc: Any, prefix: str, connector: Any) -> None:
    """AG-24(e): brak `dataset_id` → `dataset_exists: "skipped"`, bez `dataset_name`."""
    connector.report = ok_report()

    response = await svc.post(f"{prefix}/api/integrations/test-connection", json=connection_body())

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert data["dataset_exists"] == "skipped"
    assert "dataset_name" not in data
    assert data["drive_names"] == ["Dokumenty", "Wspólne"]


@pytest.mark.parametrize(("over", "message"), _MISSING_CASES)
async def test_ag24_credential_validation(
    svc: Any, prefix: str, connector: Any, over: dict[str, object], message: str
) -> None:
    """AG-24(f): sekret i creds są wymagane zawsze → 400 z komunikatem pola."""
    body = connection_body(**over)

    response = await svc.post(f"{prefix}/api/integrations/test-connection", json=body)

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json() == {"error": message}


def graph_handler(request: httpx.Request) -> httpx.Response:
    """Symulator Graph: token, witryna, biblioteki — bez sieci (wzorzec E4-2b)."""
    if request.url.host == TOKEN_HOST:
        return httpx.Response(OK, json={"access_token": "tok", "expires_in": 3599})
    if request.url.path == SITE_CALL_PATH:
        return httpx.Response(OK, json={"id": SITE_ID, "displayName": SITE_NAME})
    if request.url.path == DRIVES_PATH:
        return httpx.Response(OK, json={"value": REAL_DRIVES})
    raise AssertionError(f"nieoczekiwane żądanie symulatora: {request.url}")


def mock_factory() -> httpx.AsyncClient:
    """Klient HTTP na `MockTransport` (konektor tworzy nowy na każde wywołanie)."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(graph_handler),
        base_url=GRAPH_BASE_URL,
        follow_redirects=False,
    )


async def test_ag24_real_connector_ignores_system_drives(svc: Any, prefix: str) -> None:
    """AG-24: prawdziwy konektor na MockTransport — `system`/wykluczone nie wchodzą do listy."""
    factory: Callable[[], httpx.AsyncClient] = mock_factory
    registry.register("sharepoint", SharePointConnector(http_factory=factory), fake_load_config)
    try:
        response = await svc.post(
            f"{prefix}/api/integrations/test-connection",
            json=connection_body(tenant_id=REAL_TENANT),
        )
    finally:
        registry.clear()

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert data["graph_auth"] == "ok"
    assert data["site_resolution"] == "ok"
    assert data["site_id"] == SITE_ID
    assert data["drive_names"] == ["Dokumenty", "Wspólne"]
    assert "Site Assets" not in data["drive_names"]
    assert data["drives_visible"] == REAL_TOTAL
    assert data["drives_after_exclusion"] == REAL_INCLUDED
    assert data["drives_visible"] != data["drives_after_exclusion"]
    assert data["dataset_exists"] == "skipped"
