"""Testy HTTP tras metadanych datasetu (zadanie DS3, E2-1).

Wzorzec: ``tests/integration/api/test_dataset_ingestions_routes.py`` (TestClient, ``mark.db``).
Sprawdzają kształty złota ``datasets___metadata__config/--11,--12``,
``datasets___metadata__summary/--15,--17``, ``datasets___metadata__update/--16``
i ``datasets__metadata__flattened/--18`` oraz odmowę dla cudzego datasetu (K11 §10c p. 10).
Ścieżka łańcucha metadanych jest jak w scenariuszu: konfiguracja → ``meta_fields`` dokumentu
(PATCH) → podsumowanie → masowa zmiana → podsumowanie → spłaszczenie.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.uow import transaction
from tests.integration.api import test_datasets_routes as _api_tests
from tests.integration.api.test_datasets_routes import _bearer, create_dataset

# Fixture'y współdzielone z ``test_datasets_routes``: pytest rejestruje fixture pod nazwą
# atrybutu w TYM module, a zależności (settings, users_svc…) rozwiązuje w łańcuchu tego
# modułu — stąd jawne re-eksporty pod nazwami oryginałów.
settings = _api_tests.settings
users_svc = _api_tests.users_svc
keys_svc = _api_tests.keys_svc
models_seeded = _api_tests.models_seeded
owner = _api_tests.owner
alice_key = _api_tests.alice_key
client = _api_tests.client

pytestmark = pytest.mark.db

_OK = 200
_PERMISSION_ERROR = 108
_DATA_ERROR = 102
_ARGUMENT_ERROR = 101  # RetCode.ARGUMENT_ERROR (K3): złe ciało żądania
_GOLDEN = Path(__file__).resolve().parents[3] / "tests" / "contract" / "golden" / "v0.27.2"
_DOC_NAME = "ragflow_intro.txt"
_DOC_TEXT = "Legenda o smoku wawelskim należy do najstarszych opowieści Krakowa. " * 4
_AUTHOR = "wd_rec_e2"
_AUTHOR_UPDATED = "wd_rec_e2_updated"
_CONFIG = {
    "metadata": [
        {"key": "author", "type": "string", "description": "Author name"},
        {
            "key": "tags",
            "type": "list",
            "description": "Tag list",
            "enum": ["foo", "bar"],
        },
    ],
    "built_in_metadata": [{"key": "size", "type": "number", "description": "File size"}],
}


def _golden_data(relative: str) -> dict[str, Any]:
    """``body.data`` pliku złota (wzorzec: test_datasets_routes)."""
    loaded: dict[str, Any] = json.loads((_GOLDEN / relative).read_text(encoding="utf-8"))["body"][
        "data"
    ]
    return loaded


def _data(response: Any) -> dict[str, Any]:
    """``data`` z koperty sukcesu (code 0) z asercją HTTP 200."""
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    data: dict[str, Any] = payload["data"]
    return data


def _seed_dataset(client: TestClient, token: str) -> tuple[str, str]:
    """Dataset + dokument z metadanymi scenariusza (``meta_fields`` z kroku 14)."""
    dataset_id = str(create_dataset(client, token, {"name": "wd_meta_ds"})["id"])
    upload = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        files={"file": (_DOC_NAME, _DOC_TEXT.encode("utf-8"), "text/plain")},
        headers=_bearer(token),
    )
    document_id = str(_data(upload)[0]["id"])
    patched = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/{document_id}",
        json={"meta_fields": {"tags": ["foo", "bar"], "author": _AUTHOR}},
        headers=_bearer(token),
    )
    assert patched.status_code == _OK and patched.json()["code"] == 0, patched.text
    return dataset_id, document_id


async def _meta_fields(sm: async_sessionmaker[AsyncSession], document_id: str) -> dict[str, Any]:
    """``documents.meta_fields`` prosto z bazy (dowód „metadane nietknięte")."""
    async with transaction(sm) as session:
        raw = (
            await session.execute(
                text("SELECT meta_fields FROM documents WHERE id = :id"), {"id": document_id}
            )
        ).scalar_one()
    return json.loads(raw) if isinstance(raw, str) else raw


async def test_metadata_config_get_empty(client: TestClient, owner: tuple[str, str]) -> None:
    """GET …/metadata/config na świeżym datasecie → puste listy (złoto --11)."""
    token, _user_id = owner
    dataset_id = str(create_dataset(client, token, {"name": "wd_meta_cfg"})["id"])
    data = _data(
        client.get(f"/api/v1/datasets/{dataset_id}/metadata/config", headers=_bearer(token))
    )
    assert data == _golden_data("datasets___metadata__config/datasets_extras--11.json")


async def test_metadata_config_put_roundtrip(client: TestClient, owner: tuple[str, str]) -> None:
    """PUT …/metadata/config → echo walidacji (--12) i ta sama konfiguracja w GET."""
    token, _user_id = owner
    dataset_id = str(create_dataset(client, token, {"name": "wd_meta_cfg_put"})["id"])
    url = f"/api/v1/datasets/{dataset_id}/metadata/config"
    data = _data(client.put(url, json=_CONFIG, headers=_bearer(token)))
    assert data == _golden_data("datasets___metadata__config/datasets_extras--12.json")
    assert _data(client.get(url, headers=_bearer(token))) == data
    record = _data(client.get(f"/api/v1/datasets/{dataset_id}", headers=_bearer(token)))
    assert record["parser_config"]["metadata"] == data["metadata"]
    assert record["parser_config"]["built_in_metadata"] == data["built_in_metadata"]


async def test_metadata_config_put_strips_key_whitespace(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """PUT …/metadata/config obcina białe znaki ``key`` (upstream AutoMetadataField, FIXA p. 3a).

    ``StringConstraints(strip_whitespace=True)`` obowiązuje przed ``min_length``, więc
    ``" autor "`` zapisuje się jako ``"autor"`` — w echu, w GET i w ``parser_config`` datasetu.
    """
    token, _user_id = owner
    dataset_id = str(create_dataset(client, token, {"name": "wd_meta_cfg_strip"})["id"])
    url = f"/api/v1/datasets/{dataset_id}/metadata/config"
    body = {
        "metadata": [{"key": "  author\t", "type": "string", "description": "Author"}],
        "built_in_metadata": [{"key": " size ", "type": "number"}],
    }
    data = _data(client.put(url, json=body, headers=_bearer(token)))
    assert data["metadata"][0]["key"] == "author"
    assert data["built_in_metadata"][0]["key"] == "size"
    assert _data(client.get(url, headers=_bearer(token))) == data
    record = _data(client.get(f"/api/v1/datasets/{dataset_id}", headers=_bearer(token)))
    assert record["parser_config"]["metadata"][0]["key"] == "author"


async def test_metadata_config_put_blank_key_rejected(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """Klucz z samych białych znaków po obcięciu jest pusty → code 101 (upstream min_length=1).

    Przed obcinaniem ``min_length=1`` przepuszczał ``"   "`` (długość 3) — to właśnie różnica
    względem upstreamu ``AutoMetadataField`` (FIXA p. 3a).
    """
    token, _user_id = owner
    dataset_id = str(create_dataset(client, token, {"name": "wd_meta_cfg_blank"})["id"])
    response = client.put(
        f"/api/v1/datasets/{dataset_id}/metadata/config",
        json={"metadata": [{"key": "   ", "type": "string"}], "built_in_metadata": []},
        headers=_bearer(token),
    )
    assert response.status_code == _OK, response.text
    assert response.json()["code"] == _ARGUMENT_ERROR


async def test_metadata_summary_golden_shape(client: TestClient, owner: tuple[str, str]) -> None:
    """GET …/metadata/summary → agregacja ``meta_fields`` dokumentu (złoto --15)."""
    token, _user_id = owner
    dataset_id, _document_id = _seed_dataset(client, token)
    data = _data(
        client.get(f"/api/v1/datasets/{dataset_id}/metadata/summary", headers=_bearer(token))
    )
    assert data == _golden_data("datasets___metadata__summary/datasets_extras--15.json")


async def test_metadata_update_and_summary(client: TestClient, owner: tuple[str, str]) -> None:
    """POST …/metadata/update → 1/1 (--16), a podsumowanie pokazuje nową wartość (--17)."""
    token, _user_id = owner
    dataset_id, document_id = _seed_dataset(client, token)
    data = _data(
        client.post(
            f"/api/v1/datasets/{dataset_id}/metadata/update",
            json={
                "selector": {"document_ids": [document_id]},
                "updates": [{"key": "author", "value": _AUTHOR_UPDATED}],
                "deletes": [],
            },
            headers=_bearer(token),
        )
    )
    assert data == _golden_data("datasets___metadata__update/datasets_extras--16.json")
    summary = _data(
        client.get(f"/api/v1/datasets/{dataset_id}/metadata/summary", headers=_bearer(token))
    )
    assert summary == _golden_data("datasets___metadata__summary/datasets_extras--17.json")


async def test_metadata_flattened_golden_shape(client: TestClient, owner: tuple[str, str]) -> None:
    """GET /datasets/metadata/flattened?dataset_ids=… → {pole: {wartość: [id]}} (złoto --18)."""
    token, _user_id = owner
    dataset_id, document_id = _seed_dataset(client, token)
    assert (
        _data(
            client.post(
                f"/api/v1/datasets/{dataset_id}/metadata/update",
                json={
                    "selector": {"document_ids": [document_id]},
                    "updates": [{"key": "author", "value": _AUTHOR_UPDATED}],
                    "deletes": [],
                },
                headers=_bearer(token),
            )
        )["updated"]
        == 1
    )
    data = _data(
        client.get(
            "/api/v1/datasets/metadata/flattened",
            params={"dataset_ids": dataset_id},
            headers=_bearer(token),
        )
    )
    assert data == {
        "author": {_AUTHOR_UPDATED: [document_id]},
        "tags": {"bar": [document_id], "foo": [document_id]},
    }
    golden = _golden_data("datasets__metadata__flattened/datasets_extras--18.json")
    assert sorted(data) == sorted(golden)


def test_metadata_flattened_without_dataset_ids(client: TestClient, owner: tuple[str, str]) -> None:
    """Brak ``dataset_ids`` → code 102 „Lack of dataset_ids in query parameters" (upstream:59)."""
    token, _user_id = owner
    response = client.get("/api/v1/datasets/metadata/flattened", headers=_bearer(token))
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert payload["message"] == "Lack of dataset_ids in query parameters"


async def test_metadata_update_foreign_dataset_refused(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str], alice_key: str
) -> None:
    """Cudzy dataset: odmowa (108) i metadane NIETKNIĘTE (K11 §10c p. 10)."""
    token, _user_id = owner
    dataset_id, document_id = _seed_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/metadata/update",
        json={
            "selector": {"document_ids": [document_id]},
            "updates": [{"key": "author", "value": "obcy"}],
            "deletes": [],
        },
        headers=_bearer(alice_key),
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _PERMISSION_ERROR
    assert payload["message"] == f"You don't own the dataset {dataset_id}."
    assert await _meta_fields(sm, document_id) == {"tags": ["foo", "bar"], "author": _AUTHOR}
    summary = _data(
        client.get(f"/api/v1/datasets/{dataset_id}/metadata/summary", headers=_bearer(token))
    )
    assert summary["summary"]["author"]["values"] == [[_AUTHOR, 1]]


async def test_metadata_update_foreign_document_refused(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """Dokument spoza datasetu → code 102 z komunikatem upstream i brak zapisu."""
    token, _user_id = owner
    dataset_id, document_id = _seed_dataset(client, token)
    other_dataset_id = str(create_dataset(client, token, {"name": "wd_meta_other"})["id"])
    other = client.post(
        f"/api/v1/datasets/{other_dataset_id}/documents",
        files={"file": ("other.txt", b"inny dokument", "text/plain")},
        headers=_bearer(token),
    )
    outside_id = str(_data(other)[0]["id"])
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/metadata/update",
        json={
            "selector": {"document_ids": [document_id, outside_id]},
            "updates": [{"key": "author", "value": "x"}],
            "deletes": [],
        },
        headers=_bearer(token),
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    expected = f"These documents do not belong to dataset {dataset_id}: {outside_id}"
    assert payload["message"] == expected
    assert await _meta_fields(sm, document_id) == {"tags": ["foo", "bar"], "author": _AUTHOR}


async def test_metadata_update_by_metadata_condition(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """``selector.metadata_condition`` zawęża ``document_ids`` (upstream: przecięcie zbiorów).

    Warunek sam (bez ``document_ids``) nie wybiera nic — upstream bierze
    ``set(document_ids) & filtered_ids``, więc bez listy identyfikatorów zbiór jest pusty;
    test sprawdza oba przypadki: zgodny warunek zmienia dokument, niezgodny nie zmienia.
    """
    token, _user_id = owner
    dataset_id, document_id = _seed_dataset(client, token)
    url = f"/api/v1/datasets/{dataset_id}/metadata/update"

    def _update(condition_value: str) -> dict[str, Any]:
        return _data(
            client.post(
                url,
                json={
                    "selector": {
                        "document_ids": [document_id],
                        "metadata_condition": {
                            "logic": "and",
                            "conditions": [
                                {
                                    "name": "author",
                                    "comparison_operator": "is",
                                    "value": condition_value,
                                }
                            ],
                        },
                    },
                    "updates": [{"key": "author", "value": _AUTHOR_UPDATED}],
                    "deletes": [],
                },
                headers=_bearer(token),
            )
        )

    assert _update("inny") == {"matched_docs": 0, "updated": 0}
    assert await _meta_fields(sm, document_id) == {"tags": ["foo", "bar"], "author": _AUTHOR}
    assert _update(_AUTHOR) == {"matched_docs": 1, "updated": 1}
    assert await _meta_fields(sm, document_id) == {
        "tags": ["foo", "bar"],
        "author": _AUTHOR_UPDATED,
    }


async def test_team_dataset_metadata_writes_require_owner(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str], alice_key: str
) -> None:
    """Dataset ``permission: team``: obcy uwierzytelniony NIE zapisuje metadanych (UPDATE≠READ).

    Polityka (``can``): dla datasetu „team" READ/USE ma każdy, zapis tylko właściciel —
    dlatego trasy zapisu muszą żądać ``Action.UPDATE``. Sprawdza trzy trasy zapisu:
    ``PUT …/metadata/config``, ``POST …/metadata/update`` i ``PATCH …/documents/metadatas``.
    """
    token, _user_id = owner
    dataset_id, document_id = _seed_dataset(client, token)
    shared = client.put(
        f"/api/v1/datasets/{dataset_id}", json={"permission": "team"}, headers=_bearer(token)
    )
    assert _data(shared)["permission"] == "team"
    written = client.put(
        f"/api/v1/datasets/{dataset_id}/metadata/config", json=_CONFIG, headers=_bearer(alice_key)
    )
    updated = client.post(
        f"/api/v1/datasets/{dataset_id}/metadata/update",
        json={
            "selector": {"document_ids": [document_id]},
            "updates": [{"key": "author", "value": "obcy"}],
            "deletes": [],
        },
        headers=_bearer(alice_key),
    )
    patched = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/metadatas",
        json={
            "selector": {"document_ids": [document_id]},
            "updates": [{"key": "author", "value": "obcy"}],
            "deletes": [],
        },
        headers=_bearer(alice_key),
    )
    for response in (written, updated, patched):
        assert response.status_code == _OK
        assert response.json()["code"] == _PERMISSION_ERROR, response.text
    assert await _meta_fields(sm, document_id) == {"tags": ["foo", "bar"], "author": _AUTHOR}
