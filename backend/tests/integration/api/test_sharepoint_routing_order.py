"""Kolejność tras SVC SharePoint: `runs` nie może trafić do `/api/integrations/{id}` (brief T4b).

`GET /api/integrations/runs` ma tyle samo segmentów co `GET /api/integrations/{id}`, więc o tym,
która trasa wygrywa, decyduje kolejność w `sharepoint.routers` — pilnuje tego łatka mutacji
`backend/tests/mutations/e4-3a-runs-after-id.patch`. Wzorzec aplikacji i klienta z nagłówkiem
`X-API-Secret`: `tests/contract/hub_compat/user_api/conftest.py`; baza jest potrzebna, bo trasa
`runs` czyta tabelę przebiegów (`pytestmark = pytest.mark.db`).
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.core.config import Settings
from app.core.container import Container
from app.main import create_app
from tests.integration.ingest.pipeline_helpers import make_container

pytestmark = pytest.mark.db

SVC_SECRET = "test-secret"  # noqa: S105 — sekret wyłącznie testowy (K7 §1.7)
PREFIXES = ["", "/sharepoint-sync-api"]
_OK = 200
_BAD_REQUEST = 400
_NOT_FOUND = 404


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Sekret SVC + włączone integracje + storage w `tmp_path` (brief T4b p. 5)."""
    return auth_settings.model_copy(
        update={
            "storage_root": str(tmp_path),
            "hub_compat_api_secret": SecretStr(SVC_SECRET),
            "integrations_enabled": True,
        }
    )


@pytest.fixture
async def container(settings: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy na tej samej bazie co aplikacja; start ręczny."""
    instance = await make_container(settings, tmp_path)
    yield instance
    await instance.aclose()


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    """Aplikacja na tym samym `settings` i kontenerze co test."""
    return create_app(settings, container)


@pytest.fixture
async def svc(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient ASGI z nagłówkiem `X-API-Secret` (bez sieci)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Secret": SVC_SECRET}
    ) as client:
        yield client


@pytest.mark.parametrize("prefix", PREFIXES)
async def test_runs_is_not_captured_by_integration_id_route(
    svc: httpx.AsyncClient, prefix: str
) -> None:
    """`GET /api/integrations/runs` → 200 `{"data": []}`, a nie 400 „Invalid integration id”."""
    response = await svc.get(f"{prefix}/api/integrations/runs")
    assert response.status_code == _OK
    assert response.json() == {"data": []}


async def test_runs_events_reject_invalid_params(svc: httpx.AsyncClient) -> None:
    """Przykłady z briefu: zły `run_id` i zły `level` → 400 z komunikatem (nigdy 422)."""
    bad_run_id = await svc.get("/api/integrations/runs/abc/events")
    assert bad_run_id.status_code == _BAD_REQUEST
    assert bad_run_id.json() == {"error": "Invalid run id"}

    bad_level = await svc.get("/api/integrations/runs/1/events", params={"level": "debug"})
    assert bad_level.status_code == _BAD_REQUEST
    assert bad_level.json() == {"error": "Invalid level (use info|warn|error)"}


async def test_document_link_without_document_id_is_400(svc: httpx.AsyncClient) -> None:
    """Brak `documentId` → 400 „documentId is required” (brief, tabela przykładów)."""
    response = await svc.get("/api/documents/link")
    assert response.status_code == _BAD_REQUEST
    assert response.json() == {"error": "documentId is required"}


async def test_document_link_without_mapping_is_404(svc: httpx.AsyncClient) -> None:
    """Nieznany `documentId` → 404 z kodem przyczyny z `LinkNotFound` (brief, tabela przykładów)."""
    response = await svc.get("/api/documents/link", params={"documentId": "nie-ma-takiego"})
    assert response.status_code == _NOT_FOUND
    assert response.json() == {
        "error": "No SharePoint mapping for this document",
        "code": "no_mapping",
    }


async def test_datasets_proxies_dataset_list(svc: httpx.AsyncClient) -> None:
    """`GET /api/datasets` → 200 z listą datasetów (na świeżej bazie pusta)."""
    response = await svc.get("/api/datasets")
    assert response.status_code == _OK
    assert response.json() == {"data": []}
