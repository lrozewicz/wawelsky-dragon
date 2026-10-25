"""Fixture'y kontraktowych testów tras WD integracji (brief T2, kontrakt E4-3b §6).

``fresh_db``/``migrated_db``/``auth_settings``/``sm`` dziedziczymy z ``tests/contract/conftest.py``
(conftest katalogu nadrzędnego — bez re-eksportu). Wzorce: ``tests/contract/hub_compat/sharepoint/``
(kontener, ASGITransport, zaślepka konektora), ``tests/contract/hub_compat/ragflow_calls/`` (tokeny
kluczy API w nagłówku ``Authorization``) i ``tests/integration/integrations/conftest.py``
(``seed_dataset_and_user``).

``env="dev"`` w ``settings``, a nie „test”: schemat OpenAPI tras WD musi odpowiadać dokumentowi
eksportowanemu (``env != test`` nie montuje ``/api/wd/v1/test/reset``) — kontrakt §5.
Trasy WD autoryzujemy Bearerem klucza API (``container.api_keys.create``) — wystarczy podmiot
z ``is_superuser``; ``require_admin`` nie patrzy na rodzaj tokenu (kontrakt §0 p. 2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
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
from app.main import create_app
from tests.fakes.integrations import FakeConnector, fake_load_config
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.integrations.conftest import seed_dataset_and_user

# Sekrety testowe (K7 §1.7 / §7 p. 6) — nigdy nie są prawdziwymi sekretami.
CLIENT_SECRET = "s3cr3t-abcd"  # noqa: S105
CRYPTO_KEY = "0123456789abcdef" * 4
ADMIN_EMAIL = "wd-admin@example.com"
MEMBER_EMAIL = "wd-member@example.com"

CREATED = 201

SITE_ID = "S1"
SITE_NAME = "Eng"
SITE_URL = "https://contoso.sharepoint.com/sites/eng"
TENANT_ID = "t-tenant"
CLIENT_ID = "c-client"

SeedDataset = Callable[[], Awaitable[str]]
CreateIntegration = Callable[..., Awaitable[dict[str, Any]]]


class SharePointFake(FakeConnector):
    """Zaślepka konektora pod typem ``sharepoint`` (skopiowana z kontraktu E4-3a §5).

    ``resolve`` zwraca stałą witrynę (albo rzuca, gdy ``fail_resolve``), ``test_connection``
    i ``web_link`` są skryptowane atrybutami — trasy WD wołają tę samą usługę co SVC.
    """

    type = "sharepoint"

    def __init__(self) -> None:
        super().__init__()
        self.fail_resolve = False
        self.report: ConnectionReport | None = None
        self.link_item: RemoteItem | None = None
        self.link_error: Exception | None = None
        self.link_calls: list[tuple[str, str]] = []

    async def resolve(self, cfg: object) -> dict[str, Any]:
        """Stała witryna ``S1``/``Eng``; ``fail_resolve`` symuluje błąd Graph."""
        if self.fail_resolve:
            raise RuntimeError("Site not found")
        return {"site_id": SITE_ID, "site_display_name": SITE_NAME}

    async def test_connection(self, cfg: object, *, dataset_exists: bool) -> ConnectionReport:
        """Raport skryptowany atrybutem ``report``; domyślnie pusty (etap ``graph_auth`` failed)."""
        if self.report is None:
            return ConnectionReport(ok=True, checks=[], resolved={})
        return self.report

    async def web_link(self, cfg: object, container_id: str, item_id: str) -> RemoteItem | None:
        """Link elementu skryptowany ``link_item``; ``link_error`` symuluje błąd Graph (502)."""
        self.link_calls.append((container_id, item_id))
        if self.link_error is not None:
            raise self.link_error
        return self.link_item


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Sekrety testowe, storage w ``tmp_path``, powierzchnia WD integracji włączona (§6)."""
    return auth_settings.model_copy(
        update={
            "env": "dev",
            "storage_root": str(tmp_path),
            "crypto_key": SecretStr(CRYPTO_KEY),
            "integrations_enabled": True,
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
    """Aplikacja na tym samym ``settings`` i kontenerze co test (kontrakt C9)."""
    return create_app(settings, container)


@pytest.fixture
def connector(app: FastAPI) -> AsyncIterator[SharePointFake]:
    """Podmienia rejestr ``sharepoint`` na zaślepkę (po ``create_app``) i czyści go po teście."""
    fake = SharePointFake()
    registry.register("sharepoint", fake, fake_load_config)
    yield fake
    registry.clear()


async def _api_key(container: Container, email: str, *, superuser: bool) -> str:
    """Klucz API dla świeżego konta o podanym e-mailu; zwraca jawny token (Bearer)."""
    assert container.users is not None
    assert container.api_keys is not None
    user = await container.users.create(email=email, password=None, is_superuser=superuser)
    key = await container.api_keys.create(container.users.principal_of(user))
    return key.token


def _client(app: FastAPI, token: str | None) -> httpx.AsyncClient:
    """Klient ASGI (bez sieci); ``token`` w nagłówku ``Authorization``, gdy podany."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
    )


@pytest.fixture
async def admin(app: FastAPI, container: Container) -> AsyncIterator[httpx.AsyncClient]:
    """Klient z Bearerem klucza API superusera (200 na trasach WD)."""
    async with _client(app, await _api_key(container, ADMIN_EMAIL, superuser=True)) as client:
        yield client


@pytest.fixture
async def member(app: FastAPI, container: Container) -> AsyncIterator[httpx.AsyncClient]:
    """Klient z Bearerem klucza API zwykłego użytkownika (403 na trasach WD)."""
    async with _client(app, await _api_key(container, MEMBER_EMAIL, superuser=False)) as client:
        yield client


@pytest.fixture
async def anon(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient **bez** nagłówka ``Authorization`` (testy 401)."""
    async with _client(app, None) as client:
        yield client


@pytest.fixture
def seed_dataset(sm: async_sessionmaker[AsyncSession]) -> SeedDataset:
    """Helper: zakłada użytkownika i dataset w bazie; zwraca ``dataset_id``."""

    async def _seed() -> str:
        _, dataset_id = await seed_dataset_and_user(sm)
        return dataset_id

    return _seed


@pytest.fixture
def create_integration(admin: httpx.AsyncClient) -> CreateIntegration:
    """Helper: ``POST /api/wd/v1/integrations`` z ``type="sharepoint"``; zwraca ``data`` (201).

    Działa po T3 (trasy CRUD); WOŁAJ go z ``dataset_id`` z ``seed_dataset()``.
    """

    async def _create(dataset_id: str, **over: object) -> dict[str, Any]:
        body: dict[str, object] = {"type": "sharepoint", **integration_body(dataset_id)}
        body.update(over)
        response = await admin.post("/api/wd/v1/integrations", json=body)
        assert response.status_code == CREATED, response.text
        return dict(response.json()["data"])

    return _create


def integration_body(dataset_id: str, **over: object) -> dict[str, object]:
    """Poprawne ciało ``POST /api/wd/v1/integrations`` (kontrakt E4-3b §2)."""
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
