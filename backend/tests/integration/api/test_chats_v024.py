"""Trasy czatu i sesji w profilu zgodności 0.24 (brief E2-2b T5; CONTRACT C4).

Ten sam kod tras obsługuje dwa profile wybrane nagłówkiem ``X-RAGFlow-Compat`` (C7): bez
nagłówka działa kształt v0.27, z ``0.24`` koperty i kształty złota ``v0.24.0``. Testy idą
przez prawdziwe klucze API dwóch użytkowników (wzorzec ``test_refusals_v024.py``), bo profil
bierze się z nagłówka dopiero po ustaleniu podmiotu z klucza.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.uow import transaction
from tests.integration.api import test_refusals_v024 as _refusals

# Fixture'y współdzielone z ``test_refusals_v024``: pytest rejestruje fixture pod nazwą
# atrybutu w TYM module, a zależności (settings, users_svc…) rozwiązuje w łańcuchu tego
# modułu — stąd jawne re-eksporty (wzorzec ``test_dataset_ingestions_routes``).
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
_CODE_DATA_ERROR = 102
_V024_COMPAT = "0.24"
# Złoto v0.24.0 chats/chat_session--01.json: domyślny prolog asystenta.
_DEFAULT_OPENER = "Hi! I'm your assistant. What can I do for you?"
# Wartości z ciała żądania w teście tłumaczenia (brief p. 6d).
_KEYWORDS_WEIGHT = 0.7
_TEMPERATURE = 0.5


def _v024(token: str) -> dict[str, str]:
    """Nagłówki klucza API wymuszające profil zgodności 0.24 (C7)."""
    return {"Authorization": f"Bearer {token}", "X-RAGFlow-Compat": _V024_COMPAT}


def _data(response: Any) -> Any:
    """``data`` koperty sukcesu (HTTP 200, code 0)."""
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_SUCCESS, payload
    return payload["data"]


def create_chat(client: TestClient, token: str, **body: Any) -> dict[str, Any]:
    """POST /chats w profilu 0.24 z asercją sukcesu; zwraca ``data``."""
    data: dict[str, Any] = _data(
        client.post("/api/v1/chats", headers=_v024(token), json={"dataset_ids": [], **body})
    )
    return data


def _chat_items(client: TestClient, token: str) -> list[dict[str, Any]]:
    """Elementy listy czatów w profilu 0.24 (``data`` jest listą, nie kopertą)."""
    listing = _data(client.get("/api/v1/chats?page=1&page_size=100", headers=_v024(token)))
    assert isinstance(listing, list)
    return listing


async def _bump_dataset_chunks(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> None:
    """``chunk_count = 1`` wprost SQL-em: czat wymaga datasetu po parsowaniu (C2.1), a TestClient
    nie uruchamia workera (wzorzec ``test_dataset_ingestions_routes.py``)."""
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET chunk_count = 1 WHERE id = :id"), {"id": dataset_id}
        )


def test_put_chat_v024_returns_code_only(client: TestClient, owner: tuple[str, str]) -> None:
    """PUT /chats/{id} w 0.24 → 200, ``code`` 0 i brak ``data``; lista pokazuje nową nazwę (C4)."""
    token, _user_id = owner
    chat = create_chat(client, token, name="wd_v024_put")
    response = client.put(
        f"/api/v1/chats/{chat['id']}", headers=_v024(token), json={"name": "renamed"}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == _CODE_SUCCESS
    assert "data" not in body
    renamed = [item for item in _chat_items(client, token) if item["id"] == chat["id"]]
    assert renamed[0]["name"] == "renamed"


def test_patch_chat_v024_keeps_full_detail(client: TestClient, owner: tuple[str, str]) -> None:
    """PATCH czatu w 0.24 bez zmian (C4: „PATCH bez zmian") — pełny szczegół z ``data``."""
    token, _user_id = owner
    chat = create_chat(client, token, name="wd_v024_patch")
    response = client.patch(
        f"/api/v1/chats/{chat['id']}", headers=_v024(token), json={"description": "nowy opis"}
    )
    assert response.status_code == _OK
    data = _data(response)
    assert data["id"] == chat["id"]
    assert data["description"] == "nowy opis"
    assert data["avatar"] == chat["avatar"]


def test_put_chat_v024_duplicated_name_message(client: TestClient, owner: tuple[str, str]) -> None:
    """Zajęta nazwa w PUT 0.24 → 102 z komunikatem złota (``chats___/chat_extras--22.json``)."""
    token, _user_id = owner
    create_chat(client, token, name="wd_v024_taken")
    chat = create_chat(client, token, name="wd_v024_other")
    response = client.put(
        f"/api/v1/chats/{chat['id']}", headers=_v024(token), json={"name": "wd_v024_taken"}
    )
    assert response.status_code == _OK
    assert response.json() == {
        "code": _CODE_DATA_ERROR,
        "message": "Duplicated chat name in updating chat.",
    }


def test_put_chat_v024_foreign_chat_refused(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """PUT cudzego czatu w 0.24 → 102 „You do not own the chat" i zasób nietknięty (C4)."""
    token, _user_id = owner
    chat = create_chat(client, token, name="wd_v024_foreign")
    response = client.put(
        f"/api/v1/chats/{chat['id']}", headers=_v024(bob_key), json={"name": "intruder"}
    )
    assert response.status_code == _OK
    assert response.json() == {"code": _CODE_DATA_ERROR, "message": "You do not own the chat"}
    mine = [item for item in _chat_items(client, token) if item["id"] == chat["id"]]
    assert mine[0]["name"] == "wd_v024_foreign"


async def test_list_chats_v024_shape(
    client: TestClient, owner: tuple[str, str], sm: async_sessionmaker[AsyncSession]
) -> None:
    """GET /chats w 0.24: lista z ``datasets`` (bez ``dataset_ids``) i ``prompt.opener`` (C2)."""
    token, _user_id = owner
    dataset = _data(
        client.post("/api/v1/datasets", headers=_v024(token), json={"name": "wd_v024_ds"})
    )
    await _bump_dataset_chunks(sm, dataset["id"])
    chat = create_chat(client, token, name="wd_v024_list", dataset_ids=[dataset["id"]])
    assert chat["dataset_ids"] == [dataset["id"]]
    item = next(entry for entry in _chat_items(client, token) if entry["id"] == chat["id"])
    assert "avatar" in item
    assert item["prompt"]["opener"] == _DEFAULT_OPENER
    assert isinstance(item["datasets"], list)
    assert "dataset_ids" not in item
    assert item["datasets"][0]["id"] == dataset["id"]


def test_create_chat_v024_body_translated(client: TestClient, owner: tuple[str, str]) -> None:
    """POST /chats w 0.24 tłumaczy ciało v0.24 i oddaje kształt v0.24 (C1/C2)."""
    token, _user_id = owner
    data = create_chat(
        client,
        token,
        name="c",
        avatar="a.png",
        prompt={"opener": "Hi", "keywords_similarity_weight": _KEYWORDS_WEIGHT},
        llm={"temperature": _TEMPERATURE},
    )
    assert data["avatar"] == "a.png"
    assert data["prompt"]["opener"] == "Hi"
    assert data["prompt"]["keywords_similarity_weight"] == _KEYWORDS_WEIGHT
    assert data["llm"]["temperature"] == _TEMPERATURE


def test_session_rename_v024_code_only(client: TestClient, owner: tuple[str, str]) -> None:
    """PUT sesji w 0.24 → sam ``code`` 0, a lista sesji pokazuje nową nazwę (C4)."""
    token, _user_id = owner
    chat = create_chat(client, token, name="wd_v024_session")
    session = _data(
        client.post(
            f"/api/v1/chats/{chat['id']}/sessions", headers=_v024(token), json={"name": "s1"}
        )
    )
    response = client.put(
        f"/api/v1/chats/{chat['id']}/sessions/{session['id']}",
        headers=_v024(token),
        json={"name": "s2"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == _CODE_SUCCESS
    assert "data" not in body
    sessions = _data(client.get(f"/api/v1/chats/{chat['id']}/sessions", headers=_v024(token)))
    assert [item["name"] for item in sessions] == ["s2"]
