"""Test odchyłki profilu 0.24: ``keywords`` w ``/file/list`` filtruje tylko bezpośrednie dzieci.

Upstream v0.24.0 (``FileService.get_by_pf_id``) szuka ``keywords`` wśród dzieci listowanego
folderu (``parent_id == pf_id``); poddrzewo (CTE) pojawiło się dopiero w 0.27.2. Trasa
``routes/file_legacy_v024.list_files`` zawęża wynik usługi w trasie, więc podfolder pasujący do
słowa kluczowego, ale zagnieżdżony, nie może wyciec do listingu (złoto ``file_legacy--07``).

Wzór ``test_file_legacy_v024_ops.py``: klucz API + ``X-RAGFlow-Compat: 0.24``; fixture'y
zakładamy trasami v0.27 ``/api/v1/files``.
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


def _v024(token: str) -> dict[str, str]:
    """Nagłówki klucza API wymuszające profil zgodności 0.24 (C7)."""
    return {"Authorization": f"Bearer {token}", "X-RAGFlow-Compat": _V024}


def _folder(client: TestClient, token: str, name: str, parent_id: str | None = None) -> str:
    """POST /files (JSON, v0.27 — narzędzie) z asercją sukcesu; zwraca id folderu."""
    payload: dict[str, Any] = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/api/v1/files", headers=headers, json=payload)
    assert response.status_code == _OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    folder_id: str = body["data"]["id"]
    return folder_id


def _list(client: TestClient, token: str, **params: str) -> dict[str, Any]:
    """GET /file/list w profilu 0.24 z asercją sukcesu; zwraca ``data``."""
    response = client.get("/api/v1/file/list", headers=_v024(token), params=params)
    assert response.status_code == _OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    return body["data"]


def test_list_keywords_returns_direct_children_only(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """Zagnieżdżony podfolder pasujący do keywords NIE występuje w listingu roota (§D4)."""
    token, _user_id = owner
    folder_id = _folder(client, token, "wd_e4b_t4_kw_folder")
    _sub_id = _folder(client, token, "wd_e4b_t4_kw_folder_sub", folder_id)

    data = _list(client, token, keywords="wd_e4b_t4_kw_folder")

    assert data["total"] == 1
    assert [item["id"] for item in data["files"]] == [folder_id]


def test_list_keywords_scoped_to_listed_folder(client: TestClient, owner: tuple[str, str]) -> None:
    """Ten sam keywords w liście folderu zwraca jego bezpośrednie dziecko (podfolder)."""
    token, _user_id = owner
    folder_id = _folder(client, token, "wd_e4b_t4_kw_scope")
    sub_id = _folder(client, token, "wd_e4b_t4_kw_scope_sub", folder_id)

    data = _list(client, token, parent_id=folder_id, keywords="wd_e4b_t4_kw_scope")

    assert data["total"] == 1
    assert [item["id"] for item in data["files"]] == [sub_id]
