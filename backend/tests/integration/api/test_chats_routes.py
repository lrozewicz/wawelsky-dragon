"""Testy HTTP tras /api/v1/chats (brief T2c; CONTRACT C6, R2, R4)."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.domain.policy import Principal
from app.main import create_app
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

# Stałe statusu i długości (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_HTTP_OK = 200
_MODEL_ID_LEN = 32


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (kopia z tests/integration/chat/conftest.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na życiu kontenerze (bez lifespan) z nadpisanym uwierzytelnianiem."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (wzorzec test_completions_routes.py)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create(
    client: httpx.AsyncClient, name: str = "wd", dataset_ids: list[str] | None = None
) -> dict[str, Any]:
    """Tworzy czat przez API i zwraca kopertę data."""
    payload: dict[str, Any] = {"name": name, "dataset_ids": dataset_ids or []}
    resp = await client.post("/api/v1/chats", json=payload)
    assert resp.status_code == _HTTP_OK
    body = resp.json()
    assert body["code"] == RetCode.SUCCESS
    return body["data"]


async def test_create_duplicate_and_list(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST: llm_id = 32 hex = tenant_llm_id, system pusty bez datasetów; duplikat → 102."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        data = await _create(client)
        assert len(data["llm_id"]) == _MODEL_ID_LEN
        assert data["llm_id"] == data["tenant_llm_id"]
        assert data["prompt_config"]["system"] == ""
        duplicated = await client.post("/api/v1/chats", json={"name": "wd", "dataset_ids": []})
        assert duplicated.json()["code"] == RetCode.DATA_ERROR
        assert duplicated.json()["message"] == "duplicated chat name in creating chat"
        listing = (await client.get("/api/v1/chats?page=1&page_size=30")).json()
        assert listing["code"] == RetCode.SUCCESS
        assert listing["data"]["total"] == 1
        assert listing["data"]["chats"][0]["id"] == data["id"]
        assert listing["data"]["chats"][0]["nickname"] == "seed"


async def test_get_found_missing_and_stranger(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """GET /chats/{id}: właściciel → 0; nieistniejący → 102; obcy → 109.

    Obcy czat: upstream ``get_chat`` (chat_api.py:571-591) nie oddaje szczegółu komuś, kto
    go nie ma na liście tenantów → ``no authorization`` (złoto errors_access--25.json).
    """
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        data = await _create(client)
        got = await client.get(f"/api/v1/chats/{data['id']}")
        assert got.json()["code"] == RetCode.SUCCESS
        missing = await client.get("/api/v1/chats/brak")
        assert missing.json()["code"] == RetCode.DATA_ERROR
        assert missing.json()["message"] == "Chat not found!"
    async with _client(_app(container, principal_for(uuid.uuid4().hex))) as stranger:
        denied = await stranger.get(f"/api/v1/chats/{data['id']}")
    assert denied.json() == {
        "code": RetCode.AUTHENTICATION_ERROR,
        "message": "no authorization",
        "data": False,
    }


async def test_put_then_patch_merges_llm_setting(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT zastępuje llm_setting, PATCH dokleja (C6: merge=False potem merge=True)."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        data = await _create(client)
        put = await client.put(
            f"/api/v1/chats/{data['id']}", json={"llm_setting": {"temperature": 0.1}}
        )
        assert put.json()["code"] == RetCode.SUCCESS
        patched = await client.patch(
            f"/api/v1/chats/{data['id']}", json={"llm_setting": {"top_p": 0.5}}
        )
    assert patched.json()["data"]["llm_setting"] == {"temperature": 0.1, "top_p": 0.5}


async def test_patch_and_delete_stranger_denied_owner_ok(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PATCH jako obcy → 109 „no authorization" (get_json_result); DELETE obcego → 108.

    PATCH cudzego czatu u upstream to ``_ensure_owned_chat`` → koperta 109 ``data: false``
    (złoto errors_access--27.json); DELETE czatu zostaje na polityce (108).
    """
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        data = await _create(client)
    stranger_app = _app(container, principal_for(uuid.uuid4().hex))
    async with _client(stranger_app) as stranger:
        patched = await stranger.patch(f"/api/v1/chats/{data['id']}", json={"name": "x"})
        assert patched.json() == {
            "code": RetCode.AUTHENTICATION_ERROR,
            "message": "no authorization",
            "data": False,
        }
        deleted = await stranger.delete(f"/api/v1/chats/{data['id']}")
        assert deleted.json()["code"] == RetCode.PERMISSION_ERROR
    async with _client(_app(container, principal)) as client:
        deleted = await client.delete(f"/api/v1/chats/{data['id']}")
    assert deleted.json() == {"code": RetCode.SUCCESS, "message": "success", "data": True}


async def test_put_patch_missing_and_duplicated_name(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT/PATCH: brak czatu → 109 ``data: false``; zajęta nazwa → 102 bez ``data`` (E2-1).

    Złoto chat_extras--25.json (109) i chat_extras--23.json (102 bez klucza ``data`` —
    upstream ``get_data_error_result``).
    """
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        first = await _create(client, name="wd_rec_e2_chat_extras_chat")
        await _create(client, name="wd_rec_e2_chat_extras_dup")
        for method in ("PUT", "PATCH"):
            missing = await client.request(
                method, f"/api/v1/chats/{'0' * _MODEL_ID_LEN}", json={"name": "brak"}
            )
            assert missing.json() == {
                "code": RetCode.AUTHENTICATION_ERROR,
                "message": "no authorization",
                "data": False,
            }
            duplicated = await client.request(
                method,
                f"/api/v1/chats/{first['id']}",
                json={"name": "wd_rec_e2_chat_extras_dup"},
            )
            assert duplicated.json() == {
                "code": RetCode.DATA_ERROR,
                "message": "duplicated chat name",
            }


async def test_delete_many_cases(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DELETE /chats (R4): {} → {}; częściowy → success_count+errors; sam brak → 102; pojedynczy."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        empty = await client.request("DELETE", "/api/v1/chats", json={})
        assert empty.json()["data"] == {}
        first = await _create(client, name="a1")
        partial = await client.request(
            "DELETE", "/api/v1/chats", json={"ids": [first["id"], "brak"]}
        )
        assert partial.json()["data"] == {
            "success_count": 1,
            "errors": ["Chat(brak) not found."],
        }
        missing = await client.request("DELETE", "/api/v1/chats", json={"ids": ["brak"]})
        # 102 bez klucza ``data`` (upstream ``get_data_error_result``; złoto errors_access--52).
        assert missing.json() == {"code": RetCode.DATA_ERROR, "message": "Chat(brak) not found."}
        second = await _create(client, name="a2")
        single = await client.request("DELETE", "/api/v1/chats", json={"ids": [second["id"]]})
    assert single.json()["data"] == {"success_count": 1}


async def test_list_invalid_orderby(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """GET /chats?orderby=id → 101 z komunikatem upstream (:521)."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        resp = await client.get("/api/v1/chats?orderby=id")
    assert resp.json()["code"] == RetCode.ARGUMENT_ERROR
    assert resp.json()["message"] == "invalid orderby field: id"
