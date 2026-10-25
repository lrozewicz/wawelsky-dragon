"""Fixture'y kontraktowych testów SVC `sharepoint-sync` (brief T5a, kontrakt E4-3a).

`fresh_db`/`migrated_db`/`auth_settings`/`sm` dziedziczymy z `tests/contract/conftest.py`
(conftest katalogu nadrzędnego — bez re-eksportu). Wzorce: `tests/contract/hub_compat/user_api/`
(kontener, ASGITransport, prefiksy) i `tests/integration/integrations/conftest.py`
(`seed_dataset_and_user`, `FakeConnector`).

Kluczowa kolejność: `create_app` rejestruje realny `SharePointConnector` (DEC-074 p. 3),
dlatego fixture `connector` zależy od `app` i podmienia rejestr **po** zbudowaniu aplikacji.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.integrations import registry
from app.integrations.base import ConnectionReport, RemoteItem
from app.integrations.base import Container as RemoteContainer
from app.main import create_app
from tests.fakes.integrations import FakeConnector, fake_load_config
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.integrations.conftest import seed_dataset_and_user

# Sekrety testowe (K7 §1.7 / §7 p. 6) — nigdy nie są prawdziwymi sekretami.
SVC_SECRET = "test-secret"  # noqa: S105
CLIENT_SECRET = "s3cr3t-abcd"  # noqa: S105
CLIENT_SECRET_MASK = "••••abcd"  # noqa: S105 — maska, nie sekret
CRYPTO_KEY = "0123456789abcdef" * 4

CREATED = 201

SITE_ID = "S1"
SITE_NAME = "Eng"
SITE_URL = "https://contoso.sharepoint.com/sites/eng"
TENANT_ID = "t-tenant"
CLIENT_ID = "c-client"

CONTAINER_D1 = "d1"
CONTAINER_D2 = "d2"
CONTAINER_D1_NAME = "Dokumenty"
CONTAINER_D2_NAME = "Wspólne"

WORKER_POLL_S = 0.02
WAIT_POLL_S = 0.01
WAIT_TIMEOUT_S = 5.0

SeedDataset = Callable[[], Awaitable[tuple[str, str]]]
CreateIntegration = Callable[..., Awaitable[dict[str, Any]]]


class SharePointFake(FakeConnector):
    """Zaślepka konektora pod typem `sharepoint` (kontrakt E4-3a §5, wzorzec `FakeConnector`).

    `resolve` zwraca stałą witrynę (albo rzuca, gdy `fail_resolve`), `test_connection`
    i `web_link` są skryptowane atrybutami — tak jak w testach usługi (K12 §3).
    """

    type = "sharepoint"

    def __init__(self) -> None:
        super().__init__()
        self.containers = [
            RemoteContainer(id=CONTAINER_D1, name=CONTAINER_D1_NAME),
            RemoteContainer(id=CONTAINER_D2, name=CONTAINER_D2_NAME),
        ]
        self.fail_resolve = False
        self.report: ConnectionReport | None = None
        self.link_item: RemoteItem | None = None
        self.link_error: Exception | None = None
        self.link_calls: list[tuple[str, str]] = []

    async def resolve(self, cfg: object) -> dict[str, Any]:
        """Stała witryna `S1`/`Eng`; `fail_resolve` symuluje błąd Graph (400 z trasy)."""
        if self.fail_resolve:
            raise RuntimeError("Site not found")
        return {"site_id": SITE_ID, "site_display_name": SITE_NAME}

    async def test_connection(self, cfg: object, *, dataset_exists: bool) -> ConnectionReport:
        """Raport skryptowany atrybutem `report`; domyślnie pusty (etap `graph_auth` failed)."""
        if self.report is None:
            return ConnectionReport(ok=True, checks=[], resolved={})
        return self.report

    async def web_link(self, cfg: object, container_id: str, item_id: str) -> RemoteItem | None:
        """Link elementu skryptowany `link_item`; `link_error` symuluje błąd Graph (502)."""
        self.link_calls.append((container_id, item_id))
        if self.link_error is not None:
            raise self.link_error
        return self.link_item


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Sekrety testowe, storage w `tmp_path`, powierzchnia SVC SharePoint włączona (§4)."""
    return auth_settings.model_copy(
        update={
            "storage_root": str(tmp_path),
            "hub_compat_api_secret": SecretStr(SVC_SECRET),
            "crypto_key": SecretStr(CRYPTO_KEY),
            "integrations_enabled": True,
            "hub_compat_routes": True,
            "worker_poll_s": WORKER_POLL_S,
        }
    )


@pytest.fixture
async def container(settings: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy na tej samej bazie co aplikacja; start ręczny (C9)."""
    instance = await make_container(settings, tmp_path)
    yield instance
    await instance.aclose()


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    """Aplikacja na tym samym `settings` i kontenerze co test; rejestruje realny konektor."""
    return create_app(settings, container)


@pytest.fixture
def connector(app: FastAPI) -> Iterator[SharePointFake]:
    """Podmienia rejestr `sharepoint` na zaślepkę (po `create_app`) i czyści go po teście."""
    fake = SharePointFake()
    registry.register("sharepoint", fake, fake_load_config)
    yield fake
    registry.clear()


@pytest.fixture
async def svc(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient z nagłówkiem `X-API-Secret` (ASGI, bez sieci)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Secret": SVC_SECRET}
    ) as client:
        yield client


@pytest.fixture
async def anon(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient **bez** nagłówka `X-API-Secret` (testy 401, AG-31)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture(params=["", "/sharepoint-sync-api"])
def prefix(request: pytest.FixtureRequest) -> str:
    """Prefiks montażu powierzchni SharePoint: `""` i `"/sharepoint-sync-api"` (AG-29)."""
    return str(request.param)


@pytest.fixture
def seed_dataset(sm: async_sessionmaker[AsyncSession]) -> SeedDataset:
    """Helper: zakłada użytkownika i dataset w bazie; zwraca `(owner_id, dataset_id)`."""

    async def _seed() -> tuple[str, str]:
        return await seed_dataset_and_user(sm)

    return _seed


@pytest.fixture
def create_integration(
    svc: httpx.AsyncClient, prefix: str, connector: SharePointFake
) -> CreateIntegration:
    """Helper: `POST {prefix}/api/integrations` z poprawnym ciałem; zwraca `data` (201)."""

    async def _create(dataset_id: str, **over: object) -> dict[str, Any]:
        body: dict[str, object] = dict(integration_body(dataset_id))
        body.update(over)
        response = await svc.post(f"{prefix}/api/integrations", json=body)
        assert response.status_code == CREATED, response.text
        return dict(response.json()["data"])

    return _create


def integration_body(dataset_id: str, **over: object) -> dict[str, object]:
    """Poprawne ciało `POST /api/integrations` (kontrakt E4-3a §4, tabela 03 §5)."""
    body: dict[str, object] = {
        "name": "SP test",
        "dataset_id": dataset_id,
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "site_url": SITE_URL,
    }
    body.update(over)
    return body


def connection_body(**over: object) -> dict[str, object]:
    """Poprawne ciało `POST /api/integrations/test-connection` (AG-24)."""
    body: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "site_url": SITE_URL,
    }
    body.update(over)
    return body


async def wait_async(
    predicate: Callable[[], Awaitable[bool]], *, timeout_s: float = WAIT_TIMEOUT_S
) -> None:
    """Czeka na asynchroniczny warunek (kopiowane z `test_scenario.py`, WP E4-1).

    Pętla krótkich uśpien zamiast `sleep` na sztywno — praca w tle może się jeszcze nie zacząć.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not await predicate():
        if loop.time() >= deadline:
            raise AssertionError("warunek nie został osiągnięty")
        await asyncio.sleep(WAIT_POLL_S)
