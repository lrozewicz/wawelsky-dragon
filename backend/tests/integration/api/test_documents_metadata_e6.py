"""Testy HTTP filtrów metadanych dokumentów i trasy S-320 (K11 §10f p. 1-2, złoto E6).

Wzorzec: ``tests/integration/api/test_dataset_metadata_routes.py`` (TestClient, ``mark.db``).
Pokrywają kroki grupy A złota ``metadata_e6`` (13-39): ``metadata_condition`` zawęża ``total``
i listę ``GET …/documents`` (każdy operator tabeli §1a oraz quirki: nieznany operator = 0,
``year = 2020`` int = 0, brak ``value`` przy ``empty`` = 100 ``KeyError('value')``, zły JSON = 102),
oraz trasę ``PUT …/documents/{id}/metadata/config`` (S-320) wraz z odmowami (101/102).
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.api import test_datasets_routes as _api_tests
from tests.integration.api.test_datasets_routes import _bearer, create_dataset

# Fixture'y współdzielone z ``test_datasets_routes`` (re-eksport pod nazwami oryginałów).
settings = _api_tests.settings
users_svc = _api_tests.users_svc
keys_svc = _api_tests.keys_svc
models_seeded = _api_tests.models_seeded
owner = _api_tests.owner
alice_key = _api_tests.alice_key
client = _api_tests.client

pytestmark = pytest.mark.db

_OK = 200
_ARGUMENT_ERROR = 101
_DATA_ERROR = 102
_EXCEPTION_ERROR = 100

# Metadane trzech dokumentów złota (``e6_meta_a/b/c.txt``, golden-E6 §1a).
_META = {
    "a.txt": {"author": "A", "year": "2020", "topic": "rag", "note": "alpha"},
    "b.txt": {"author": "B", "year": "2021", "topic": "web", "note": ""},
    "c.txt": {"author": "A", "year": "2022", "topic": "rag", "note": "gamma"},
}
_SCHEMA = {
    "type": "object",
    "properties": {
        "author": {"type": "string", "description": "Autor dokumentu"},
        "year": {"type": "number", "description": "Rok publikacji"},
    },
}


def _c(name: str, op: str, value: Any = None) -> dict[str, Any]:
    """Pojedynczy warunek ``metadata_condition`` (klucz ``value`` obecny, gdy jest podany)."""
    condition: dict[str, Any] = {"name": name, "comparison_operator": op}
    if value is not None:
        condition["value"] = value
    return condition


def _condition(logic: str, *conditions: dict[str, Any]) -> str:
    """JSON-string ``metadata_condition`` (upstream: query, nie ciało; DOC:1066)."""
    return json.dumps({"logic": logic, "conditions": list(conditions)})


def _seed_documents(client: TestClient, token: str) -> str:
    """Dataset + trzy dokumenty z metadanymi złota; zwraca id datasetu."""
    dataset_id = str(create_dataset(client, token, {"name": "wd_meta_e6"})["id"])
    for name, meta in _META.items():
        upload = client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            files={"file": (name, b"smok wawelski", "text/plain")},
            headers=_bearer(token),
        )
        assert upload.status_code == _OK and upload.json()["code"] == 0, upload.text
        document_id = upload.json()["data"][0]["id"]
        patched = client.patch(
            f"/api/v1/datasets/{dataset_id}/documents/{document_id}",
            json={"meta_fields": meta},
            headers=_bearer(token),
        )
        assert patched.status_code == _OK and patched.json()["code"] == 0, patched.text
    return dataset_id


def _list(client: TestClient, token: str, dataset_id: str, condition: str) -> dict[str, Any]:
    """GET …/documents z ``metadata_condition``; zwraca ``data`` (docs + total)."""
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={
            "page": 1,
            "page_size": 30,
            "orderby": "name",
            "desc": "false",
            "metadata_condition": condition,
        },
    )
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    data: dict[str, Any] = payload["data"]
    return data


def _doc_id(client: TestClient, token: str, dataset_id: str, name: str) -> str:
    """Identyfikator dokumentu o nazwie ``name`` w datasecie."""
    payload = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={"page": 1, "page_size": 30},
    ).json()
    return str(next(doc["id"] for doc in payload["data"]["docs"] if doc["name"] == name))


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (_condition("and", _c("author", "=", "A")), {"a.txt", "c.txt"}),
        (_condition("and", _c("author", "=", "A"), _c("year", "=", "2020")), {"a.txt"}),
        (_condition("or", _c("author", "=", "B"), _c("year", "=", "2022")), {"b.txt", "c.txt"}),
        (_condition("and", _c("author", "!=", "A")), {"b.txt"}),
        (_condition("and", _c("year", ">", "2020")), {"b.txt", "c.txt"}),
        (_condition("and", _c("year", "<", "2022")), {"a.txt", "b.txt"}),
        (_condition("and", _c("year", ">=", "2021")), {"b.txt", "c.txt"}),
        (_condition("and", _c("year", "<=", "2021")), {"a.txt", "b.txt"}),
        (_condition("and", _c("topic", "contains", "ag")), {"a.txt", "c.txt"}),
        (_condition("and", _c("topic", "not contains", "ag")), {"b.txt"}),
        (_condition("and", _c("author", "in", ["A", "B"])), {"a.txt", "b.txt", "c.txt"}),
        (_condition("and", _c("author", "not in", ["A"])), {"b.txt"}),
        (_condition("and", _c("topic", "start with", "ra")), {"a.txt", "c.txt"}),
        (_condition("and", _c("topic", "end with", "eb")), {"b.txt"}),
        (_condition("and", _c("note", "empty", "")), {"b.txt"}),
        (_condition("and", _c("note", "not empty", "")), {"a.txt", "c.txt"}),
        (_condition("and", _c("author", "bogus", "A")), set()),
        (_condition("and", _c("author", "=", "Z")), set()),
        (_condition("and", _c("year", "=", 2020)), set()),
    ],
)
async def test_list_documents_metadata_condition(
    client: TestClient, owner: tuple[str, str], condition: str, expected: set[str]
) -> None:
    """``metadata_condition`` zawęża ``total`` i listę dokumentów (kroki 14-33 złota)."""
    token, _user_id = owner
    dataset_id = _seed_documents(client, token)
    data = _list(client, token, dataset_id, condition)
    assert data["total"] == len(expected)
    assert {doc["name"] for doc in data["docs"]} == expected


async def test_list_documents_empty_missing_value(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """``empty`` bez klucza ``value`` → 200/100 ``KeyError('value')`` (krok 30 złota)."""
    token, _user_id = owner
    dataset_id = _seed_documents(client, token)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={
            "page": 1,
            "page_size": 30,
            "metadata_condition": _condition("and", _c("note", "empty")),
        },
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _EXCEPTION_ERROR
    assert payload["message"] == "KeyError('value')"


async def test_list_documents_bad_json(client: TestClient, owner: tuple[str, str]) -> None:
    """Zły JSON ``metadata_condition`` → 102 bez klucza ``data`` (krok 34 złota)."""
    token, _user_id = owner
    dataset_id = _seed_documents(client, token)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={"page": 1, "page_size": 30, "metadata_condition": "not-json"},
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert payload["message"] == "metadata_condition must be valid JSON: not-json."
    assert "data" not in payload


async def test_document_metadata_config_success(client: TestClient, owner: tuple[str, str]) -> None:
    """PUT …/documents/{id}/metadata/config → 200/0 i ``parser_config.metadata`` (kroki 35-36)."""
    token, _user_id = owner
    dataset_id = _seed_documents(client, token)
    doc_id = _doc_id(client, token, dataset_id, "a.txt")
    response = client.put(
        f"/api/v1/datasets/{dataset_id}/documents/{doc_id}/metadata/config",
        json={"metadata": _SCHEMA},
        headers=_bearer(token),
    )
    assert response.status_code == _OK, response.text
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["parser_config"]["metadata"] == _SCHEMA
    # Skutek czytany przez GET ?id= (krok 36).
    listed = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={"id": doc_id},
    ).json()
    assert listed["data"]["docs"][0]["parser_config"]["metadata"] == _SCHEMA


async def test_document_metadata_config_missing_metadata(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """Brak pola ``metadata`` → 200/101 „metadata is required" (krok 37 złota)."""
    token, _user_id = owner
    dataset_id = _seed_documents(client, token)
    doc_id = _doc_id(client, token, dataset_id, "a.txt")
    response = client.put(
        f"/api/v1/datasets/{dataset_id}/documents/{doc_id}/metadata/config",
        json={},
        headers=_bearer(token),
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _ARGUMENT_ERROR
    assert payload["message"] == "metadata is required"
    assert "data" not in payload


async def test_document_metadata_config_missing_document(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """Nieistniejący dokument → 200/102 „document <id> not found in dataset <id>" (krok 38)."""
    token, _user_id = owner
    dataset_id = _seed_documents(client, token)
    phantom = "0" * 32
    response = client.put(
        f"/api/v1/datasets/{dataset_id}/documents/{phantom}/metadata/config",
        json={"metadata": {}},
        headers=_bearer(token),
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert payload["message"] == f"document {phantom} not found in dataset {dataset_id}"


async def test_document_metadata_config_second_user(
    client: TestClient, owner: tuple[str, str], alice_key: str
) -> None:
    """Cudzy dataset → 200/102 „you don't own the dataset" (krok 39 złota)."""
    token, _user_id = owner
    dataset_id = _seed_documents(client, token)
    doc_id = _doc_id(client, token, dataset_id, "a.txt")
    response = client.put(
        f"/api/v1/datasets/{dataset_id}/documents/{doc_id}/metadata/config",
        json={"metadata": {}},
        headers=_bearer(alice_key),
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert payload["message"] == "you don't own the dataset"
