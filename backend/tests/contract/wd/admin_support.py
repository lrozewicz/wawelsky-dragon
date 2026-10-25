"""Fixture'y kontraktowych testów tras WD admina (kontrakt E3-6a §6, zadanie T1).

Wzorzec ``tests/contract/wd/integrations/conftest.py`` bez zaślepki SharePoint i bez tras
integracji: ``settings`` (``env="dev"``), kontener na tej samej bazie co aplikacja oraz klienci
``admin``/``member``/``anon`` (Bearer klucza API, ASGITransport). Podkatalogi
``tests/contract/wd/{users,access,system}/`` re-eksportują te nazwy w swoich ``conftest.py``
(``from tests.contract.wd.admin_support import *``), więc fixture'y są widoczne w testach.

``fresh_db``/``migrated_db``/``auth_settings``/``sm`` dziedziczymy z ``tests/contract/conftest.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import audit_log as audit_repo
from app.db.repositories.audit_log import AuditRow
from app.db.repositories.users import UserRow
from app.db.uow import transaction
from app.main import create_app
from tests.integration.ingest.pipeline_helpers import make_container

ADMIN_EMAIL = "wd-admin@example.com"
MEMBER_EMAIL = "wd-member@example.com"
MEMBER_PASSWORD = "Str0ng-pass!"  # noqa: S105 — hasło wyłącznie testowe
SVC_SECRET = "test-secret"  # noqa: S105 — sekret SVC wyłącznie testowy (K7 §1.7)
CRYPTO_KEY = "0123456789abcdef" * 4

MakeUser = Callable[..., Awaitable[UserRow]]
AuditRows = Callable[[str], Awaitable[list[AuditRow]]]


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Sekrety testowe, storage w ``tmp_path``, dokument OpenAPI jak w eksporcie (§6)."""
    return auth_settings.model_copy(
        update={
            "env": "dev",
            "storage_root": str(tmp_path),
            "crypto_key": SecretStr(CRYPTO_KEY),
            "hub_compat_api_secret": SecretStr(SVC_SECRET),
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
def make_user(container: Container) -> MakeUser:
    """Helper: zakłada konto ``email`` i zwraca ``UserRow`` (domyślnie zwykły użytkownik)."""

    async def _make(
        email: str, *, superuser: bool = False, password: str | None = MEMBER_PASSWORD
    ) -> UserRow:
        assert container.users is not None
        return await container.users.create(email=email, password=password, is_superuser=superuser)

    return _make


@pytest.fixture
def audit_rows(sm: async_sessionmaker[AsyncSession]) -> AuditRows:
    """Helper: wpisy audytu danej akcji, kolejność wstawienia (kontrakt C2)."""

    async def _rows(action: str) -> list[AuditRow]:
        async with transaction(sm) as session:
            return await audit_repo.list_by_action(session, action)

    return _rows


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
