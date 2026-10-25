"""Testy HTTP tras legacy ``/api/v1/file/*`` w profilu 0.27 (E4-5b T1; CONTRACT §D0, §D3).

Kształty, kody i komunikaty dosłownie ze złota v0.27.2 (``tests/contract/golden/v0.27.2/file__*``).
Profil domyślny to ``ragflow_0_27`` (podmiot ``auth_kind="jwt"``), więc trasy wołają funkcje
``routes/files.py`` (E4-5a). Trasy legacy nie mają wpisu w OpenAPI (``include_in_schema=False``),
a ich odpowiedzi to ta sama koperta co ``/files`` (komparator złota toleruje dodatkowe ``message``
przy ``code 0``, Q2). Cudzy zasób w 0.27: 102 ``no authorization`` (``files_*`` w ``PROFILES``).
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
from app.db.repositories import models as models_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.datasets import DatasetService
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME_MS
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401

# Klucze prezenterów (CONTRACT §D3; złoto file_legacy--02/--04/--05/--12).
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
_UPLOAD_INFO_KEYS = {
    "created_at",
    "created_by",
    "extension",
    "id",
    "mime_type",
    "name",
    "preview_url",
    "size",
}
_NO_AUTHORIZATION = "no authorization"
_MSG_FILE_ID_REQUIRED = "`file_id` query parameter is required"
_FILE_BYTES = b"Wawelski Dragon - legacy menedzer plikow (E4-5b T1).\n"
_MISSING_FILE = uuid.uuid4().hex
# Root po utworzeniu folderu i uploadzie: dwa widoczne wiersze (folder + plik).
_ROOT_ITEMS = 2


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy + wymiar modelu embedding (``/file/convert`` linkuje do datasetu)."""
    instance = await make_container(migrated_db, tmp_path)
    async with transaction(instance.sessionmaker) as session:
        await models_repo.set_dimension_if_null(session, "e" * 32, 1024, TIME_MS)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal | None = None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` zostawia prawdziwe uwierzytelnianie."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (wzorzec test_files_routes.py)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create_folder(client: httpx.AsyncClient, name: str, parent_id: str | None = None) -> str:
    """POST /file/create (JSON) z asercją sukcesu; zwraca id folderu."""
    payload: dict[str, Any] = {"name": name, "type": "folder"}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = await client.post("/api/v1/file/create", json=payload)
    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    assert set(body["data"]) == _CREATED_KEYS
    assert body["data"]["location"] == ""
    return body["data"]["id"]


async def _upload(
    client: httpx.AsyncClient,
    filename: str = "wd_e4b_legacy.txt",
    *,
    content: bytes = _FILE_BYTES,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """POST /file/upload (multipart) z asercją sukcesu; zwraca element ``data`` (złoto ``--04``)."""
    data = {"parent_id": parent_id} if parent_id is not None else None
    response = await client.post(
        "/api/v1/file/upload", files={"file": (filename, content)}, data=data
    )
    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    item = body["data"][0]
    assert set(item) == _CREATED_KEYS
    return item


async def _listing(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    """GET /file/list z asercją sukcesu; zwraca ``data`` (klucze listingu)."""
    response = await client.get("/api/v1/file/list", params=params)
    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    assert set(body["data"]) == {"files", "parent_folder", "total"}
    return body["data"]


async def _dataset(container: Container, principal: Principal, name: str) -> str:
    """Dataset principala przez usługę; zwraca id (dla ``/file/convert``)."""
    return (await DatasetService(container).create(principal, name=name)).id


def _find(files: Sequence[dict[str, Any]], item_id: str) -> dict[str, Any]:
    """Element listingu po id (kolejność sortowania nie jest przedmiotem testu)."""
    found = [item for item in files if item["id"] == item_id]
    assert len(found) == 1, files
    return found[0]


async def test_create_upload_list_root_and_download(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """create/upload/list/root_folder/get: 12 tras z §D3 — 5 tu, pełne klucze odpowiedzi."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        folder_id = await _create_folder(client, "wd_e4b_folder")
        created = await _upload(client, "wd_e4b_dokument.txt")
        listed = await _listing(client)
        root = await client.get("/api/v1/file/root_folder")
        downloaded = await client.get(f"/api/v1/file/get/{created['id']}")

    assert created["name"] == "wd_e4b_dokument.txt"
    assert created["size"] == len(_FILE_BYTES)
    assert created["type"] == "doc"
    assert _find(listed["files"], folder_id)["name"] == "wd_e4b_folder"
    assert listed["parent_folder"]["name"] == "/"
    assert listed["total"] == _ROOT_ITEMS
    assert root.status_code == _HTTP_OK, root.text
    root_body = root.json()
    assert root_body["code"] == RetCode.SUCCESS, root_body
    assert set(root_body["data"]) == {"files", "parent_folder", "total"}
    assert root_body["data"]["total"] == _ROOT_ITEMS
    assert downloaded.status_code == _HTTP_OK
    assert downloaded.content == _FILE_BYTES


async def test_parent_all_parent_move_and_rename(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """parent_folder/all_parent_folder/mv/rename — 4 trasy z §D3 (kształty ze złota)."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        folder_id = await _create_folder(client, "wd_e4b_katalog")
        sub_id = await _create_folder(client, "wd_e4b_podkatalog", folder_id)
        created = await _upload(client, "wd_e4b_przenoszony.txt")
        moved = await client.post(
            "/api/v1/file/mv",
            json={"src_file_ids": [created["id"]], "dest_file_id": sub_id},
        )
        parent = await client.get("/api/v1/file/parent_folder", params={"file_id": created["id"]})
        ancestors = await client.get(
            "/api/v1/file/all_parent_folder", params={"file_id": created["id"]}
        )
        renamed = await client.post(
            "/api/v1/file/rename",
            json={"file_id": created["id"], "name": "wd_e4b_zmieniony.txt"},
        )

    assert moved.json() == {"code": RetCode.SUCCESS, "message": "success", "data": True}
    assert parent.json()["data"]["parent_folder"]["id"] == sub_id
    assert set(parent.json()["data"]["parent_folder"]) == _PARENT_KEYS
    path = ancestors.json()["data"]["parent_folders"]
    assert [row["id"] for row in path] == [created["id"], sub_id, folder_id, path[-1]["id"]]
    assert path[-1]["name"] == "/"
    assert renamed.json() == {"code": RetCode.SUCCESS, "message": "success", "data": True}


async def test_convert_links_file_to_dataset(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """convert: ``{code:0, data:true, message:success}`` i dokument w liście datasetu (§D3)."""
    alice = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "wd_e4b_legacy_ds")
    async with _client(_app(container, alice)) as client:
        created = await _upload(client, "wd_e4b_linked.txt")
        converted = await client.post(
            "/api/v1/file/convert",
            json={"file_ids": [created["id"]], "kb_ids": [dataset_id]},
        )
        listed = await client.get(f"/api/v1/datasets/{dataset_id}/documents")

    assert converted.status_code == _HTTP_OK, converted.text
    assert converted.json() == {
        "code": RetCode.SUCCESS,
        "data": True,
        "message": "success",
    }
    docs = listed.json()["data"]["docs"]
    assert [doc["name"] for doc in docs] == ["wd_e4b_linked.txt"]


async def test_upload_info_returns_metadata(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """upload_info: 8 kluczy złota ``--19``; ``size`` liczone ``sys.getsizeof`` (upstream)."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        response = await client.post(
            "/api/v1/file/upload_info", files={"file": ("ragflow_intro.txt", _FILE_BYTES)}
        )

    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    assert set(body["data"]) == _UPLOAD_INFO_KEYS
    assert body["data"]["name"] == "ragflow_intro.txt"
    assert body["data"]["extension"] == "txt"
    assert body["data"]["preview_url"] is None


async def test_rm_removes_own_file(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """rm: własny plik → ``{code:0, data:{success_count:1}}``; brakujący → 102 z ``errors``."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        created = await _upload(client, "wd_e4b_do_usuniecia.txt")
        deleted = await client.post("/api/v1/file/rm", json={"ids": [created["id"]]})
        missing = await client.post("/api/v1/file/rm", json={"ids": [_MISSING_FILE]})
        listed = await _listing(client)

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
    assert listed["files"] == []


async def test_foreign_resource_refused_for_six_routes(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudzy plik (get/parent/mv/rename/rm/convert) → 102; zasób właściciela nietknięty (§7)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    dataset_id = await _dataset(container, alice, "wd_e4b_cudzy_ds")
    async with _client(_app(container, alice)) as client:
        folder_id = await _create_folder(client, "wd_e4b_cudzy_folder")
        probe = await _upload(client, "wd_e4b_cudzy.txt")
    bob = principal_for(await seed_user(sm))
    async with _client(_app(container, bob)) as stranger:
        downloaded = await stranger.get(f"/api/v1/file/get/{probe['id']}")
        parent = await stranger.get("/api/v1/file/parent_folder", params={"file_id": probe["id"]})
        moved = await stranger.post(
            "/api/v1/file/mv",
            json={"src_file_ids": [probe["id"]], "dest_file_id": folder_id},
        )
        renamed = await stranger.post(
            "/api/v1/file/rename",
            json={"file_id": probe["id"], "name": "wd_e4b_przejete.txt"},
        )
        removed = await stranger.post("/api/v1/file/rm", json={"ids": [probe["id"]]})
        converted = await stranger.post(
            "/api/v1/file/convert",
            json={"file_ids": [probe["id"]], "kb_ids": [dataset_id]},
        )

    refused = {"code": RetCode.DATA_ERROR, "message": _NO_AUTHORIZATION}
    for response in (downloaded, parent, moved, renamed, converted):
        assert response.status_code == _HTTP_OK, response.text
        assert response.json() == refused, response.text
    assert removed.json() == {
        "code": RetCode.DATA_ERROR,
        "data": {
            "errors": [f"No authorization for file {probe['id']}"],
            "success_count": 0,
        },
        "message": "Deleted files failed with 1 errors",
    }
    async with _client(_app(container, alice)) as client:
        listed = await _listing(client)
    assert _find(listed["files"], probe["id"])["name"] == "wd_e4b_cudzy.txt"


async def test_parent_folder_without_file_id(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak ``file_id`` w query → 102 ``\\`file_id\\` query parameter is required`` (§D3)."""
    alice = principal_for(await seed_user(sm))
    async with _client(_app(container, alice)) as client:
        parent = await client.get("/api/v1/file/parent_folder")
        ancestors = await client.get("/api/v1/file/all_parent_folder")

    expected = {"code": RetCode.DATA_ERROR, "message": _MSG_FILE_ID_REQUIRED}
    assert parent.json() == expected
    assert ancestors.json() == expected


async def test_missing_authorization_header_is_401(container: Container) -> None:
    """Brak nagłówka ``Authorization`` → HTTP 401 (złoto ``--28/--29``)."""
    async with _client(_app(container)) as anonymous:
        response = await anonymous.get("/api/v1/file/list")

    assert response.status_code == _HTTP_UNAUTHORIZED
    assert response.json()["code"] == _HTTP_UNAUTHORIZED
