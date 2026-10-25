"""Testy HTTP trasy ``POST /api/v1/files/link-to-datasets`` (brief T6; CONTRACT §D1.7, §D5).

Kształty i komunikaty dosłownie złoto v0.27.2 (``files--15`` sukces, ``files--24`` brak
datasetu, ``files--30`` cudzy plik, ``files--16`` dokument w liście datasetu). Trasy
odmów włączają profil ``PROFILES`` (v0.27: 102 ``no authorization``, bez ``data``).
Fixture'y współdzielone z ``test_documents_routes`` (ten sam wzorzec co ``test_files_v024``).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.error_codes import RetCode
from tests.integration.api import test_documents_routes as _documents

# Fixture'y współdzielone z ``test_documents_routes`` (re-eksport wzorem ``test_files_v024``).
settings = _documents.settings
users_svc = _documents.users_svc
keys_svc = _documents.keys_svc
models_seeded = _documents.models_seeded
owner = _documents.owner
bob_key = _documents.bob_key
client = _documents.client

pytestmark = pytest.mark.db

_OK = 200
_CODE_ARGUMENT_ERROR = 101
_CODE_DATA_ERROR = 102
_MSG_MODE_INVALID = "mode must be 'add' or 'replace'"
_MSG_DATASET_NOT_FOUND = "Can't find this dataset!"
_MSG_NO_AUTHORIZATION = "no authorization"
_MISSING_DATASET = "0" * 32
_FILE_NAME = "wd_e4a_link.txt"
_FILE_BYTES = b"wawelski dragon - link routes (E4-5a T6)\n"

_LINK_KEYS = {"code", "data", "message"}
_DOC_LIST_KEYS = {"docs", "total"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _dataset(client: TestClient, token: str, name: str) -> str:
    """POST /datasets z asercją sukcesu; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": name})
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == RetCode.SUCCESS, payload
    dataset_id: str = payload["data"]["id"]
    return dataset_id


def _upload(client: TestClient, token: str, *, name: str = _FILE_NAME) -> str:
    """POST /files (multipart) z asercją sukcesu; zwraca id pliku."""
    response = client.post(
        "/api/v1/files",
        headers=_bearer(token),
        files={"file": (name, _FILE_BYTES)},
    )
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == RetCode.SUCCESS, payload
    file_id: str = payload["data"][0]["id"]
    return file_id


def _link(
    client: TestClient,
    token: str,
    file_ids: list[str],
    kb_ids: list[str],
    *,
    mode: str | None = None,
) -> Any:
    """POST /files/link-to-datasets (klucz API właściciela); zwraca odpowiedź."""
    params = {"mode": mode} if mode is not None else None
    return client.post(
        "/api/v1/files/link-to-datasets",
        headers=_bearer(token),
        json={"file_ids": file_ids, "kb_ids": kb_ids},
        params=params,
    )


def _doc_names(client: TestClient, token: str, dataset_id: str) -> list[str]:
    """Nazwy dokumentów datasetu przez ``GET /datasets/{id}/documents``."""
    response = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == RetCode.SUCCESS, payload
    assert set(payload["data"]) == _DOC_LIST_KEYS, payload["data"]
    return [doc["name"] for doc in payload["data"]["docs"]]


def test_link_success_and_document_in_dataset(client: TestClient, owner: tuple[str, str]) -> None:
    """Sukces: ``{code:0, data:true, message:success}`` i dokument w liście datasetu (§D1.7)."""
    token, _user_id = owner
    dataset_id = _dataset(client, token, "wd_e4a_link_ds")
    file_id = _upload(client, token)

    response = _link(client, token, [file_id], [dataset_id])

    assert response.status_code == _OK, response.text
    assert response.json() == {"code": RetCode.SUCCESS, "data": True, "message": "success"}
    assert set(response.json()) == _LINK_KEYS
    listed = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    docs = listed.json()["data"]["docs"]
    assert len(docs) == 1
    doc = docs[0]
    # Złoto files--16: dokument powstały z linku nie jest parsowany.
    assert (doc["name"], doc["run"], doc["chunk_count"]) == (_FILE_NAME, "UNSTART", 0)
    # CONTRACT §D1.3: location = bieżąca nazwa pliku.
    assert doc["location"] == _FILE_NAME


def test_bad_mode_is_argument_error(client: TestClient, owner: tuple[str, str]) -> None:
    """``?mode=bad`` → 101 ``mode must be 'add' or 'replace'`` (przykład briefu)."""
    token, _user_id = owner
    dataset_id = _dataset(client, token, "wd_e4a_link_mode_ds")
    file_id = _upload(client, token)

    response = _link(client, token, [file_id], [dataset_id], mode="bad")

    assert response.status_code == _OK, response.text
    assert response.json() == {"code": _CODE_ARGUMENT_ERROR, "message": _MSG_MODE_INVALID}
    assert _doc_names(client, token, dataset_id) == []


def test_missing_dataset_is_data_error(client: TestClient, owner: tuple[str, str]) -> None:
    """Nieistniejący dataset → 102 ``Can't find this dataset!`` (złoto files--24)."""
    token, _user_id = owner
    file_id = _upload(client, token)

    response = _link(client, token, [file_id], [_MISSING_DATASET])

    assert response.status_code == _OK, response.text
    assert response.json() == {"code": _CODE_DATA_ERROR, "message": _MSG_DATASET_NOT_FOUND}


def test_foreign_file_is_refused(client: TestClient, owner: tuple[str, str], bob_key: str) -> None:
    """Cudzy plik → 102 ``no authorization`` bez ``data`` (złoto files--30)."""
    token, _user_id = owner
    dataset_id = _dataset(client, token, "wd_e4a_link_foreign_ds")
    file_id = _upload(client, token)

    response = _link(client, bob_key, [file_id], [dataset_id])

    assert response.status_code == _OK, response.text
    assert response.json() == {"code": _CODE_DATA_ERROR, "message": _MSG_NO_AUTHORIZATION}
    assert _doc_names(client, token, dataset_id) == []


def test_missing_kb_ids_is_argument_error(client: TestClient, owner: tuple[str, str]) -> None:
    """Brak klucza ``kb_ids`` → 101 (port ``validate_request``, file2document_api.py:100)."""
    token, _user_id = owner
    file_id = _upload(client, token)

    response = client.post(
        "/api/v1/files/link-to-datasets",
        headers=_bearer(token),
        json={"file_ids": [file_id]},
    )

    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_ARGUMENT_ERROR, payload
    assert "kb_ids" in payload["message"]


def test_mode_add_keeps_and_replace_drops_previous(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """``replace`` (domyślny) kasuje link do innego datasetu, ``add`` go zachowuje (§D1.7)."""
    token, _user_id = owner
    first = _dataset(client, token, "wd_e4a_link_first")
    second = _dataset(client, token, "wd_e4a_link_second")
    file_id = _upload(client, token)

    assert _link(client, token, [file_id], [first]).json()["code"] == RetCode.SUCCESS
    assert _link(client, token, [file_id], [second], mode="add").json()["code"] == RetCode.SUCCESS
    assert _doc_names(client, token, first) == [_FILE_NAME]
    assert _doc_names(client, token, second) == [_FILE_NAME]

    assert (
        _link(client, token, [file_id], [second], mode="replace").json()["code"] == RetCode.SUCCESS
    )
    assert _doc_names(client, token, first) == []
    assert _doc_names(client, token, second) == [_FILE_NAME]
