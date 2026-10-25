"""Trasy mutujące legacy ``/api/v1/file/*`` w profilu 0.24: mv/rename/rm/convert (E4-5b T3).

Wzór ``test_files_v024.py``: klucze API (właściciel i Bob) i nagłówek ``X-RAGFlow-Compat: 0.24``
wybierają funkcje ``file_legacy_v024_ops``. Fixture'y zakładamy trasami v0.27 ``/api/v1/files``
i ``/api/v1/datasets`` — profil 0.24 jest przedmiotem testu, nie narzędziem. Kody i komunikaty
dosłownie z CONTRACT §D4 oraz odchyłek DEC-201 (cudzy zasób jak nieistniejący) i DEC-202
(``convert`` bez pliku → 102 „File not found!").
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.error_codes import RetCode
from tests.integration.api import test_documents_routes as _documents

# Fixture'y współdzielone z ``test_documents_routes`` (wzorzec ``test_files_v024``).
settings = _documents.settings
users_svc = _documents.users_svc
keys_svc = _documents.keys_svc
models_seeded = _documents.models_seeded
owner = _documents.owner
bob_key = _documents.bob_key
client = _documents.client

pytestmark = pytest.mark.db

_OK = 200
_V024 = "0.24"
_MISSING = "0" * 32
_FILE_NAME = "wd_e4b_t3.txt"
_FILE_BYTES = b"wawelski dragon - mv/rename/rm/convert 0.24 (E4-5b T3)\n"

_SUCCESS = {"code": 0, "data": True, "message": "success"}
_FILE_NOT_FOUND = {"code": 404, "data": None, "message": "File not found!"}
_EXTENSION_CHANGED = {
    "code": 400,
    "data": False,
    "message": "The extension of file can't be changed",
}
_DUPLICATED_NAME = {
    "code": 409,
    "data": False,
    "message": "Duplicated file name in the same folder.",
}
_PARENT_FOLDER_NOT_FOUND = {"code": 404, "data": None, "message": "Parent Folder not found!"}
_FILE_OR_FOLDER_NOT_FOUND = {"code": 404, "data": None, "message": "File or Folder not found!"}
_CONVERT_FILE_NOT_FOUND = {"code": 102, "data": None, "message": "File not found!"}
_DATASET_NOT_FOUND = {"code": 404, "data": None, "message": "Can't find this dataset!"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _v024(token: str) -> dict[str, str]:
    """Nagłówki klucza API wymuszające profil zgodności 0.24 (C7)."""
    return {**_bearer(token), "X-RAGFlow-Compat": _V024}


def _upload(
    client: TestClient, token: str, name: str = _FILE_NAME, parent_id: str | None = None
) -> str:
    """POST /files (multipart, v0.27) z asercją sukcesu; zwraca id pliku."""
    data = {"parent_id": parent_id} if parent_id is not None else None
    response = client.post(
        "/api/v1/files", headers=_bearer(token), files={"file": (name, _FILE_BYTES)}, data=data
    )
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == RetCode.SUCCESS, payload
    file_id: str = payload["data"][0]["id"]
    return file_id


def _folder(client: TestClient, token: str, name: str, parent_id: str | None = None) -> str:
    """POST /files (JSON, v0.27) z asercją sukcesu; zwraca id folderu."""
    payload: dict[str, Any] = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = client.post("/api/v1/files", headers=_bearer(token), json=payload)
    assert response.status_code == _OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    folder_id: str = body["data"]["id"]
    return folder_id


def _dataset(client: TestClient, token: str, name: str) -> str:
    """POST /datasets z asercją sukcesu; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": name})
    assert response.status_code == _OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    dataset_id: str = body["data"]["id"]
    return dataset_id


def _listed(client: TestClient, token: str, parent_id: str | None = None) -> list[dict[str, Any]]:
    """Widoczne dzieci folderu przez ``GET /files`` (v0.27 — narzędzie kontroli stanu)."""
    params = {"parent_id": parent_id} if parent_id is not None else None
    response = client.get("/api/v1/files", headers=_bearer(token), params=params)
    assert response.status_code == _OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    files: list[dict[str, Any]] = body["data"]["files"]
    return files


def _find(files: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    """Element listingu po id (kolejność sortowania nie jest przedmiotem testu)."""
    found = [item for item in files if item["id"] == item_id]
    assert len(found) == 1, files
    return found[0]


def _ids(files: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in files}


def _key_error(key: str) -> dict[str, Any]:
    """Koperta ``KeyError(klucz)``: ``code 100``, ``data null`` (§D4)."""
    return {"code": 100, "data": None, "message": f"KeyError('{key}')"}


def _mv(client: TestClient, token: str, src_ids: list[str], dest_id: str) -> Any:
    return client.post(
        "/api/v1/file/mv",
        headers=_v024(token),
        json={"src_file_ids": src_ids, "dest_file_id": dest_id},
    )


def _rename(client: TestClient, token: str, file_id: str, name: str) -> Any:
    return client.post(
        "/api/v1/file/rename", headers=_v024(token), json={"file_id": file_id, "name": name}
    )


def _rm(client: TestClient, token: str, file_ids: list[str]) -> Any:
    return client.post("/api/v1/file/rm", headers=_v024(token), json={"file_ids": file_ids})


def _convert(client: TestClient, token: str, file_ids: list[str], kb_ids: list[str]) -> Any:
    return client.post(
        "/api/v1/file/convert", headers=_v024(token), json={"file_ids": file_ids, "kb_ids": kb_ids}
    )


def test_mv_moves_file_to_folder(client: TestClient, owner: tuple[str, str]) -> None:
    """mv do folderu: kod 0, ``data true``, plik widoczny w nowym folderze (§D4, złoto --11)."""
    token, _user_id = owner
    folder_id = _folder(client, token, "wd_e4b_t3_cel")
    file_id = _upload(client, token)

    response = _mv(client, token, [file_id], folder_id)

    assert response.status_code == _OK, response.text
    assert response.json() == _SUCCESS
    assert _ids(_listed(client, token, folder_id)) == {file_id}
    assert file_id not in _ids(_listed(client, token))


def test_mv_missing_src_reports_key_error(client: TestClient, owner: tuple[str, str]) -> None:
    """mv nieistniejącego (lub cudzego) src → ``KeyError(id)`` code 100 (§D4, złoto --23)."""
    token, _user_id = owner
    folder_id = _folder(client, token, "wd_e4b_t3_kex")

    response = _mv(client, token, [_MISSING], folder_id)

    assert response.status_code == _OK, response.text
    assert response.json() == _key_error(_MISSING)


def test_mv_missing_dest_folder(client: TestClient, owner: tuple[str, str]) -> None:
    """mv do nieistniejącego folderu → 404 „Parent Folder not found!"; plik nietknięty."""
    token, _user_id = owner
    file_id = _upload(client, token)

    response = _mv(client, token, [file_id], _MISSING)

    assert response.status_code == _OK, response.text
    assert response.json() == _PARENT_FOLDER_NOT_FOUND
    assert file_id in _ids(_listed(client, token))


def test_rename_file(client: TestClient, owner: tuple[str, str]) -> None:
    """rename: kod 0, ``data true``, nowa nazwa w listingu (złoto --15)."""
    token, _user_id = owner
    file_id = _upload(client, token)

    response = _rename(client, token, file_id, "wd_e4b_t3_zmieniony.txt")

    assert response.status_code == _OK, response.text
    assert response.json() == _SUCCESS
    assert _find(_listed(client, token), file_id)["name"] == "wd_e4b_t3_zmieniony.txt"


def test_rename_extension_change_rejected(client: TestClient, owner: tuple[str, str]) -> None:
    """Zmiana rozszerzenia → 400 ``data false``; nazwa bez zmian (przykład briefu)."""
    token, _user_id = owner
    file_id = _upload(client, token)

    response = _rename(client, token, file_id, "wd_e4b_t3.pdf")

    assert response.status_code == _OK, response.text
    assert response.json() == _EXTENSION_CHANGED
    assert _find(_listed(client, token), file_id)["name"] == _FILE_NAME


def test_rename_duplicate_name_rejected(client: TestClient, owner: tuple[str, str]) -> None:
    """Zajęta nazwa w folderze → 409 ``data false``; nazwa bez zmian."""
    token, _user_id = owner
    first = _upload(client, token, "wd_e4b_t3_a.txt")
    second = _upload(client, token, "wd_e4b_t3_b.txt")

    response = _rename(client, token, second, "wd_e4b_t3_a.txt")

    assert response.status_code == _OK, response.text
    assert response.json() == _DUPLICATED_NAME
    assert _find(_listed(client, token), second)["name"] == "wd_e4b_t3_b.txt"
    assert _find(_listed(client, token), first)["name"] == "wd_e4b_t3_a.txt"


def test_rename_missing_file(client: TestClient, owner: tuple[str, str]) -> None:
    """rename nieistniejącego pliku → 404 „File not found!"."""
    token, _user_id = owner

    response = _rename(client, token, _MISSING, "wd_e4b_t3_x.txt")

    assert response.status_code == _OK, response.text
    assert response.json() == _FILE_NOT_FOUND


def test_rm_removes_file(client: TestClient, owner: tuple[str, str]) -> None:
    """rm własnego pliku → kod 0; plik znika z listingu (złoto --24/--38)."""
    token, _user_id = owner
    file_id = _upload(client, token)

    response = _rm(client, token, [file_id])

    assert response.status_code == _OK, response.text
    assert response.json() == _SUCCESS
    assert file_id not in _ids(_listed(client, token))


def test_rm_missing_file(client: TestClient, owner: tuple[str, str]) -> None:
    """rm nieistniejącego id → 404 „File or Folder not found!" (złoto --24)."""
    token, _user_id = owner

    response = _rm(client, token, [_MISSING])

    assert response.status_code == _OK, response.text
    assert response.json() == _FILE_OR_FOLDER_NOT_FOUND


def test_rm_second_missing_keeps_first_deleted(client: TestClient, owner: tuple[str, str]) -> None:
    """rm ``[plik, brak]``: pierwsze id usunięte, odpowiedź 404 jak upstream (§D4)."""
    token, _user_id = owner
    file_id = _upload(client, token)

    response = _rm(client, token, [file_id, _MISSING])

    assert response.status_code == _OK, response.text
    assert response.json() == _FILE_OR_FOLDER_NOT_FOUND
    assert file_id not in _ids(_listed(client, token))


def test_convert_links_file_and_returns_links(client: TestClient, owner: tuple[str, str]) -> None:
    """convert: lista wiązań z 3 kluczami i dokument pliku w datasecie (§D4, złoto --17)."""
    token, _user_id = owner
    dataset_id = _dataset(client, token, "wd_e4b_t3_ds")
    file_id = _upload(client, token)

    response = _convert(client, token, [file_id], [dataset_id])

    assert response.status_code == _OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    assert body["message"] == "success"
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    link = body["data"][0]
    assert set(link) == {"document_id", "file_id", "id"}
    assert link["file_id"] == file_id

    documents = client.get(
        f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token)
    ).json()["data"]["docs"]
    assert [doc["name"] for doc in documents] == [_FILE_NAME]
    assert [doc["id"] for doc in documents] == [link["document_id"]]


def test_convert_existing_link_returns_same_binding(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """Drugi convert tego samego pliku/datasetu → to samo wiązanie, jeden dokument (§D6)."""
    token, _user_id = owner
    dataset_id = _dataset(client, token, "wd_e4b_t3_ds_powtorka")
    file_id = _upload(client, token, "wd_e4b_t3_powtorka.txt")

    first = _convert(client, token, [file_id], [dataset_id]).json()["data"]
    second = _convert(client, token, [file_id], [dataset_id]).json()["data"]

    assert first == second
    documents = client.get(
        f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token)
    ).json()["data"]["docs"]
    assert [doc["id"] for doc in documents] == [first[0]["document_id"]]


def test_convert_two_datasets_in_request_order(client: TestClient, owner: tuple[str, str]) -> None:
    """Dwa datasety → wiązania w kolejności ``kb_ids`` z żądania (§D6)."""
    token, _user_id = owner
    first_ds = _dataset(client, token, "wd_e4b_t3_ds_a")
    second_ds = _dataset(client, token, "wd_e4b_t3_ds_b")
    file_id = _upload(client, token, "wd_e4b_t3_dwa.txt")

    data = _convert(client, token, [file_id], [second_ds, first_ds]).json()["data"]

    assert [link["file_id"] for link in data] == [file_id, file_id]
    docs_by_dataset = {
        dataset_id: client.get(
            f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token)
        ).json()["data"]["docs"]
        for dataset_id in (first_ds, second_ds)
    }
    assert [link["document_id"] for link in data] == [
        docs_by_dataset[second_ds][0]["id"],
        docs_by_dataset[first_ds][0]["id"],
    ]


def test_convert_missing_file(client: TestClient, owner: tuple[str, str]) -> None:
    """convert bez pliku → 102 „File not found!" (odchyłka (d) DEC-202)."""
    token, _user_id = owner
    dataset_id = _dataset(client, token, "wd_e4b_t3_brak_pliku")

    response = _convert(client, token, [_MISSING], [dataset_id])

    assert response.status_code == _OK, response.text
    assert response.json() == _CONVERT_FILE_NOT_FOUND


def test_convert_missing_dataset(client: TestClient, owner: tuple[str, str]) -> None:
    """convert do nieistniejącego datasetu → 404 „Can't find this dataset!"."""
    token, _user_id = owner
    file_id = _upload(client, token)

    response = _convert(client, token, [file_id], [_MISSING])

    assert response.status_code == _OK, response.text
    assert response.json() == _DATASET_NOT_FOUND


def test_foreign_file_ops_like_missing_and_owner_untouched(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy plik drugim użytkownikiem: mv/rename/rm/convert jak brak id; zasób właściciela cały."""
    token, _user_id = owner
    folder_id = _folder(client, token, "wd_e4b_t3_cudzy_folder")
    file_id = _upload(client, token, "wd_e4b_t3_cudzy.txt")
    before = _find(_listed(client, token), file_id)

    moved = _mv(client, bob_key, [file_id], folder_id)
    renamed = _rename(client, bob_key, file_id, "wd_e4b_t3_przejete.txt")
    removed = _rm(client, bob_key, [file_id])
    converted = _convert(client, bob_key, [file_id], [_MISSING])

    assert moved.json() == _key_error(file_id)
    assert renamed.json() == _FILE_NOT_FOUND
    assert removed.json() == _FILE_OR_FOLDER_NOT_FOUND
    assert converted.json() == _CONVERT_FILE_NOT_FOUND

    after = _find(_listed(client, token), file_id)
    assert after["name"] == before["name"] == "wd_e4b_t3_cudzy.txt"
    assert after["parent_id"] == before["parent_id"]


def test_foreign_dataset_convert_untouched(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy dataset własnym plikiem → 404 jak brak datasetu; dataset właściciela bez dokumentów."""
    token, _user_id = owner
    dataset_id = _dataset(client, token, "wd_e4b_t3_cudzy_ds")
    bob_file = _upload(client, bob_key, "wd_e4b_t3_bob.txt")

    response = _convert(client, bob_key, [bob_file], [dataset_id])

    assert response.status_code == _OK, response.text
    assert response.json() == _DATASET_NOT_FOUND
    documents = client.get(
        f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token)
    ).json()["data"]["docs"]
    assert documents == []


def test_missing_body_keys_report_key_error(client: TestClient, owner: tuple[str, str]) -> None:
    """Brak klucza ciała → ``KeyError(klucz)`` code 100 w kolejności tras (§D4)."""
    token, _user_id = owner

    mv = client.post("/api/v1/file/mv", headers=_v024(token), json={"dest_file_id": "x"})
    rename = client.post("/api/v1/file/rename", headers=_v024(token), json={"name": "x"})
    rm = client.post("/api/v1/file/rm", headers=_v024(token), json={})
    convert = client.post("/api/v1/file/convert", headers=_v024(token), json={"file_ids": []})

    assert mv.json() == _key_error("src_file_ids")
    assert rename.json() == _key_error("file_id")
    assert rm.json() == _key_error("file_ids")
    assert convert.json() == _key_error("kb_ids")
