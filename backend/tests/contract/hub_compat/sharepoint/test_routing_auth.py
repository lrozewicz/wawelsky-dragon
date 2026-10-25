"""Montaż prefiksów, health i uwierzytelnianie SVC SharePoint: AG-29, AG-30, AG-31.

Każda trasa tabeli 03 §5 jest sprawdzana pod oboma prefiksami (`""` i `/sharepoint-sync-api`)
oraz bez `X-API-Secret` — ten drugi blok jest testem negatywnym dla łatki mutacyjnej
`tests/mutations/e4-3a-no-secret-check.patch`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.core.config import Settings
from app.core.container import Container
from app.main import create_app
from tests.contract.hub_compat.sharepoint.conftest import (
    SVC_SECRET,
    connection_body,
    integration_body,
)
from tests.integration.ingest.pipeline_helpers import make_container

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

OK = 200
CREATED = 201
ACCEPTED = 202
BAD_REQUEST = 400
UNAUTHORIZED = 401
NOT_FOUND = 404
RF_UNAUTHORIZED_CODE = 401
WRONG_SECRET = "zly"  # noqa: S105 — sekret wyłącznie testowy

# (metoda, ścieżka, rodzaj ciała, oczekiwany status) — pełna tabela tras 03 §5.
ROUTE_CASES: list[tuple[str, str, str, int]] = [
    ("GET", "/api/integrations", "none", OK),
    ("POST", "/api/integrations", "create", CREATED),
    ("POST", "/api/integrations/test-connection", "connection", OK),
    ("GET", "/api/integrations/runs", "none", OK),
    ("GET", "/api/integrations/runs/1/events", "none", OK),
    ("GET", "/api/integrations/{id}", "none", OK),
    ("PUT", "/api/integrations/{id}", "empty", OK),
    ("DELETE", "/api/integrations/{id}", "none", OK),
    ("POST", "/api/integrations/{id}/sync", "none", ACCEPTED),
    ("POST", "/api/integrations/{id}/cancel", "none", OK),
    ("GET", "/api/integrations/{id}/status", "none", OK),
    ("GET", "/api/integrations/{id}/drives", "none", OK),
    ("GET", "/api/datasets", "none", OK),
    ("GET", "/api/documents/link?documentId=brak", "none", NOT_FOUND),
]

# Ten sam zbiór bez tworzenia danych: identyfikator nie musi istnieć, bo sekret sprawdza
# się przed ciałem trasy (`dependencies=[Depends(require_secret)]`).
AUTH_CASES: list[tuple[str, str]] = [
    (method, path.replace("{id}", "1")) for method, path, _kind, _status in ROUTE_CASES
]


async def make_client(app: FastAPI, headers: dict[str, str]) -> httpx.AsyncClient:
    """Klient ASGI na aplikacji z podanymi nagłówkami domyślnymi."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)


@pytest.fixture
async def bad(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient ze złym `X-API-Secret` (AG-31)."""
    async with await make_client(app, {"X-API-Secret": WRONG_SECRET}) as client:
        yield client


@pytest.fixture
async def empty_secret_client(
    settings: Settings, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Aplikacja z pustym `WD_HUB_COMPAT_API_SECRET` — 401 wszędzie poza health (K7 §1.7)."""
    empty = settings.model_copy(update={"hub_compat_api_secret": SecretStr("")})
    container = await make_container(empty, tmp_path)
    try:
        async with await make_client(create_app(empty, container), {"X-API-Secret": ""}) as client:
            yield client
    finally:
        await container.aclose()


@pytest.fixture
async def disabled_integrations_client(
    settings: Settings, container: Container
) -> AsyncIterator[httpx.AsyncClient]:
    """Aplikacja z `integrations_enabled=False` — trasy SharePoint nie są montowane (K7 §7 p. 2)."""
    disabled = settings.model_copy(update={"integrations_enabled": False})
    headers = {"X-API-Secret": SVC_SECRET}
    async with await make_client(create_app(disabled, container), headers) as client:
        yield client


def body_for(kind: str, dataset_id: str) -> dict[str, object] | None:
    """Ciało żądania dla przypadku trasy; `none` = brak ciała (GET/DELETE/sync/cancel)."""
    if kind == "create":
        return integration_body(dataset_id)
    if kind == "connection":
        return connection_body()
    if kind == "empty":
        return {}
    return None


@pytest.mark.parametrize(("method", "suffix", "kind", "expected"), ROUTE_CASES)
async def test_ag29_every_route_under_both_prefixes(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    method: str,
    suffix: str,
    kind: str,
    expected: int,
) -> None:
    """AG-29: każda trasa odpowiada pod `""` i `/sharepoint-sync-api` (nie 404 z fallbacku)."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    _owner2, free_dataset = await seed_dataset()
    url = f"{prefix}{suffix.format(id=created['id'])}"

    response = await svc.request(method, url, json=body_for(kind, free_dataset))

    assert response.status_code == expected, response.text
    if expected == NOT_FOUND:  # `/api/documents/link` bez mapowania: 404 trasy, nie fallbacku
        assert response.json()["code"] == "no_mapping"
        assert response.json() != {"error": "Not found"}


async def test_ag29_unknown_route_under_sharepoint_prefix(svc: Any, anon: Any, bad: Any) -> None:
    """AG-29/K7 §7 p. 1: fallback pod `/sharepoint-sync-api` → 404 `{error: Not found}`."""
    with_secret = await svc.get("/sharepoint-sync-api/api/foo")
    without_secret = await anon.get("/sharepoint-sync-api/api/foo")
    with_bad_secret = await bad.get("/sharepoint-sync-api/api/foo")

    assert with_secret.status_code == NOT_FOUND
    assert with_secret.json() == {"error": "Not found"}
    assert without_secret.status_code == UNAUTHORIZED
    assert without_secret.json() == {"error": "Unauthorized"}
    assert with_bad_secret.status_code == UNAUTHORIZED
    assert with_bad_secret.json() == {"error": "Unauthorized"}


async def test_ag30_health_under_both_prefixes_without_secret(anon: Any, prefix: str) -> None:
    """AG-30: `/api/health` i `/sharepoint-sync-api/api/health` → 200 `{status: ok}` bez auth."""
    response = await anon.get(f"{prefix}/api/health")

    assert response.status_code == OK
    assert response.json() == {"status": "ok"}


async def test_ag30_health_ignores_wrong_secret(app: FastAPI, prefix: str) -> None:
    """AG-30: health nie sprawdza `X-API-Secret`."""
    async with await make_client(app, {"X-API-Secret": WRONG_SECRET}) as client:
        response = await client.get(f"{prefix}/api/health")

    assert response.status_code == OK
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(("method", "path"), AUTH_CASES)
async def test_ag31_every_route_rejects_missing_or_wrong_secret(
    anon: Any, bad: Any, prefix: str, method: str, path: str
) -> None:
    """AG-31: brak i zły `X-API-Secret` → 401 `{error: Unauthorized}` na każdej trasie."""
    url = f"{prefix}{path}"

    without = await anon.request(method, url)
    wrong = await bad.request(method, url)

    assert without.status_code == UNAUTHORIZED, f"{method} {url}: {without.text}"
    assert without.json() == {"error": "Unauthorized"}
    assert wrong.status_code == UNAUTHORIZED, f"{method} {url}: {wrong.text}"
    assert wrong.json() == {"error": "Unauthorized"}


async def test_ag31_empty_secret_rejects_even_empty_header(
    empty_secret_client: httpx.AsyncClient, prefix: str
) -> None:
    """K7 §1.7: pusty sekret w Settings ⇒ 401 także z pustym nagłówkiem; health działa."""
    rejected = await empty_secret_client.get(f"{prefix}/api/integrations")
    health = await empty_secret_client.get(f"{prefix}/api/health")

    assert rejected.status_code == UNAUTHORIZED
    assert rejected.json() == {"error": "Unauthorized"}
    assert health.status_code == OK
    assert health.json() == {"status": "ok"}


async def test_ag31_runs_route_is_not_integration_id(svc: Any, prefix: str, connector: Any) -> None:
    """AG-31/§4: `GET /api/integrations/runs` to lista przebiegów, nie integracja o id „runs”."""
    response = await svc.get(f"{prefix}/api/integrations/runs")

    assert response.status_code == OK, response.text
    assert response.json() == {"data": []}


async def test_ag31_datasets_svc_route_does_not_shadow_ragflow(
    svc: Any, prefix: str, connector: Any, seed_dataset: Any
) -> None:
    """AG-31: `GET /api/datasets` (SVC) działa, a `/api/v1/datasets` bez Bearera daje kopertę RF."""
    _owner, dataset_id = await seed_dataset()

    svc_response = await svc.get(f"{prefix}/api/datasets")
    assert svc_response.status_code == OK, svc_response.text
    assert [item["id"] for item in svc_response.json()["data"]] == [dataset_id]

    ragflow = await svc.get("/api/v1/datasets")
    assert ragflow.status_code == UNAUTHORIZED, ragflow.text
    envelope = ragflow.json()
    assert set(envelope) == {"code", "message", "data"}
    assert envelope["code"] == RF_UNAUTHORIZED_CODE
    assert envelope != {"error": "Unauthorized"}


async def test_ag31_integrations_disabled_is_not_svc_route(
    disabled_integrations_client: httpx.AsyncClient,
) -> None:
    """K7 §7 p. 2: `integrations_enabled=False` ⇒ `/api/integrations` w ogóle nie istnieje (404)."""
    response = await disabled_integrations_client.get("/api/integrations")

    assert response.status_code == NOT_FOUND
    body = response.json()
    assert body != {"error": "Not found"}
    assert "Not Found: /api/integrations" in str(body)
