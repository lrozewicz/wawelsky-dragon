"""Trasy wyszukiwarek w profilu zgodności 0.24 (brief E4-4a T5; K15 §2 p. 6, CONTRACT §D5).

W v0.24.0 upstream nie ma żadnej trasy ``/api/v1/searches*`` (legacy ``search_app.py`` to
``/v1/search/*`` i cały scenariusz jest tam pomijany), więc nie istnieje złoto ani mapa
``PROFILES_V024`` dla tych tras. Nagłówek ``X-RAGFlow-Compat: 0.24`` na ``PUT``/``DELETE``
kompletion z cudzym zasobem wybiera więc ``PROFILES_V024``, w której klucza nie ma — ``refuse``
zwraca wtedy 108 (``PermissionDenied``) zamiast 109 ``no authorization`` (§D5, „brak wpisu
w PROFILES_V024 → 108"). Własny CRUD nie zależy od profilu i działa jak w v0.27.

Testy idą przez prawdziwe klucze API dwóch użytkowników (wzorzec ``test_refusals_v024.py``,
``test_chats_v024.py``) — profil bierze się z nagłówka dopiero po ustaleniu podmiotu.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.api import test_refusals_v024 as _refusals

# Fixture'y współdzielone z ``test_refusals_v024`` (re-eksport jak w ``test_chats_v024``).
settings = _refusals.settings
users_svc = _refusals.users_svc
keys_svc = _refusals.keys_svc
models_seeded = _refusals.models_seeded
owner = _refusals.owner
bob_key = _refusals.bob_key
client = _refusals.client

pytestmark = pytest.mark.db

_OK = 200
_CODE_SUCCESS = 0
_CODE_LACK_PERMISSION = 108
_V024_COMPAT = "0.24"
_NO_AUTHORIZATION = "no authorization"

# Klucze pełnego wiersza ``PUT`` ze złota v0.27.2 ``searches___/searches--15.json`` (§D5).
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


def _v024(token: str) -> dict[str, str]:
    """Nagłówki klucza API wymuszające profil zgodności 0.24 (C7)."""
    return {"Authorization": f"Bearer {token}", "X-RAGFlow-Compat": _V024_COMPAT}


def create_search(client: TestClient, token: str, name: str = "wd_e4a_v024") -> dict[str, Any]:
    """POST /searches w profilu 0.24 z asercją sukcesu; zwraca ``data``."""
    response = client.post("/api/v1/searches", headers=_v024(token), json={"name": name})
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_SUCCESS, payload
    return payload["data"]


def _detail(client: TestClient, token: str, search_id: str) -> dict[str, Any]:
    """GET /searches/{id} z asercją sukcesu; zwraca ``data``."""
    response = client.get(f"/api/v1/searches/{search_id}", headers=_v024(token))
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_SUCCESS, payload
    data: dict[str, Any] = payload["data"]
    return data


def test_put_foreign_search_v024_refused_and_untouched(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy PUT w 0.24 → 108 (brak klucza w ``PROFILES_V024``); zasób nietknięty."""
    token, _user_id = owner
    search_id = create_search(client, token, "wd_e4a_v024_cudza_put")["search_id"]
    response = client.put(
        f"/api/v1/searches/{search_id}",
        headers=_v024(bob_key),
        json={"name": "wd_e4a_v024_intruder", "search_config": {}},
    )
    assert response.status_code == _OK
    assert response.json() == {
        "code": _CODE_LACK_PERMISSION,
        "message": _NO_AUTHORIZATION,
        "data": None,
    }
    assert _detail(client, token, search_id)["name"] == "wd_e4a_v024_cudza_put"


def test_delete_foreign_search_v024_refused_and_untouched(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy DELETE w 0.24 → 108 (brak klucza w ``PROFILES_V024``); zasób nadal istnieje."""
    token, _user_id = owner
    search_id = create_search(client, token, "wd_e4a_v024_cudza_delete")["search_id"]
    response = client.delete(f"/api/v1/searches/{search_id}", headers=_v024(bob_key))
    assert response.status_code == _OK
    assert response.json() == {
        "code": _CODE_LACK_PERMISSION,
        "message": _NO_AUTHORIZATION,
        "data": None,
    }
    assert _detail(client, token, search_id)["id"] == search_id


def test_own_crud_v024_matches_v027(client: TestClient, owner: tuple[str, str]) -> None:
    """Własny PUT/DELETE w 0.24 działa jak w v0.27 (pełny wiersz §D5, ``data: true``)."""
    token, _user_id = owner
    search_id = create_search(client, token, "wd_e4a_v024_wlasna")["search_id"]
    updated = client.put(
        f"/api/v1/searches/{search_id}",
        headers=_v024(token),
        json={"name": "wd_e4a_v024_zmieniona", "search_config": {}, "description": "opis"},
    )
    assert updated.status_code == _OK
    body = updated.json()
    assert body["code"] == _CODE_SUCCESS, body
    assert set(body["data"]) == _FULL_KEYS
    assert body["data"]["name"] == "wd_e4a_v024_zmieniona"
    assert body["data"]["description"] == "opis"
    deleted = client.delete(f"/api/v1/searches/{search_id}", headers=_v024(token))
    assert deleted.status_code == _OK
    assert deleted.json() == {"code": _CODE_SUCCESS, "message": "success", "data": True}
