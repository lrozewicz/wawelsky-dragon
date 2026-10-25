"""Trasy ``/api/v1/files*`` w profilu zgodności 0.24 i odmowy cudzego zasobu (brief T6).

W v0.24.0 upstream nie ma tras ``/api/v1/files*`` (ma ``/v1/file/*`` w ``api/apps/sdk/files.py``),
więc ``refusals_v024.PROFILES_V024`` nie ma wpisów ``files_*`` — ``refuse`` zwraca wtedy 108
(``PermissionDenied``, K16 §2 p. 3). Bez nagłówka (profil v0.27) wpisy ``PROFILES`` dają 102
``no authorization`` bez ``data`` (złoto kroków 26-31); ``DELETE /files`` nie rzuca odmowy, tylko
zwraca komunikat per id w ``errors`` (§D1.8). Własny zasób w 0.24 działa jak w 0.27.

Fixture'y współdzielone z ``test_documents_routes`` (wzorzec ``test_searches_v024``).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.error_codes import RetCode
from tests.integration.api import test_documents_routes as _documents

# Fixture'y współdzielone z ``test_documents_routes`` (re-eksport jak w ``test_searches_v024``).
settings = _documents.settings
users_svc = _documents.users_svc
keys_svc = _documents.keys_svc
models_seeded = _documents.models_seeded
owner = _documents.owner
bob_key = _documents.bob_key
client = _documents.client

pytestmark = pytest.mark.db

_OK = 200
_CODE_SUCCESS = 0
_CODE_DATA_ERROR = 102
_CODE_LACK_PERMISSION = 108
_V024_COMPAT = "0.24"
_MSG_NO_AUTHORIZATION = "no authorization"
_FILE_NAME = "wd_e4a_v024.txt"
_FILE_BYTES = b"wawelski dragon - profil 0.24 (E4-5a T6)\n"

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

_REFUSED_V027 = {"code": _CODE_DATA_ERROR, "message": _MSG_NO_AUTHORIZATION}
_REFUSED_V024 = {"code": _CODE_LACK_PERMISSION, "message": _MSG_NO_AUTHORIZATION, "data": None}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _v024(token: str) -> dict[str, str]:
    """Nagłówki klucza API wymuszające profil zgodności 0.24 (C7)."""
    return {**_bearer(token), "X-RAGFlow-Compat": _V024_COMPAT}


def _upload(client: TestClient, token: str, *, headers: dict[str, str] | None = None) -> str:
    """POST /files (multipart) z asercją sukcesu; zwraca id pliku."""
    response = client.post(
        "/api/v1/files",
        headers=headers if headers is not None else _bearer(token),
        files={"file": (_FILE_NAME, _FILE_BYTES)},
    )
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == RetCode.SUCCESS, payload
    file_id: str = payload["data"][0]["id"]
    return file_id


def _foreign_requests(
    client: TestClient, headers: dict[str, str], file_id: str, dest_id: str
) -> list[Any]:
    """Pięć tras konkretnego zasobu: pobranie, parent, ancestors, move, link (cudzym kluczem).

    Dataset do linku zakłada ten sam (cudzy) użytkownik — sprawdzenie własności pliku wypada
    wcześniej niż sprawdzenie dostępu do datasetu (§D1.7), więc wynik zależy tylko od pliku.
    """
    dataset_id = client.post(
        "/api/v1/datasets", headers=headers, json={"name": "wd_v024_cudzy_ds"}
    ).json()["data"]["id"]
    return [
        client.get(f"/api/v1/files/{file_id}", headers=headers),
        client.get(f"/api/v1/files/{file_id}/parent", headers=headers),
        client.get(f"/api/v1/files/{file_id}/ancestors", headers=headers),
        client.post(
            "/api/v1/files/move",
            headers=headers,
            json={"src_file_ids": [file_id], "dest_file_id": dest_id},
        ),
        client.post(
            "/api/v1/files/link-to-datasets",
            headers=headers,
            json={"file_ids": [file_id], "kb_ids": [dataset_id]},
        ),
    ]


def test_foreign_file_v024_refused_on_all_routes(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy plik z ``X-RAGFlow-Compat: 0.24`` → 108 na pięciu trasach (K16 §2 p. 3)."""
    token, _user_id = owner
    file_id = _upload(client, token)
    folder_id = client.post(
        "/api/v1/files", headers=_bearer(token), json={"name": "wd_e4a_v024_folder"}
    ).json()["data"]["id"]

    responses = _foreign_requests(client, _v024(bob_key), file_id, folder_id)

    for response in responses:
        assert response.status_code == _OK, response.text
        assert response.json() == _REFUSED_V024, response.text


def test_foreign_file_v027_refused_and_delete_errors(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy plik bez nagłówka → 102 ``no authorization``; ``DELETE`` zwraca ``errors`` (§D1.8)."""
    token, _user_id = owner
    file_id = _upload(client, token)
    folder_id = client.post(
        "/api/v1/files", headers=_bearer(token), json={"name": "wd_e4a_v027_folder"}
    ).json()["data"]["id"]

    responses = _foreign_requests(client, _bearer(bob_key), file_id, folder_id)
    deleted = client.request(
        "DELETE", "/api/v1/files", headers=_bearer(bob_key), json={"ids": [file_id]}
    )

    for response in responses:
        assert response.status_code == _OK, response.text
        assert response.json() == _REFUSED_V027, response.text
    assert deleted.status_code == _OK, deleted.text
    assert deleted.json() == {
        "code": _CODE_DATA_ERROR,
        "data": {
            "errors": [f"No authorization for file {file_id}"],
            "success_count": 0,
        },
        "message": "Deleted files failed with 1 errors",
    }


def test_own_folder_and_listing_v024_match_v027(client: TestClient, owner: tuple[str, str]) -> None:
    """Własny folder/listing/pobranie w 0.24 działają jak w 0.27 (ten sam kod tras)."""
    token, _user_id = owner
    created = client.post("/api/v1/files", headers=_v024(token), json={"name": "wd_e4a_v024_own"})
    assert created.status_code == _OK, created.text
    body = created.json()
    assert body["code"] == _CODE_SUCCESS, body
    folder_id = body["data"]["id"]
    assert set(body["data"]) == _CREATED_KEYS
    assert (body["data"]["type"], body["data"]["location"]) == ("folder", "")

    file_id = _upload(client, token, headers=_v024(token))
    listing = client.get("/api/v1/files", headers=_v024(token))
    downloaded = client.get(f"/api/v1/files/{file_id}", headers=_v024(token))

    assert listing.status_code == _OK, listing.text
    data = listing.json()["data"]
    assert data["parent_folder"]["name"] == "/"
    assert data["parent_folder"]["id"] in {item["parent_id"] for item in data["files"]}
    assert {item["id"] for item in data["files"]} == {folder_id, file_id}
    assert downloaded.status_code == _OK, downloaded.text
    assert downloaded.content == _FILE_BYTES
