"""``DELETE /api/v1/datasets`` w profilu zgodności 0.24 (brief E2-2a T1 p. 3-4).

Profil 0.24 odpowiada kopertą ``{"code": 0}`` bez ``data`` (złoto v0.24.0
``datasets/datasets_crud--05.json``), a puste ``ids`` bez ``delete_all:true`` jest no-opem
z ostrzeżeniem (02-api §7.3, Q14) — w przeciwieństwie do upstreamu v0.24, który takim
żądaniem usuwał wszystko. Profil 0.27 pozostaje bez zmian (``data.success_count``).

Fixture'y współdzielone z ``test_datasets_routes``: pytest rejestruje fixture pod nazwą
atrybutu w TYM module, a zależności rozwiązuje w łańcuchu tego modułu — stąd jawne
re-eksporty (wzorzec ``test_chats_v024``).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.ragflow.present.datasets import MSG_DELETE_NOTHING_V024
from tests.integration.api import test_datasets_routes as _routes

settings = _routes.settings
users_svc = _routes.users_svc
keys_svc = _routes.keys_svc
models_seeded = _routes.models_seeded
owner = _routes.owner
client = _routes.client

pytestmark = pytest.mark.db

_OK = 200
_CODE_SUCCESS = 0
_V024_COMPAT = "0.24"
_PAGE = {"page": 1, "page_size": 30}


def _v024(token: str) -> dict[str, str]:
    """Nagłówki klucza API wymuszające profil zgodności 0.24 (C7)."""
    return {"Authorization": f"Bearer {token}", "X-RAGFlow-Compat": _V024_COMPAT}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create(client: TestClient, token: str, name: str) -> str:
    """POST /datasets w profilu 0.24 z asercją sukcesu; zwraca identyfikator datasetu."""
    response = client.post("/api/v1/datasets", headers=_v024(token), json={"name": name})
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_SUCCESS, payload
    dataset_id: str = payload["data"]["id"]
    return dataset_id


def _names(client: TestClient, token: str) -> list[str]:
    """Nazwy datasetów z GET /datasets w profilu 0.24."""
    payload = client.get("/api/v1/datasets", headers=_v024(token), params=_PAGE).json()
    assert payload["code"] == _CODE_SUCCESS, payload
    return [row["name"] for row in payload["data"]]


def _delete(client: TestClient, token: str, body: dict[str, Any], **headers: str) -> Any:
    """DELETE /datasets; zwraca kopertę odpowiedzi (HTTP 200)."""
    response = client.request(
        "DELETE", "/api/v1/datasets", headers={**_v024(token), **headers}, json=body
    )
    assert response.status_code == _OK, response.text
    return response.json()


def test_delete_null_ids_v024_is_noop(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE {"ids": null} w profilu 0.24 nic nie usuwa i zwraca ostrzeżenie (02 §7.3)."""
    token, _user_id = owner
    _create(client, token, "wd_del_ds_a")
    _create(client, token, "wd_del_ds_b")

    payload = _delete(client, token, {"ids": None})
    assert payload["code"] == _CODE_SUCCESS
    assert payload["message"] == MSG_DELETE_NOTHING_V024
    assert "data" not in payload
    assert sorted(_names(client, token)) == ["wd_del_ds_a", "wd_del_ds_b"]


def test_delete_missing_ids_v024_is_noop(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE bez ``ids`` w profilu 0.24 też jest no-opem z ostrzeżeniem (Q14)."""
    token, _user_id = owner
    _create(client, token, "wd_del_ds_c")

    payload = _delete(client, token, {})
    assert payload["code"] == _CODE_SUCCESS
    assert payload["message"] == MSG_DELETE_NOTHING_V024
    assert _names(client, token) == ["wd_del_ds_c"]


def test_delete_by_ids_v024_envelope_has_no_data(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """DELETE {"ids": [...]} w profilu 0.24 → dokładnie ``{"code": 0}`` (złoto --05)."""
    token, _user_id = owner
    dataset_id = _create(client, token, "wd_del_ds_d")

    payload = _delete(client, token, {"ids": [dataset_id]})
    assert payload == {"code": _CODE_SUCCESS}
    assert _names(client, token) == []


def test_delete_all_v024_deletes_everything(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE {"delete_all": true} w profilu 0.24 usuwa wszystko (dotychczasowe zachowanie)."""
    token, _user_id = owner
    _create(client, token, "wd_del_ds_e")
    _create(client, token, "wd_del_ds_f")

    payload = _delete(client, token, {"delete_all": True})
    assert payload == {"code": _CODE_SUCCESS}
    assert _names(client, token) == []


def test_delete_by_ids_v027_envelope_unchanged(client: TestClient, owner: tuple[str, str]) -> None:
    """Profil 0.27 (bez nagłówka) zachowuje ``data.success_count`` (regresja C0 p. 1)."""
    token, _user_id = owner
    dataset_id = _create(client, token, "wd_del_ds_g")

    response = client.request(
        "DELETE", "/api/v1/datasets", headers=_bearer(token), json={"ids": [dataset_id]}
    )
    assert response.status_code == _OK, response.text
    assert response.json()["data"] == {"success_count": 1}
