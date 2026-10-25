"""Testy HTTP tras legacy ``/api/v1/file/*`` w profilu 0.24 (E4-5b T2; CONTRACT §D4).

Kody, komunikaty i kształty dosłownie z kontraktu §D4 i złota v0.24.0
(``tests/contract/golden/v0.24.0/file__*``). Profil wymuszamy nagłówkiem
``X-RAGFlow-Compat: 0.24`` na kluczu API (C7) — podmiot JWT zawsze daje 0.27. Cudzy zasób
dostaje tę samą odpowiedź co nieistniejące id (DEC-201), a zasób właściciela zostaje
nietknięty. Fixture'y współdzielone z ``test_documents_routes`` (wzorzec ``test_files_v024``).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.error_codes import RetCode
from tests.integration.api import test_documents_routes as _documents

# Fixture'y współdzielone z ``test_documents_routes`` (re-eksport jak w ``test_files_v024``).
users_svc = _documents.users_svc
keys_svc = _documents.keys_svc
models_seeded = _documents.models_seeded
owner = _documents.owner
bob_key = _documents.bob_key
client = _documents.client

pytestmark = pytest.mark.db


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Any) -> Settings:
    """Ustawienia jak w ``test_documents_routes`` + niski limit uploadu (gałąź 102 §D4)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path), "max_upload_mb": 1})


_OK = 200
_V024_COMPAT = "0.24"
_MISSING_ID = "0" * 32
_MSG_SUCCESS = "success"
_MSG_PARENT_NOT_EXIST = "Parent Folder Doesn't Exist!"
_MSG_DOCUMENT_NOT_FOUND = "Document not found!"
_MSG_FOLDER_NOT_FOUND = "Folder not found!"
_MSG_CANT_FIND_FOLDER = "Can't find this folder!"
_MSG_NO_FILE_PART = "No file part!"
_MSG_NO_FILE_SELECTED = "No selected file!"
_MSG_DUPLICATED_FOLDER = "Duplicated folder name in the same folder."
_MSG_SPECIFY_DOC_ID = "AssertionError('please specify doc_id')"
_FILE_NAME = "x.txt"
_FILE_BYTES = b"wawelski dragon - legacy /file/* w profilu 0.24 (E4-5b T2)\n"
# Dwa uploady w listingu: liczba widocznych dzieci roota w teście sortowania.
_ROOT_ITEMS = 2

# Klucze prezenterów (CONTRACT §D4; złoto file_legacy--02/--05/--09).
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


def _v024(token: str) -> dict[str, str]:
    """Nagłówki klucza API wymuszające profil zgodności 0.24 (C7)."""
    return {"Authorization": f"Bearer {token}", "X-RAGFlow-Compat": _V024_COMPAT}


def _ok(response: Any) -> dict[str, Any]:
    """Asercja sukcesu koperty SDK v0.24; zwraca ciało (``code``/``data``/``message``)."""
    assert response.status_code == _OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    assert body["message"] == _MSG_SUCCESS, body
    return body


def _create(
    client: TestClient, headers: dict[str, str], name: str, parent_id: str | None = None
) -> str:
    """POST /file/create z asercją sukcesu; zwraca id folderu (złoto ``--02``/``--03``)."""
    payload: dict[str, Any] = {"name": name, "type": "folder"}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    body = _ok(client.post("/api/v1/file/create", headers=headers, json=payload))
    item = body["data"]
    assert set(item) == _CREATED_KEYS, item
    assert (item["name"], item["type"], item["location"]) == (name, "folder", "")
    return item["id"]


def _upload(
    client: TestClient,
    headers: dict[str, str],
    name: str = _FILE_NAME,
    *,
    content: bytes = _FILE_BYTES,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """POST /file/upload (multipart) z asercją sukcesu; zwraca ``data[0]`` (złoto ``--04``)."""
    data = {"parent_id": parent_id} if parent_id is not None else None
    response = client.post(
        "/api/v1/file/upload", headers=headers, files={"file": (name, content)}, data=data
    )
    body = _ok(response)
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1, body
    item = body["data"][0]
    assert set(item) == _CREATED_KEYS, item
    return item


def _list(client: TestClient, headers: dict[str, str], **params: str) -> dict[str, Any]:
    """GET /file/list z asercją sukcesu; zwraca ``data`` (klucze listingu, złoto ``--05``)."""
    body = _ok(client.get("/api/v1/file/list", headers=headers, params=params))
    assert set(body["data"]) == {"files", "parent_folder", "total"}, body["data"]
    return body["data"]


def test_create_and_root_folder_match_golden(client: TestClient, owner: tuple[str, str]) -> None:
    """create/root_folder: koperta 0.24, 9 kluczy folderu i root o ``name "/"`` (``--02/--09``)."""
    token, _user_id = owner
    headers = _v024(token)
    folder_id = _create(client, headers, "wd_e4b_v024_folder")
    root = _ok(client.get("/api/v1/file/root_folder", headers=headers))

    assert set(root["data"]) == {"root_folder"}
    root_folder = root["data"]["root_folder"]
    assert set(root_folder) == _PARENT_KEYS, root_folder
    assert (root_folder["name"], root_folder["type"], root_folder["location"]) == (
        "/",
        "folder",
        "",
    )
    assert root_folder["parent_id"] == root_folder["id"] != folder_id


def test_create_duplicate_and_bad_parent(client: TestClient, owner: tuple[str, str]) -> None:
    """create: duplikat nazwy → 409/``data false`` (``--27``); zły rodzic → 400/``data false``."""
    token, _user_id = owner
    headers = _v024(token)
    _create(client, headers, "wd_e4b_v024_dup")

    duplicate = client.post(
        "/api/v1/file/create",
        headers=headers,
        json={"name": "wd_e4b_v024_dup", "type": "folder"},
    )
    bad_parent = client.post(
        "/api/v1/file/create",
        headers=headers,
        json={"name": "wd_e4b_v024_sierota", "parent_id": _MISSING_ID, "type": "folder"},
    )

    assert duplicate.json() == {
        "code": RetCode.CONFLICT,
        "data": False,
        "message": _MSG_DUPLICATED_FOLDER,
    }
    assert bad_parent.json() == {
        "code": RetCode.BAD_REQUEST,
        "data": False,
        "message": _MSG_PARENT_NOT_EXIST,
    }


def test_upload_and_get_download(client: TestClient, owner: tuple[str, str]) -> None:
    """upload/get: lista ``file_created`` i blob ``application/txt`` (``--04/--10``)."""
    token, _user_id = owner
    headers = _v024(token)
    created = _upload(client, headers)

    assert (created["name"], created["size"], created["type"]) == (
        _FILE_NAME,
        len(_FILE_BYTES),
        "doc",
    )
    downloaded = client.get(f"/api/v1/file/get/{created['id']}", headers=headers)

    assert downloaded.status_code == _OK, downloaded.text
    assert downloaded.content == _FILE_BYTES
    assert downloaded.headers["content-type"] == "application/txt"
    assert "content-disposition" not in downloaded.headers


def _empty_filename_upload(client: TestClient, headers: dict[str, str]) -> Any:
    """Multipart z częścią ``file`` o pustej nazwie (httpx sam pominąłby atrybut ``filename``)."""
    boundary = "----wd-e4b-v024-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename=""\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
        f"{_FILE_BYTES.decode()}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    return client.post(
        "/api/v1/file/upload",
        headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        content=body,
    )


def test_upload_without_file_part_and_bad_parent(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """upload: brak części ``file`` i pusta nazwa → 400; brak folderu docelowego → 404 (§D4)."""
    token, _user_id = owner
    headers = _v024(token)

    no_part = client.post("/api/v1/file/upload", headers=headers, data={"parent_id": ""})
    empty_name = _empty_filename_upload(client, headers)
    bad_parent = client.post(
        "/api/v1/file/upload",
        headers=headers,
        files={"file": (_FILE_NAME, _FILE_BYTES)},
        data={"parent_id": _MISSING_ID},
    )

    assert no_part.json() == {
        "code": RetCode.BAD_REQUEST,
        "data": False,
        "message": _MSG_NO_FILE_PART,
    }
    assert empty_name.json() == {
        "code": RetCode.BAD_REQUEST,
        "data": False,
        "message": _MSG_NO_FILE_SELECTED,
    }
    assert bad_parent.json() == {
        "code": RetCode.NOT_FOUND,
        "data": False,
        "message": _MSG_CANT_FIND_FOLDER,
    }


def test_upload_over_limit_reports_service_error(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """upload: inny ``ValidationFailed`` usługi (limit rozmiaru) → 102, nie 404 (§D4)."""
    token, _user_id = owner
    response = client.post(
        "/api/v1/file/upload",
        headers=_v024(token),
        files={"file": ("wd_e4b_v024_big.bin", b"x" * (1024 * 1024 + 1))},
    )

    assert response.json() == {
        "code": RetCode.DATA_ERROR,
        "data": None,
        "message": "file exceeds limit of 1048576 bytes",
    }


def test_get_missing_and_folder_artifacts(client: TestClient, owner: tuple[str, str]) -> None:
    """get: brak → 404 (``--20``); własny folder → 100 ``AssertionError`` (``--32``, §D4)."""
    token, _user_id = owner
    headers = _v024(token)
    folder_id = _create(client, headers, "wd_e4b_v024_pobranie")

    missing = client.get(f"/api/v1/file/get/{_MISSING_ID}", headers=headers)
    folder = client.get(f"/api/v1/file/get/{folder_id}", headers=headers)

    assert missing.json() == {
        "code": RetCode.NOT_FOUND,
        "data": None,
        "message": _MSG_DOCUMENT_NOT_FOUND,
    }
    assert folder.json() == {
        "code": 100,
        "data": None,
        "message": _MSG_SPECIFY_DOC_ID,
    }


def test_list_own_and_desc_keeps_descending(client: TestClient, owner: tuple[str, str]) -> None:
    """list: ``parent_folder`` roota; ``desc=false`` → ``bool("false")`` malejąco (``--06``)."""
    token, _user_id = owner
    headers = _v024(token)
    _upload(client, headers, "wd_e4b_v024_a.txt")
    _upload(client, headers, "wd_e4b_v024_b.txt")

    listed = _list(client, headers)
    sorted_desc = _list(client, headers, orderby="name", desc="false")

    assert listed["parent_folder"]["name"] == "/"
    assert listed["total"] == _ROOT_ITEMS
    names = [item["name"] for item in sorted_desc["files"]]
    assert names == ["wd_e4b_v024_b.txt", "wd_e4b_v024_a.txt"], sorted_desc


def test_list_bad_parent_is_not_found(client: TestClient, owner: tuple[str, str]) -> None:
    """list: nieistniejący ``parent_id`` → 404 ``Folder not found!``/``data null`` (§D4)."""
    token, _user_id = owner
    response = client.get(
        "/api/v1/file/list", headers=_v024(token), params={"parent_id": _MISSING_ID}
    )

    assert response.json() == {
        "code": RetCode.NOT_FOUND,
        "data": None,
        "message": _MSG_FOLDER_NOT_FOUND,
    }


def test_parent_and_all_parent_folder(client: TestClient, owner: tuple[str, str]) -> None:
    """parent_folder/all_parent_folder: ``parent_folder`` i ścieżka ``[plik, …, root]`` (§D4)."""
    token, _user_id = owner
    headers = _v024(token)
    folder_id = _create(client, headers, "wd_e4b_v024_katalog")
    sub_id = _create(client, headers, "wd_e4b_v024_podkatalog", folder_id)
    created = _upload(client, headers, "wd_e4b_v024_sciezka.txt", parent_id=sub_id)

    parent = _ok(
        client.get("/api/v1/file/parent_folder", headers=headers, params={"file_id": created["id"]})
    )
    ancestors = _ok(
        client.get(
            "/api/v1/file/all_parent_folder", headers=headers, params={"file_id": created["id"]}
        )
    )

    assert set(parent["data"]) == {"parent_folder"}
    assert set(parent["data"]["parent_folder"]) == _PARENT_KEYS
    assert parent["data"]["parent_folder"]["id"] == sub_id
    path = ancestors["data"]["parent_folders"]
    assert [row["id"] for row in path] == [created["id"], sub_id, folder_id, path[-1]["id"]]
    assert path[-1]["name"] == "/"


def test_parent_routes_without_file_id_and_missing(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """Brak ``file_id`` (bez usługi) i nieistniejące id → 404 ``Folder not found!`` (§D4)."""
    token, _user_id = owner
    headers = _v024(token)
    expected = {"code": RetCode.NOT_FOUND, "data": None, "message": _MSG_FOLDER_NOT_FOUND}

    responses = [
        client.get("/api/v1/file/parent_folder", headers=headers),
        client.get("/api/v1/file/all_parent_folder", headers=headers),
        client.get("/api/v1/file/parent_folder", headers=headers, params={"file_id": _MISSING_ID}),
        client.get(
            "/api/v1/file/all_parent_folder", headers=headers, params={"file_id": _MISSING_ID}
        ),
    ]

    for response in responses:
        assert response.status_code == _OK, response.text
        assert response.json() == expected, response.text


def test_foreign_resource_refused_like_missing(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy folder/plik (get, parent, all_parent, list, create, upload) → jak nieistniejące id."""
    token, _user_id = owner
    owner_headers = _v024(token)
    folder_id = _create(client, owner_headers, "wd_e4b_v024_cudzy_folder")
    created = _upload(client, owner_headers, "wd_e4b_v024_cudzy.txt")
    stranger = _v024(bob_key)

    # Odpowiedzi cudzym kluczem — muszą być identyczne jak dla nieistniejącego id (DEC-201).
    foreign = {
        "get": client.get(f"/api/v1/file/get/{created['id']}", headers=stranger),
        "parent": client.get(
            "/api/v1/file/parent_folder", headers=stranger, params={"file_id": created["id"]}
        ),
        "all_parent": client.get(
            "/api/v1/file/all_parent_folder", headers=stranger, params={"file_id": created["id"]}
        ),
        "list": client.get("/api/v1/file/list", headers=stranger, params={"parent_id": folder_id}),
        "create": client.post(
            "/api/v1/file/create",
            headers=stranger,
            json={"name": "wd_e4b_v024_przejete", "parent_id": folder_id, "type": "folder"},
        ),
        "upload": client.post(
            "/api/v1/file/upload",
            headers=stranger,
            files={"file": ("wd_e4b_v024_przejete.txt", _FILE_BYTES)},
            data={"parent_id": folder_id},
        ),
    }
    missing = {
        "get": client.get(f"/api/v1/file/get/{_MISSING_ID}", headers=stranger),
        "parent": client.get(
            "/api/v1/file/parent_folder", headers=stranger, params={"file_id": _MISSING_ID}
        ),
        "all_parent": client.get(
            "/api/v1/file/all_parent_folder", headers=stranger, params={"file_id": _MISSING_ID}
        ),
        "list": client.get(
            "/api/v1/file/list", headers=stranger, params={"parent_id": _MISSING_ID}
        ),
        "create": client.post(
            "/api/v1/file/create",
            headers=stranger,
            json={"name": "wd_e4b_v024_sierota", "parent_id": _MISSING_ID, "type": "folder"},
        ),
        "upload": client.post(
            "/api/v1/file/upload",
            headers=stranger,
            files={"file": ("wd_e4b_v024_sierota.txt", _FILE_BYTES)},
            data={"parent_id": _MISSING_ID},
        ),
    }
    for route, response in foreign.items():
        assert response.status_code == _OK, response.text
        assert response.json() == missing[route].json(), route

    # Zasób właściciela nietknięty: folder i plik nadal na miejscu pod swoimi nazwami.
    listed = _list(client, owner_headers)
    assert {item["id"]: item["name"] for item in listed["files"]} == {
        folder_id: "wd_e4b_v024_cudzy_folder",
        created["id"]: "wd_e4b_v024_cudzy.txt",
    }
