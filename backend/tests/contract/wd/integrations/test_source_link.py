"""Trasa WD ``GET /documents/{id}/source-link`` (brief T4, kontrakt E4-3b §0 p. 9, §4).

Kształt ``data`` jest snake_case (``web_url``, ``name``, ``path``, ``drive_name``) —
inaczej niż camelCase trasy SVC. Brak mapowania / zniknięty element → 404 ze slugiem
przyczyny (``no_mapping`` / ``item_not_found``), błąd Graph → 502 ``upstream_error``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import MappingRow
from app.db.uow import transaction
from app.services.integration_input import (
    DEFAULT_EXCLUDED_LIBRARY_NAMES,
    DEFAULT_IGNORED_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    IntegrationCreate,
)
from app.services.integration_ops import Actor
from app.services.integrations import IntegrationService
from tests.contract.wd.integrations.conftest import (
    CLIENT_ID,
    CLIENT_SECRET,
    SITE_URL,
    TENANT_ID,
)
from tests.fakes.integrations import make_item

pytestmark = pytest.mark.contract

WD = "/api/wd/v1"
OK = 200
UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404
UPSTREAM_ERROR = 502

STALE_MS = 0  # mapping sprzed epoki — zawsze starszy niż 24 h (kontrakt E4-3a §3 p. 3)
CONTAINER_D1 = "d1"
CONTAINER_D1_NAME = "Dokumenty"
ITEM_ID = "i1"
WEB_URL = "https://contoso.sharepoint.com/sites/eng/Dokumenty/a.txt"
LINK_KEYS = {"web_url", "name", "path", "drive_name"}

MakeIntegration = Callable[[str], Coroutine[Any, Any, int]]


@pytest.fixture
def make_integration(app: FastAPI, connector: Any) -> MakeIntegration:
    """Zakłada integrację usługą aplikacji (``POST /integrations`` dochodzi w T3)."""
    service: IntegrationService = app.state.integrations

    async def _make(dataset_id: str) -> int:
        view = await service.create(
            IntegrationCreate(
                name="SP test",
                dataset_id=dataset_id,
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                site_url=SITE_URL,
                excluded_library_names=list(DEFAULT_EXCLUDED_LIBRARY_NAMES),
                max_file_size_bytes=DEFAULT_MAX_FILE_SIZE_BYTES,
                ignored_extensions=list(DEFAULT_IGNORED_EXTENSIONS),
                scan_interval_seconds=DEFAULT_SCAN_INTERVAL_SECONDS,
                delete_propagation=True,
                is_active=True,
            ),
            Actor(label="wd-test"),
        )
        return view.row.id

    return _make


async def seed_mapping(
    sm: async_sessionmaker[AsyncSession], integration_id: int, *, document_id: str
) -> None:
    """Kontener ``d1`` i mapowanie dokumentu bez ``web_url`` (starsze niż 24 h)."""
    async with transaction(sm) as session:
        await integrations_repo.upsert_container(
            session, integration_id, CONTAINER_D1, name=CONTAINER_D1_NAME, now_ms=STALE_MS
        )
        await integrations_repo.upsert_mapping(
            session,
            MappingRow(
                integration_id=integration_id,
                container_id=CONTAINER_D1,
                item_id=ITEM_ID,
                document_id=document_id,
                content_tag=None,
                meta_tag=None,
                name=None,
                path=None,
                web_url=None,
                last_status="ok",
                last_error=None,
                updated_at=STALE_MS,
            ),
        )


async def test_source_link_returns_exact_shape(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
    connector: Any,
) -> None:
    """``GET /source-link`` → 200 ``{web_url, name, path, drive_name}`` z konektora (brief)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(sm, integration_id, document_id=document_id)
    connector.link_item = make_item(
        container_id=CONTAINER_D1,
        item_id=ITEM_ID,
        name="a.txt",
        path="/a.txt",
        web_url=WEB_URL,
    )

    response = await admin.get(f"{WD}/documents/{document_id}/source-link")

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert set(data) == LINK_KEYS
    assert data == {
        "web_url": WEB_URL,
        "name": "a.txt",
        "path": "/a.txt",
        "drive_name": CONTAINER_D1_NAME,
    }
    assert connector.link_calls == [(CONTAINER_D1, ITEM_ID)]
    assert CLIENT_SECRET not in response.text


async def test_source_link_no_mapping_is_404(admin: Any, connector: Any) -> None:
    """Dokument bez mapowania → 404 ``no_mapping`` w kopercie WD (brief, wiersz 13)."""
    response = await admin.get(f"{WD}/documents/{uuid.uuid4().hex}/source-link")

    assert response.status_code == NOT_FOUND, response.text
    body = response.json()["error"]
    assert body["code"] == "no_mapping"
    assert body["message"] == "No SharePoint mapping for this document"


async def test_source_link_item_not_found_is_404(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
    connector: Any,
) -> None:
    """Element zniknął z SharePoint (``web_link`` → ``None``) → 404 ``item_not_found``."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(sm, integration_id, document_id=document_id)

    response = await admin.get(f"{WD}/documents/{document_id}/source-link")

    assert response.status_code == NOT_FOUND, response.text
    body = response.json()["error"]
    assert body["code"] == "item_not_found"
    assert body["message"] == "Item no longer exists in SharePoint"


async def test_source_link_upstream_error_is_502(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
    connector: Any,
) -> None:
    """Błąd konektora inny niż brak elementu → 502 ``upstream_error`` (brief, wiersz 13)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(sm, integration_id, document_id=document_id)
    connector.link_error = RuntimeError("graph down")

    response = await admin.get(f"{WD}/documents/{document_id}/source-link")

    assert response.status_code == UPSTREAM_ERROR, response.text
    assert response.json()["error"]["code"] == "upstream_error"


async def test_source_link_requires_authentication(anon: Any, member: Any) -> None:
    """Bez nagłówka → 401 ``unauthorized``; jako ``member`` → 403 ``permission_denied``."""
    anon_response = await anon.get(f"{WD}/documents/abc/source-link")
    member_response = await member.get(f"{WD}/documents/abc/source-link")

    assert anon_response.status_code == UNAUTHORIZED, anon_response.text
    assert anon_response.json()["error"]["code"] == "unauthorized"
    assert member_response.status_code == FORBIDDEN, member_response.text
    assert member_response.json()["error"]["code"] == "permission_denied"
