"""Testy HTTP tras /api/v1/files* (brief T5b; CONTRACT E4-5a §D1, §D3, §D5).

Klucze odpowiedzi, kody i komunikaty porównywane ze złotem v0.27.2
(``tests/contract/golden/v0.27.2/files*``) — koperta sukcesu WD dokłada ``message``, co
komparator złota toleruje przy ``code 0`` (Q2, K11 §5 p. 4). Trasy ``link-to-datasets``
zależą od T4, więc ich testy są poza zakresem tego zadania (T6).
"""

import uuid
from collections.abc import AsyncIterator, Sequence
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

_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401

# Klucze prezenterów (CONTRACT §D5; złoto files--02/--04/--05/--12).
_CREATED_KEYS = {
    "created_by",
    "id",
    "location",
    "name",
    "parent_id",
    "size",
    "source_type",
    "tenant_id",
    "type",
}
_PARENT_KEYS = {
    "create_date",
    "create_time",
    "created_by",
    "id",
    "location",
    "name",
    "parent_id",
    "size",
    "source_type",
    "tenant_id",
    "type",
    "update_date",
    "update_time",
}
_NO_AUTHORIZATION = "no authorization"
_FILE_BYTES = b"Wawelski Dragon - menedzer plikow (E4-5a T5b).\n"
_MISSING_FILE = uuid.uuid4().hex


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (kopia z tests/integration/api/test_searches_routes.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal | None = None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` zostawia prawdziwe uwierzytelnianie."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (wzorzec test_chats_routes.py)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create_folder(client: httpx.AsyncClient, name: str, parent_id: str | None = None) -> str:
    """POST /files (JSON) z asercją sukcesu; zwraca id folderu."""
    payload: dict[str, Any] = {"name": name, "type": "folder"}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = await client.post("/api/v1/files", json=payload)
    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    assert set(body["data"]) == _CREATED_KEYS
    assert body["data"]["type"] == "folder"
    assert body["data"]["location"] == ""
    return body["data"]["id"]


async def _upload(
    client: httpx.AsyncClient,
    filename: str = "ragflow_intro.txt",
    *,
    content: bytes = _FILE_BYTES,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """POST /files (multipart) z asercją sukcesu; zwraca element ``data`` (złoto files--04)."""
    data = {"parent_id": parent_id} if parent_id is not None else None
    response = await client.post("/api/v1/files", files={"file": (filename, content)}, data=data)
    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    item = body["data"][0]
    assert set(item) == _CREATED_KEYS
    return item


async def _listing(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    """GET /files z asercją sukcesu; zwraca ``data``."""
    response = await client.get("/api/v1/files", params=params)
    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    return body["data"]


def _find(files: Sequence[dict[str, Any]], item_id: str) -> dict[str, Any]:
    """Element listingu po id (kolejność sortowania nie jest przedmiotem testu)."""
    found = [item for item in files if item["id"] == item_id]
    assert len(found) == 1, files
    return found[0]


async def test_create_folder_duplicate_and_listing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST folder → 9 kluczy; duplikat nazwy → 102; listing ma ``parent_folder`` i ``total``."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        folder_id = await _create_folder(client, "wd_e4a_folder")
        duplicated = await client.post(
            "/api/v1/files", json={"name": "wd_e4a_folder", "type": "folder"}
        )
        data = await _listing(client)

    assert duplicated.status_code == _HTTP_OK
    assert duplicated.json() == {
        "code": RetCode.DATA_ERROR,
        "message": "Duplicated folder name in the same folder.",
    }
    item = _find(data["files"], folder_id)
    assert item["has_child_folder"] is False
    assert (item["name"], item["parent_id"], item["kbs_info"]) == (
        "wd_e4a_folder",
        data["parent_folder"]["id"],
        [],
    )
    assert data["parent_folder"]["name"] == "/"
    assert data["total"] == 1


async def test_upload_then_list_and_download_bytes(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Upload → wiersz w listingu bez ``has_child_folder``; pobranie oddaje te same bajty."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        created = await _upload(client, "wd_e4a_dokument.txt")
        data = await _listing(client)
        downloaded = await client.get(f"/api/v1/files/{created['id']}")

    assert created["name"] == "wd_e4a_dokument.txt"
    assert created["location"] == created["name"]
    assert created["size"] == len(_FILE_BYTES)
    assert created["type"] == "doc"
    item = _find(data["files"], created["id"])
    assert set(item) == _PARENT_KEYS | {"kbs_info"}
    assert item["kbs_info"] == []
    assert downloaded.status_code == _HTTP_OK
    assert downloaded.content == _FILE_BYTES
    # Komparator złota porównuje typ bez parametru ``charset`` (K11 §5 p. 4; złoto files--09).
    assert downloaded.headers["content-type"].split(";")[0] == "text/plain"
    assert downloaded.headers["content-disposition"].startswith("attachment; filename=")


async def test_move_rename_parent_and_ancestors(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Move do podfolderu i rename; ``ancestors`` to ścieżka ``[plik, …, root]`` (§D1.3)."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        folder_id = await _create_folder(client, "wd_e4a_katalog")
        sub_id = await _create_folder(client, "wd_e4a_podkatalog", folder_id)
        created = await _upload(client, "wd_e4a_przenoszony.txt")
        moved = await client.post(
            "/api/v1/files/move",
            json={"src_file_ids": [created["id"]], "dest_file_id": sub_id},
        )
        in_sub = await _listing(client, parent_id=sub_id)
        parent = await client.get(f"/api/v1/files/{created['id']}/parent")
        renamed = await client.post(
            "/api/v1/files/move",
            json={"src_file_ids": [created["id"]], "new_name": "wd_e4a_zmieniony.txt"},
        )
        ancestors = await client.get(f"/api/v1/files/{created['id']}/ancestors")

    assert moved.json() == {"code": RetCode.SUCCESS, "message": "success", "data": True}
    assert _find(in_sub["files"], created["id"])["name"] == "wd_e4a_przenoszony.txt"
    assert parent.json()["data"]["parent_folder"]["id"] == sub_id
    assert set(parent.json()["data"]["parent_folder"]) == _PARENT_KEYS
    assert renamed.json()["data"] is True
    path = ancestors.json()["data"]["parent_folders"]
    assert [row["id"] for row in path] == [created["id"], sub_id, folder_id, path[-1]["id"]]
    # §D1.3: ``location`` odpowiedzi = bieżąca nazwa pliku (WD nie pamięta pierwotnej — odchyłka).
    assert path[0]["name"] == "wd_e4a_zmieniony.txt"
    assert path[0]["location"] == path[0]["name"]
    assert path[-1]["name"] == "/"
    assert path[-1]["parent_id"] == path[-1]["id"]


async def test_delete_success_and_missing_id(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DELETE własnego pliku → ``success_count``; brakujący id → 102 z listą ``errors``."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        created = await _upload(client, "wd_e4a_do_usuniecia.txt")
        deleted = await client.request("DELETE", "/api/v1/files", json={"ids": [created["id"]]})
        missing = await client.request("DELETE", "/api/v1/files", json={"ids": [_MISSING_FILE]})
        data = await _listing(client)

    assert deleted.json() == {
        "code": RetCode.SUCCESS,
        "message": "success",
        "data": {"success_count": 1},
    }
    assert missing.json() == {
        "code": RetCode.DATA_ERROR,
        "data": {"errors": [f"File or Folder not found: {_MISSING_FILE}"], "success_count": 0},
        "message": "Deleted files failed with 1 errors",
    }
    assert data["files"] == []


async def test_foreign_file_refused_without_data(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudzy plik: GET/parent/ancestors/move → 102 ``no authorization`` bez ``data`` (§D1.8)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    async with _client(_app(container, alice)) as client:
        created = await _upload(client, "wd_e4a_cudzy.txt")
    bob = principal_for(await seed_user(sm))
    async with _client(_app(container, bob)) as stranger:
        downloaded = await stranger.get(f"/api/v1/files/{created['id']}")
        parent = await stranger.get(f"/api/v1/files/{created['id']}/parent")
        ancestors = await stranger.get(f"/api/v1/files/{created['id']}/ancestors")
        moved = await stranger.post(
            "/api/v1/files/move",
            json={"src_file_ids": [created["id"]], "new_name": "wd_e4a_przejete.txt"},
        )
        deleted = await stranger.request("DELETE", "/api/v1/files", json={"ids": [created["id"]]})

    refused = {"code": RetCode.DATA_ERROR, "message": _NO_AUTHORIZATION}
    for response in (downloaded, parent, ancestors, moved):
        assert response.status_code == _HTTP_OK, response.text
        assert response.json() == refused, response.text
    # DELETE nie rzuca odmowy — zwraca błąd per id w ``errors`` (§D1.8).
    assert deleted.json() == {
        "code": RetCode.DATA_ERROR,
        "data": {
            "errors": [f"No authorization for file {created['id']}"],
            "success_count": 0,
        },
        "message": "Deleted files failed with 1 errors",
    }
    async with _client(_app(container, alice)) as client:
        data = await _listing(client)
    assert _find(data["files"], created["id"])["name"] == "wd_e4a_cudzy.txt"


async def test_missing_authorization_header_is_401(container: Container) -> None:
    """Brak nagłówka ``Authorization`` → HTTP 401 (K3; złoto files--32/--33)."""
    async with _client(_app(container)) as anonymous:
        response = await anonymous.get("/api/v1/files")

    assert response.status_code == _HTTP_UNAUTHORIZED
    assert response.json()["code"] == _HTTP_UNAUTHORIZED


async def test_invalid_json_body_is_101(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Puste ciało JSON ``POST /files`` → 101 (port ``CreateFolderReq``, normalize/files.py)."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        response = await client.post("/api/v1/files", json={})

    assert response.status_code == _HTTP_OK
    assert response.json()["code"] == RetCode.ARGUMENT_ERROR
