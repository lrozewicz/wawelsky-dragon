"""Ścieżka hub-compat: klucz z profilem `ragflow_0_24`, bez nagłówka zgodności (brief E2-2b T7).

Ten sam kod tras obsługuje dwa profile zgodności; profil wybiera `get_compat_profile`
(C7) — dla klucza API bez nagłówka `X-RAGFlow-Compat` bierze zapisany `compat_profile`
klucza (K11 §10d). Testy idą przez PRAWDZIWE klucze (klucz z profilem założony usługą,
nie nadpisany nagłówkiem), żeby udowodnić integrację hub-compat: `GET /chats` zwraca listę
v0.24 (`data[]`, `datasets[].id`), completion bez sesji ją zakłada (AG-06, AG-07),
a wiadomości asystenta noszą referencje (C0 p. 4, C3).

Uwaga do wymagania 3 briefu: element `reference` wiadomości asystenta w v0.24 ma
dokładnie 7 kluczy portu upstream `list_session` (C3, `present/references.py`
``chunk_reference_v024``) — `id, content, document_id, document_name, dataset_id,
image_id, positions`; NIE ma `similarity` (to klucz referencji completion, nie sesji;
pilnuje tego `tests/unit/api/ragflow/test_present_sessions_v024.py`).
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.main import create_app
from tests.integration.chat.conftest import chat_with_doc
from tests.integration.ingest.pipeline_helpers import make_container

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

_OK = 200
_CODE_SUCCESS = 0
# 32 zera: czat nieistniejący (AG-08) — odmowa kopertą, nie `{detail}`.
_MISSING_CHAT = "0" * 32
# Profil zgodności zapisany na kluczu (C7); bez nagłówka X-RAGFlow-Compat.
_COMPAT_V024 = "ragflow_0_24"
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
_OWNER_EMAIL = "hub-compat-owner@x.pl"

# Dokument o smoku wawelskim; pytanie zawiera jego słowa (tryb termowy, w=0.0).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_QUESTION = "Gdzie mieszkał smok wawelski?"
# Klucze ChunkReference wiadomości sesji v0.24 (C3; `chunk_reference_v024`) — dokładnie 7.
_SESSION_CHUNK_KEYS = {
    "id",
    "content",
    "document_id",
    "document_name",
    "dataset_id",
    "image_id",
    "positions",
}


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Ustawienia auth + storage w katalogu tymczasowym."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
async def container(settings: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (modele fake, storage w tmp_path)."""
    instance = await make_container(settings, tmp_path)
    yield instance
    await instance.aclose()


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    """Aplikacja na tym samym kontenerze co test (bez sieci, ASGITransport)."""
    return create_app(settings, container)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient ASGI (bez X-RAGFlow-Compat — profil bierze się z klucza)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def owner(container: Container) -> tuple[str, str]:
    """Konto + klucz API z `compat_profile=ragflow_0_24`; zwraca (token, user_id)."""
    assert container.users is not None
    assert container.api_keys is not None
    user = await container.users.create(email=_OWNER_EMAIL, password=PASSWORD, is_superuser=False)
    key = await container.api_keys.create(
        container.users.principal_of(user), compat_profile=_COMPAT_V024
    )
    return key.token, user.id


@pytest.fixture
async def chat(
    container: Container, sm: async_sessionmaker[AsyncSession], owner: tuple[str, str]
) -> tuple[str, str]:
    """Czat z jednym datasetem po ingestii; zwraca (chat_id, dataset_id) dla użytkownika `owner`."""
    _token, user_id = owner
    row, dataset, _doc = await chat_with_doc(container, sm, _DOC, owner=user_id)
    return row.id, dataset.id


def _h(token: str) -> dict[str, str]:
    """Nagłówki klucza API; `Content-Type` także przy GET (A9)."""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _data(response: httpx.Response) -> Any:
    """``data`` koperty sukcesu (HTTP 200, code 0)."""
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_SUCCESS, payload
    return payload["data"]


async def _sessions(client: httpx.AsyncClient, token: str, chat_id: str) -> list[dict[str, Any]]:
    """Sesje czatu (v0.24: ``data`` to lista)."""
    listable = _data(
        await client.get(
            f"/api/v1/chats/{chat_id}/sessions?page=1&page_size=100", headers=_h(token)
        )
    )
    assert isinstance(listable, list)
    return listable


async def test_ag06_list_chats_is_list_with_opener_datasets_avatar(
    client: httpx.AsyncClient, owner: tuple[str, str], chat: tuple[str, str]
) -> None:
    """AG-06: `GET /chats` z klucza 0.24 → `data` lista; element ma opener/datasets[].id."""
    chat_id, dataset_id = chat
    listing = _data(await client.get("/api/v1/chats?page=1&page_size=100", headers=_h(owner[0])))
    assert isinstance(listing, list)
    item = next(entry for entry in listing if entry["id"] == chat_id)
    assert isinstance(item["prompt"]["opener"], str)
    assert isinstance(item["avatar"], str)
    assert item["datasets"][0]["id"] == dataset_id
    assert "dataset_ids" not in item


async def test_ag07_completion_without_session_creates_session(
    client: httpx.AsyncClient, owner: tuple[str, str], chat: tuple[str, str]
) -> None:
    """AG-07: completion bez `session_id` zakłada sesję i oddaje jej id (C0 p. 5)."""
    chat_id, _dataset_id = chat
    data = _data(
        await client.post(
            f"/api/v1/chats/{chat_id}/completions",
            headers=_h(owner[0]),
            json={"question": _QUESTION, "stream": False},
        )
    )
    session_id = data["session_id"]
    assert session_id
    assert isinstance(data["reference"]["chunks"], list)
    listed = await _sessions(client, owner[0], chat_id)
    assert session_id in [entry["id"] for entry in listed]


async def test_session_list_v024_references_on_assistant_message(
    client: httpx.AsyncClient, owner: tuple[str, str], chat: tuple[str, str]
) -> None:
    """C3: referencje trafiają do wiadomości asystenta, prolog bez `reference` (7 kluczy)."""
    chat_id, _dataset_id = chat
    session_id = _data(
        await client.post(
            f"/api/v1/chats/{chat_id}/sessions", headers=_h(owner[0]), json={"name": "refs"}
        )
    )["id"]
    _data(
        await client.post(
            f"/api/v1/chats/{chat_id}/completions",
            headers=_h(owner[0]),
            json={"question": _QUESTION, "stream": False, "session_id": session_id},
        )
    )
    session = next(
        entry for entry in await _sessions(client, owner[0], chat_id) if entry["id"] == session_id
    )
    assert "reference" not in session
    assert session["messages"][0]["role"] == "assistant"
    assert "reference" not in session["messages"][0]
    answer = next(
        message
        for message in session["messages"][1:]
        if message["role"] == "assistant" and message.get("reference")
    )
    chunks = answer["reference"]
    assert isinstance(chunks, list) and chunks
    assert set(chunks[0]) == _SESSION_CHUNK_KEYS


async def test_session_user_id_and_ms_update_time(
    client: httpx.AsyncClient, owner: tuple[str, str], chat: tuple[str, str]
) -> None:
    """A3/A5: `user_id` z ciała żądania trafia do sesji, `update_time` w milisekundach."""
    chat_id, _dataset_id = chat
    created = _data(
        await client.post(
            f"/api/v1/chats/{chat_id}/sessions",
            headers=_h(owner[0]),
            json={"name": "s", "user_id": "ai@hub.test"},
        )
    )
    assert created["user_id"] == "ai@hub.test"
    listed = await _sessions(client, owner[0], chat_id)
    session = next(entry for entry in listed if entry["id"] == created["id"])
    assert isinstance(session["update_time"], int)
    assert session["update_time"] > 10**12


async def test_ag08_errors_are_http_200_with_code(
    client: httpx.AsyncClient, owner: tuple[str, str]
) -> None:
    """AG-08: brakujący czat → HTTP 200 i `code != 0`, nigdy koperta `{detail}`."""
    response = await client.post(
        f"/api/v1/chats/{_MISSING_CHAT}/completions",
        headers=_h(owner[0]),
        json={"question": _QUESTION, "stream": False},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] != _CODE_SUCCESS
    assert "detail" not in body


async def test_profile_from_key_does_not_change_other_key(
    client: httpx.AsyncClient, container: Container, owner: tuple[str, str]
) -> None:
    """Regresja: drugi klucz bez profilu (0.27) dalej dostaje `data.chats`."""
    assert container.users is not None
    assert container.api_keys is not None
    plain = await container.api_keys.create(
        container.users.principal_of(await container.users.get_by_email(_OWNER_EMAIL))
    )
    data = _data(await client.get("/api/v1/chats?page=1&page_size=100", headers=_h(plain.token)))
    assert isinstance(data, dict)
    assert isinstance(data["chats"], list)
    # Klucz z profilem 0.24 (ten sam użytkownik) widzi te same czaty jako listę.
    v024 = _data(await client.get("/api/v1/chats?page=1&page_size=100", headers=_h(owner[0])))
    assert isinstance(v024, list)
