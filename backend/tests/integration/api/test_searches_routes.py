"""Testy HTTP tras /api/v1/searches (brief T2b; CONTRACT E4-4a §D5-§D6).

Klucze odpowiedzi, kody błędów i komunikaty porównywane dosłownie ze złotem v0.27.2
(`tests/contract/golden/v0.27.2/searches*`). Dwaj użytkownicy: właściciel i obcy.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME, TIME_MS
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

# Stałe do porównań (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_HTTP_OK = 200
_OWN_SEARCHES = 3  # liczba wyszukiwarek właściciela w teście listy
_PAGE_SIZE = 2  # rozmiar strony w teście paginacji
_TOP_K = 8  # wartość ``top_k`` wstawiana przez ``PUT``

# Klucze z CONTRACT E4-4a §D5 (kolejność w złocie alfabetyczna — porównujemy zbiory).
_LIST_ITEM_KEYS = {
    "avatar",
    "create_time",
    "created_by",
    "description",
    "id",
    "name",
    "nickname",
    "status",
    "tenant_avatar",
    "tenant_id",
    "update_time",
}
_DETAIL_KEYS = {
    "avatar",
    "created_by",
    "description",
    "id",
    "name",
    "search_config",
    "tenant_id",
    "update_time",
}
_FULL_KEYS = {
    "avatar",
    "create_date",
    "create_time",
    "created_by",
    "description",
    "id",
    "name",
    "search_config",
    "status",
    "tenant_id",
    "update_date",
    "update_time",
}
_NO_PERMISSION = "Has no permission for this operation."
_NO_AUTHORIZATION = "no authorization"


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (kopia z tests/integration/api/test_chats_routes.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na życiu kontenerze (bez lifespan) z nadpisanym uwierzytelnianiem."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (wzorzec test_chats_routes.py)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _seed_dataset(
    sm: async_sessionmaker[AsyncSession], tenant_id: str, *, name: str = "Korpus"
) -> str:
    """Wstawia dataset właściciela; zwraca id (FK datasets.tenant_id → users)."""
    dataset_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO datasets (id, tenant_id, created_by, name, permission,"
                " embedding_model, embedding_dim, create_time, create_date, update_time,"
                " update_date)"
                " VALUES (:id, :tenant, :tenant, :name, 'me', 'fake-embed-1024', 1024,"
                " :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": dataset_id,
                "tenant": tenant_id,
                "name": name,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
    return dataset_id


async def _create(
    client: httpx.AsyncClient, name: str = "wd", *, search_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Tworzy wyszukiwarkę przez API i zwraca kopertę data."""
    payload: dict[str, Any] = {"name": name}
    if search_config is not None:
        payload["search_config"] = search_config
    resp = await client.post("/api/v1/searches", json=payload)
    assert resp.status_code == _HTTP_OK
    body = resp.json()
    assert body["code"] == RetCode.SUCCESS
    return body["data"]


async def test_create_list_and_detail(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST → ``search_id``; lista i szczegół mają klucze §D5, ``kb_ids`` z wiązań (§D1)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    dataset_id = await _seed_dataset(sm, alice_id)
    async with _client(_app(container, alice)) as client:
        created = await client.post(
            "/api/v1/searches",
            json={
                "name": "wd_e4a_lista",
                "description": "opis",
                "search_config": {"kb_ids": [dataset_id], "chat_id": "c" * 32},
            },
        )
        assert created.json()["code"] == RetCode.SUCCESS
        assert set(created.json()["data"]) == {"search_id"}
        search_id = created.json()["data"]["search_id"]
        listing = (await client.get("/api/v1/searches")).json()
        detail = (await client.get(f"/api/v1/searches/{search_id}")).json()

    assert listing["code"] == RetCode.SUCCESS
    assert listing["data"]["total"] == 1
    item = listing["data"]["search_apps"][0]
    assert set(item) == _LIST_ITEM_KEYS
    assert "search_config" not in item
    assert (item["id"], item["name"], item["nickname"]) == (search_id, "wd_e4a_lista", "seed")
    assert detail["code"] == RetCode.SUCCESS
    assert set(detail["data"]) == _DETAIL_KEYS
    assert detail["data"]["search_config"]["kb_ids"] == [dataset_id]
    assert detail["data"]["search_config"]["chat_id"] == "c" * 32
    assert detail["data"]["description"] == "opis"


async def test_put_full_row_and_validation_errors(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT: pełny wiersz §D5; zajęta nazwa → 102; ``search_config`` nie-obiekt → 102."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        first = await _create(client, "wd_e4a_put_a")
        await _create(client, "wd_e4a_put_b")
        updated = await client.put(
            f"/api/v1/searches/{first['search_id']}",
            json={
                "name": "wd_e4a_put_a",
                "search_config": {"top_k": _TOP_K},
                "description": "nowy",
            },
        )
        duplicated = await client.put(
            f"/api/v1/searches/{first['search_id']}",
            json={"name": "wd_e4a_put_b", "search_config": {}},
        )
        bad_config = await client.put(
            f"/api/v1/searches/{first['search_id']}",
            json={"name": "wd_e4a_put_a", "search_config": "x"},
        )

    assert updated.json()["code"] == RetCode.SUCCESS
    assert set(updated.json()["data"]) == _FULL_KEYS
    assert updated.json()["data"]["description"] == "nowy"
    assert updated.json()["data"]["search_config"]["top_k"] == _TOP_K
    assert duplicated.json() == {"code": RetCode.DATA_ERROR, "message": "Duplicated search name."}
    assert bad_config.json() == {
        "code": RetCode.DATA_ERROR,
        "message": "search_config must be a JSON object",
    }


async def test_missing_and_empty_name_arguments(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak ``name`` → 101 z ``data:null``; pusta nazwa → 102 bez ``data`` (złoto --06/--07)."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        missing = await client.post("/api/v1/searches", json={"description": "bez nazwy"})
        empty = await client.post("/api/v1/searches", json={"name": ""})
        data = await _create(client, "wd_e4a_brak")
        put_missing = await client.put(f"/api/v1/searches/{data['search_id']}", json={})

    assert missing.json() == {
        "code": RetCode.ARGUMENT_ERROR,
        "data": None,
        "message": "required argument are missing: name; ",
    }
    assert empty.json() == {"code": RetCode.DATA_ERROR, "message": "Search name can't be empty."}
    assert put_missing.json() == {
        "code": RetCode.ARGUMENT_ERROR,
        "data": None,
        "message": "required argument are missing: name,search_config; ",
    }


async def test_delete_then_get_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DELETE → ``data: true``; po usunięciu GET → 103 ``data: false`` (złoto --32/--33)."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        data = await _create(client, "wd_e4a_usun")
        deleted = await client.delete(f"/api/v1/searches/{data['search_id']}")
        gone = await client.get(f"/api/v1/searches/{data['search_id']}")

    assert deleted.json() == {"code": RetCode.SUCCESS, "message": "success", "data": True}
    assert gone.json() == {
        "code": RetCode.OPERATING_ERROR,
        "data": False,
        "message": _NO_PERMISSION,
    }


async def test_foreign_search_denied_and_resource_untouched(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Obcy: GET → 103, PUT/DELETE → 109 ``data: false``; zasób zostaje nietknięty (§D5)."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        data = await _create(client, "wd_e4a_cudza")
    outsider = _app(container, principal_for(uuid.uuid4().hex))
    async with _client(outsider) as stranger:
        got = await stranger.get(f"/api/v1/searches/{data['search_id']}")
        put = await stranger.put(
            f"/api/v1/searches/{data['search_id']}",
            json={"name": "przejeta", "search_config": {}},
        )
        deleted = await stranger.delete(f"/api/v1/searches/{data['search_id']}")

    assert got.json() == {
        "code": RetCode.OPERATING_ERROR,
        "data": False,
        "message": _NO_PERMISSION,
    }
    assert put.json() == {
        "code": RetCode.AUTHENTICATION_ERROR,
        "data": False,
        "message": _NO_AUTHORIZATION,
    }
    assert deleted.json() == {
        "code": RetCode.AUTHENTICATION_ERROR,
        "data": False,
        "message": _NO_AUTHORIZATION,
    }
    async with _client(_app(container, alice)) as client:
        kept = (await client.get(f"/api/v1/searches/{data['search_id']}")).json()
    assert kept["code"] == RetCode.SUCCESS
    assert kept["data"]["name"] == "wd_e4a_cudza"


async def test_missing_search_put_and_delete_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT/DELETE nieistniejącej wyszukiwarki → 109 (złoto searches--18/--31)."""
    alice = principal_for(await seed_user(sm))
    missing_id = uuid.uuid4().hex
    async with _client(_app(container, alice)) as client:
        put = await client.put(
            f"/api/v1/searches/{missing_id}", json={"name": "brak", "search_config": {}}
        )
        deleted = await client.delete(f"/api/v1/searches/{missing_id}")

    denied = {"code": RetCode.AUTHENTICATION_ERROR, "data": False, "message": _NO_AUTHORIZATION}
    assert put.json() == denied
    assert deleted.json() == denied


async def test_list_owner_ids_orderby_and_pagination(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``owner_ids`` bez właściciela → pusto; nieznane ``orderby`` → 200; paginacja działa."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    bob_id = await seed_user(sm)
    async with _client(_app(container, alice)) as client:
        for name in ("wd_e4a_p1", "wd_e4a_p2", "wd_e4a_p3"):
            await _create(client, name)
        foreign = (await client.get(f"/api/v1/searches?owner_ids={bob_id}")).json()
        own = (await client.get(f"/api/v1/searches?owner_ids={alice_id}")).json()
        unknown = (await client.get("/api/v1/searches?orderby=bzdura&desc=false")).json()
        page = (await client.get("/api/v1/searches?page=1&page_size=2")).json()

    assert foreign == {
        "code": RetCode.SUCCESS,
        "message": "success",
        "data": {"search_apps": [], "total": 0},
    }
    assert own["data"]["total"] == _OWN_SEARCHES
    assert unknown["code"] == RetCode.SUCCESS
    assert page["data"]["total"] == _OWN_SEARCHES
    assert len(page["data"]["search_apps"]) == _PAGE_SIZE
