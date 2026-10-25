"""`GET /api/documents/link` — AG-19 (kontrakt E4-3a §3 p. 1-5, 03 §5 A11, 09 §9).

Kształt `data` jest camelCase (`webUrl`, `name`, `path`, `driveName`), 404 zawsze niesie
`code` (`no_mapping` / `item_not_found`), a cache LRU/TTL pamięta także wyniki negatywne.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import MappingRow
from app.db.uow import transaction
from tests.contract.hub_compat.sharepoint.conftest import (
    CONTAINER_D1,
    CONTAINER_D1_NAME,
)
from tests.fakes.integrations import make_item

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

OK = 200
BAD_REQUEST = 400
NOT_FOUND = 404
UPSTREAM_ERROR = 502
STALE_MS = 0  # mapping sprzed epoki — zawsze starszy niż 24 h (kontrakt §3 p. 3)
ITEM_ID = "i1"
WEB_URL = "https://contoso.sharepoint.com/sites/eng/Dokumenty/a.txt"
LINK_KEYS = {"webUrl", "name", "path", "driveName"}
NO_MAPPING = {"error": "No SharePoint mapping for this document", "code": "no_mapping"}
ITEM_GONE = {"error": "Item no longer exists in SharePoint", "code": "item_not_found"}


async def seed_mapping(  # noqa: PLR0913 — skrót testowy z domyślnymi polami mapowania
    sm: async_sessionmaker[AsyncSession],
    integration_id: int,
    *,
    document_id: str,
    updated_at: int = STALE_MS,
    web_url: str | None = None,
    path: str | None = None,
    name: str | None = None,
) -> None:
    """Kontener `d1` i mapowanie dokumentu; domyślnie bez `web_url`/`path` (starsze niż 24 h)."""
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
                name=name,
                path=path,
                web_url=web_url,
                last_status="ok",
                last_error=None,
                updated_at=updated_at,
            ),
        )


async def test_ag19_link_returns_exact_shape(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-19: 200 z `{webUrl, name, path, driveName}` z konektora (mapping starszy niż 24 h)."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(sm, created["id"], document_id=document_id)
    connector.link_item = make_item(
        container_id=CONTAINER_D1,
        item_id=ITEM_ID,
        name="a.txt",
        path="/a.txt",
        web_url=WEB_URL,
    )

    response = await svc.get(f"{prefix}/api/documents/link", params={"documentId": document_id})

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert set(data) == LINK_KEYS
    assert data == {
        "webUrl": WEB_URL,
        "name": "a.txt",
        "path": "/a.txt",
        "driveName": CONTAINER_D1_NAME,
    }
    assert connector.link_calls == [(CONTAINER_D1, ITEM_ID)]


async def test_ag19_fresh_mapping_skips_connector(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
    container: Container,
) -> None:
    """AG-19/§3 p. 3: świeży mapping (z `web_url`) nie woła konektora."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(
        sm,
        created["id"],
        document_id=document_id,
        updated_at=container.clock.now_ms(),
        web_url=WEB_URL,
        path="/a.txt",
        name="a.txt",
    )

    response = await svc.get(f"{prefix}/api/documents/link", params={"documentId": document_id})

    assert response.status_code == OK, response.text
    assert response.json()["data"] == {
        "webUrl": WEB_URL,
        "name": "a.txt",
        "path": "/a.txt",
        "driveName": CONTAINER_D1_NAME,
    }
    assert connector.link_calls == []


async def test_ag19_no_mapping(svc: Any, prefix: str, connector: Any) -> None:
    """AG-19: dokument bez mapowania → 404 `{error, code: no_mapping}` (A11)."""
    response = await svc.get(
        f"{prefix}/api/documents/link", params={"documentId": uuid.uuid4().hex}
    )

    assert response.status_code == NOT_FOUND, response.text
    assert response.json() == NO_MAPPING


async def test_ag19_item_not_found(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-19: element zniknął z SharePoint (`web_link` → `None`) → 404 `item_not_found`."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(sm, created["id"], document_id=document_id)

    response = await svc.get(f"{prefix}/api/documents/link", params={"documentId": document_id})

    assert response.status_code == NOT_FOUND, response.text
    assert response.json() == ITEM_GONE


async def test_ag19_upstream_error_is_502(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-19: błąd konektora inny niż brak elementu → 502 `{error}` bez `code`."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(sm, created["id"], document_id=document_id)
    connector.link_error = RuntimeError("graph down")

    response = await svc.get(f"{prefix}/api/documents/link", params={"documentId": document_id})

    assert response.status_code == UPSTREAM_ERROR, response.text
    assert response.json() == {"error": "graph down"}


async def test_ag19_requires_document_id(svc: Any, prefix: str, connector: Any) -> None:
    """AG-19/§4: brak `documentId` (albo pusty) → 400 „documentId is required”."""
    missing = await svc.get(f"{prefix}/api/documents/link")
    empty = await svc.get(f"{prefix}/api/documents/link", params={"documentId": ""})

    assert missing.status_code == BAD_REQUEST
    assert missing.json() == {"error": "documentId is required"}
    assert empty.status_code == BAD_REQUEST
    assert empty.json() == {"error": "documentId is required"}


async def test_ag19_success_is_cached(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-19/§3 p. 1: drugie żądanie o ten sam dokument nie woła `web_link` (cache dodatni)."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(sm, created["id"], document_id=document_id)
    connector.link_item = make_item(
        container_id=CONTAINER_D1, item_id=ITEM_ID, name="a.txt", path="/a.txt", web_url=WEB_URL
    )
    params = {"documentId": document_id}

    first = await svc.get(f"{prefix}/api/documents/link", params=params)
    second = await svc.get(f"{prefix}/api/documents/link", params=params)

    assert first.status_code == OK
    assert second.json() == first.json()
    assert connector.link_calls == [(CONTAINER_D1, ITEM_ID)]


async def test_ag19_negative_result_is_cached(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-19/§3 p. 1: wynik negatywny też trafia do cache — drugi raz nie ma odpytywania."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    document_id = uuid.uuid4().hex
    await seed_mapping(sm, created["id"], document_id=document_id)
    params = {"documentId": document_id}

    first = await svc.get(f"{prefix}/api/documents/link", params=params)
    connector.link_item = make_item(
        container_id=CONTAINER_D1, item_id=ITEM_ID, name="a.txt", path="/a.txt", web_url=WEB_URL
    )
    second = await svc.get(f"{prefix}/api/documents/link", params=params)

    assert first.status_code == NOT_FOUND
    assert first.json() == ITEM_GONE
    assert second.status_code == NOT_FOUND
    assert second.json() == ITEM_GONE
    assert connector.link_calls == [(CONTAINER_D1, ITEM_ID)]
