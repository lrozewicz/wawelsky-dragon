"""Testy HTTP tras /api/v1/chats/{chat_id}/sessions (brief T3b; CONTRACT C6, R2, R5)."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories import chat_sessions as chat_sessions_repo
from app.db.repositories.chat_messages import MessageRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from tests.integration.chat.conftest import TIME_MS, seed_user
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

# Status HTTP sukcesu (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_HTTP_OK = 200


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (wzorzec test_chats_routes.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na życiu kontenerze (bez lifespan) z nadpisanym uwierzytelnianiem."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (wzorzec test_chats_routes.py)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create_chat(client: httpx.AsyncClient) -> str:
    """Tworzy czat przez POST /chats i zwraca jego id."""
    resp = await client.post("/api/v1/chats", json={"name": "wd", "dataset_ids": []})
    assert resp.status_code == _HTTP_OK
    assert resp.json()["code"] == RetCode.SUCCESS
    chat_id: str = resp.json()["data"]["id"]
    return chat_id


async def _create_session(
    client: httpx.AsyncClient, chat_id: str, name: str = "s"
) -> dict[str, Any]:
    """Tworzy sesję przez POST /chats/{chat_id}/sessions i zwraca kopertę data."""
    resp = await client.post(f"/api/v1/chats/{chat_id}/sessions", json={"name": name})
    assert resp.status_code == _HTTP_OK
    assert resp.json()["code"] == RetCode.SUCCESS
    return resp.json()["data"]


async def test_create_session_prologue_and_empty_name(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST: prologue assistant + user_id principalu; pusta nazwa → 102."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        chat_id = await _create_chat(client)
        data = await _create_session(client, chat_id)
        assert data["messages"][0]["role"] == "assistant"
        assert data["user_id"] == principal.user_id
        assert data["reference"] == []
        empty = await client.post(f"/api/v1/chats/{chat_id}/sessions", json={"name": ""})
    assert empty.json()["code"] == RetCode.DATA_ERROR
    assert empty.json()["message"] == "`name` can not be empty"


async def test_list_page_size_zero_and_default(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """GET listy: page_size=0 → []; bez parametrów → 1 sesja."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        chat_id = await _create_chat(client)
        await _create_session(client, chat_id)
        zero = await client.get(f"/api/v1/chats/{chat_id}/sessions?page_size=0")
        assert zero.json()["data"] == []
        default = await client.get(f"/api/v1/chats/{chat_id}/sessions")
    assert len(default.json()["data"]) == 1


async def test_get_session_avatar_and_missing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """GET jednej sesji: data ma avatar; nieistniejąca → 102 „Session not found!”."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        chat_id = await _create_chat(client)
        session = await _create_session(client, chat_id)
        got = await client.get(f"/api/v1/chats/{chat_id}/sessions/{session['id']}")
        assert got.json()["code"] == RetCode.SUCCESS
        assert "avatar" in got.json()["data"]
        missing = await client.get(f"/api/v1/chats/{chat_id}/sessions/brak")
    assert missing.json()["code"] == RetCode.DATA_ERROR
    assert missing.json()["message"] == "Session not found!"


@pytest.mark.parametrize("method", ["PATCH", "PUT"])
async def test_rename_methods(
    container: Container, sm: async_sessionmaker[AsyncSession], method: str
) -> None:
    """PATCH i PUT: zmiana nazwy; wiadomości zmieniać nie wolno (102)."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        chat_id = await _create_chat(client)
        session = await _create_session(client, chat_id)
        renamed = await client.request(
            method, f"/api/v1/chats/{chat_id}/sessions/{session['id']}", json={"name": "n2"}
        )
        assert renamed.json()["data"]["name"] == "n2"
        rejected = await client.request(
            method, f"/api/v1/chats/{chat_id}/sessions/{session['id']}", json={"messages": []}
        )
    assert rejected.json()["code"] == RetCode.DATA_ERROR
    assert rejected.json()["message"] == "`messages` cannot be changed"


async def test_delete_many_cases(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DELETE: [s] → data=true; [brak] → 102; częściowy → success_count+errors; {} → {}."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        chat_id = await _create_chat(client)
        session = await _create_session(client, chat_id)
        single = await client.request(
            "DELETE", f"/api/v1/chats/{chat_id}/sessions", json={"ids": [session["id"]]}
        )
        assert single.json() == {"code": 0, "message": "success", "data": True}
        other = await _create_session(client, chat_id, name="s2")
        partial = await client.request(
            "DELETE", f"/api/v1/chats/{chat_id}/sessions", json={"ids": ["brak", other["id"]]}
        )
        assert partial.json()["code"] == RetCode.SUCCESS
        assert partial.json()["data"] == {
            "success_count": 1,
            "errors": ["The chat doesn't own the session brak"],
        }
        missing = await client.request(
            "DELETE", f"/api/v1/chats/{chat_id}/sessions", json={"ids": ["brak"]}
        )
        assert missing.json()["code"] == RetCode.DATA_ERROR
        assert missing.json()["message"] == "The chat doesn't own the session brak"
        empty = await client.request("DELETE", f"/api/v1/chats/{chat_id}/sessions", json={})
    assert empty.json()["data"] == {}


async def test_list_stranger_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Obcy principal na liście sesji cudzego czatu → 109 „no authorization" (złoto --29)."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        chat_id = await _create_chat(client)
        await _create_session(client, chat_id)
    stranger_app = _app(container, principal_for(uuid.uuid4().hex))
    async with _client(stranger_app) as stranger:
        denied = await stranger.get(f"/api/v1/chats/{chat_id}/sessions")
    assert denied.json() == {
        "code": RetCode.AUTHENTICATION_ERROR,
        "message": "no authorization",
        "data": False,
    }


async def test_missing_chat_denied_like_stranger(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak czatu na trasach sesji → 109 „no authorization" (złoto --46; DEC-091 p. 1).

    Upstream ``_ensure_owned_chat`` jest pierwszą instrukcją każdej trasy sesji i nie odróżnia
    czatu nieistniejącego od cudzego (``chat_api.py:836/920/949``); WD oddaje tę samą kopertę.
    """
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        created = await client.post("/api/v1/chats/brak/sessions", json={"name": "s"})
        listed = await client.get("/api/v1/chats/brak/sessions")
        renamed = await client.request(
            "PATCH", "/api/v1/chats/brak/sessions/brak", json={"name": "s"}
        )
        deleted = await client.request(
            "DELETE", "/api/v1/chats/brak/sessions", json={"ids": ["brak"]}
        )
    denied = {"code": RetCode.AUTHENTICATION_ERROR, "message": "no authorization", "data": False}
    assert created.json() == denied
    assert listed.json() == denied
    assert renamed.json() == denied
    assert deleted.json() == denied


async def _seed_pair(sm: async_sessionmaker[AsyncSession], session_id: str) -> str:
    """Wstawia parę user+assistant do sesji; zwraca id pary (asystenta, E2-1 CHAT)."""
    async with transaction(sm) as session:
        for seq, role, message_id in ((1, "user", "u" * 32), (2, "assistant", "a" * 32)):
            await chat_messages_repo.insert(
                session,
                MessageRow(
                    id=message_id,
                    session_id=session_id,
                    seq=seq,
                    role=role,  # type: ignore[arg-type]
                    content=f"treść {role}",
                    reference={"chunks": [{"id": "c1"}], "doc_aggs": []},
                    prompt_tokens=None,
                    completion_tokens=None,
                    created_at=1.0 + seq,
                    create_time=TIME_MS,
                ),
            )
        await chat_sessions_repo.bump(session, session_id, added=2, now_ms=TIME_MS)
    return "a" * 32


async def test_message_feedback_and_delete_routes(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT feedback i DELETE wiadomości (E2-1 CHAT, chat_api.py:1000 i :1025)."""
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        chat_id = await _create_chat(client)
        session = await _create_session(client, chat_id)
        pair_id = await _seed_pair(sm, session["id"])
        feedback = await client.put(
            f"/api/v1/chats/{chat_id}/sessions/{session['id']}/messages/{pair_id}/feedback",
            json={"thumbup": True, "feedback": "wd_rec thumbup"},
        )
        assert feedback.status_code == _HTTP_OK
        assert feedback.json()["code"] == RetCode.SUCCESS
        # GET zwraca parę z jednym id i oceną na odpowiedzi (złoto chat_extras--12).
        got = await client.get(f"/api/v1/chats/{chat_id}/sessions/{session['id']}")
        messages = got.json()["data"]["messages"]
        assert [message["id"] for message in messages[1:]] == [pair_id, pair_id]
        assert messages[2]["thumbup"] is True
        deleted = await client.request(
            "DELETE", f"/api/v1/chats/{chat_id}/sessions/{session['id']}/messages/{pair_id}"
        )
        assert deleted.json()["code"] == RetCode.SUCCESS
        assert [message["role"] for message in deleted.json()["data"]["messages"]] == ["assistant"]
        # Brak pary o tym id → bez zmian, koperta sesji.
        missing = await client.request(
            "DELETE", f"/api/v1/chats/{chat_id}/sessions/{session['id']}/messages/{'b' * 32}"
        )
        assert missing.json()["code"] == RetCode.SUCCESS
        assert len(missing.json()["data"]["messages"]) == 1
        bad = await client.put(
            f"/api/v1/chats/{chat_id}/sessions/{session['id']}/messages/{pair_id}/feedback",
            json={"thumbup": "tak"},
        )
    # Nie-bool thumbup: upstream ``get_data_error_result`` → HTTP 200, code 102 (chat_api.py:1038).
    assert bad.status_code == _HTTP_OK
    assert bad.json()["code"] == RetCode.DATA_ERROR
    assert bad.json()["message"] == "thumbup must be a boolean"


@pytest.mark.fakellm
async def test_recommendation_routes(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST /chat/recommendation i alias /sessions/related_questions na fake-llm (E2-1 CHAT).

    Fake-llm po poprawce K10 (2026-10-01) zwraca 3 pytania pokrewne — te same linie ``^[0-9]\\. ``,
    które upstream parsuje z odpowiedzi modelu.
    """
    principal = principal_for(await seed_user(sm))
    async with _client(_app(container, principal)) as client:
        canonical = await client.post("/api/v1/chat/recommendation", json={"question": "smok"})
        alias = await client.post("/api/v1/sessions/related_questions", json={"question": "smok"})
        missing = await client.post("/api/v1/chat/recommendation", json={})
    assert canonical.json() == {
        "code": 0,
        "message": "success",
        "data": [
            "Pytanie pokrewne pierwsze",
            "Pytanie pokrewne drugie",
            "Pytanie pokrewne trzecie",
        ],
    }
    assert alias.json() == canonical.json()
    assert missing.json()["code"] == RetCode.ARGUMENT_ERROR
