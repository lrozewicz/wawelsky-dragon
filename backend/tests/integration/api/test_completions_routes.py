"""Testy HTTP tras completions (brief T4, rozstrzygnięcia 5 a-e; CONTRACT C6, R2)."""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.api.ragflow.sse import TERMINATOR
from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.domain.policy import Principal
from app.main import create_app
from tests.integration.chat.conftest import chat_with_doc, seed_chat
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

# Dokument o smoku wawelskim; pytanie zawiera jego słowa (tryb termowy, w=0.0).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_QUESTION = "Gdzie mieszkał smok wawelski?"
# Stała statusu HTTP (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_HTTP_OK = 200

GOLDEN = Path(__file__).parents[2] / "contract" / "golden" / "v0.27.2" / "chats___completions"


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (kopia z tests/integration/chat/conftest.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na życiu kontenerze (bez lifespan) z nadpisanym uwierzytelnianiem."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _frames(content: bytes) -> list[bytes]:
    """Ramki SSE: podział po b"\\n\n"; treść musi kończyć się TERMINATORem."""
    parts = content.split(b"\n\n")
    assert parts[-1] == b""
    return parts[:-1]


async def test_sse_stream_with_headers_and_frames(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(a) SSE: nagłówki, ramki data:, terminator, final z [ID:0], ids w każdej ramce."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    app = _app(container, principal_for(chat.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/chats/{chat.id}/completions", json={"question": _QUESTION}
        )
    assert resp.status_code == _HTTP_OK
    assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    frames = _frames(resp.content)
    assert frames[-1] + b"\n\n" == TERMINATOR
    for frame in frames:
        assert frame.startswith(b"data:")
    # K4 §1.2: ramka finalna niesie reference/prompt z answer="", tekst płynie deltami.
    final = json.loads(frames[-2][5:])["data"]
    assert final["final"] is True
    assert final["answer"] == ""
    assert final["reference"]["chunks"]
    streamed = "".join(json.loads(frame[5:])["data"]["answer"] for frame in frames[:-2])
    assert "[ID:0]" in streamed
    for frame in frames[:-1]:
        data = json.loads(frame[5:])["data"]
        assert data["session_id"]
        assert data["chat_id"] == chat.id


async def test_json_stream_false_matches_golden_keys(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(b) stream=False: koperta sukcesu, klucze data jak w złocie completion--08."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    app = _app(container, principal_for(chat.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/chats/{chat.id}/completions", json={"question": _QUESTION, "stream": False}
        )
    body = resp.json()
    assert body["code"] == RetCode.SUCCESS
    assert body["message"] == "success"
    golden = json.loads((GOLDEN / "completion--08.json").read_bytes())
    assert set(body["data"]) == set(golden["body"]["data"])
    assert isinstance(body["data"]["created_at"], float)
    assert body["data"]["audio_binary"] is None


async def test_empty_response_bytes_match_golden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(c) empty_response bajtowo: złoto completion--09 po podstawieniu id."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    chat = await seed_chat(
        sm,
        dataset.tenant_id,
        [dataset.id],
        prompt_config={},
        similarity_threshold=0.99,
        vector_similarity_weight=0.0,
    )
    app = _app(container, principal_for(chat.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/chats/{chat.id}/completions",
            json={"question": "Odpowiedź testowa: Output:"},
        )
    first = json.loads(_frames(resp.content)[0][5:])["data"]
    out = (
        resp.content.replace(first["id"].encode(), b"<ID:id#3>")
        .replace(first["session_id"].encode(), b"<ID:session#1>")
        .replace(chat.id.encode(), b"<ID:chat#1>")
    )
    assert out == (GOLDEN / "completion--09.sse").read_bytes()


async def test_restful_completions_stream_and_json(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(d) /chat/completions: SSE jak (a); stream=False z chat_id i solo (bez chat_id)."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    app = _app(container, principal_for(chat.tenant_id))
    messages = [{"role": "user", "content": _QUESTION}]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/completions", json={"chat_id": chat.id, "messages": messages}
        )
        assert resp.status_code == _HTTP_OK
        frames = _frames(resp.content)
        assert frames[-1] + b"\n\n" == TERMINATOR
        final = json.loads(frames[-2][5:])["data"]
        assert final["final"] is True
        assert final["chat_id"] == chat.id
        body = (
            await client.post(
                "/api/v1/chat/completions",
                json={"chat_id": chat.id, "messages": messages, "stream": False},
            )
        ).json()
        assert body["code"] == RetCode.SUCCESS
        assert body["data"]["chat_id"] == chat.id
        assert body["data"]["session_id"]
        solo = (
            await client.post(
                "/api/v1/chat/completions", json={"messages": messages, "stream": False}
            )
        ).json()
    assert solo["code"] == RetCode.SUCCESS
    assert "chat_id" not in solo["data"]


async def test_other_users_chat_denied_before_stream(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(e) cudzy czat (R2, K11 §10c p. 9): 109 przed strumieniem; brak sesji po próbie."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    stranger = principal_for(uuid.uuid4().hex)
    app = _app(container, stranger)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/chats/{chat.id}/completions", json={"question": _QUESTION}
        )
        assert resp.status_code == _HTTP_OK
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        # Koperta ``_ensure_owned_chat`` (upstream chat_api.py:190); złoto errors_access--33.
        assert body == {
            "code": RetCode.AUTHENTICATION_ERROR,
            "message": "no authorization",
            "data": False,
        }
        assert b"data:" not in resp.content
        body_json = await client.post(
            f"/api/v1/chats/{chat.id}/completions",
            json={"question": _QUESTION, "stream": False},
        )
        assert body_json.json() == body
        missing = await client.post(f"/api/v1/chats/{chat.id}/completions", json={})
    assert missing.json()["code"] == RetCode.ARGUMENT_ERROR
    assert missing.json()["message"] == "required argument are missing: messages"
    # Test negatywny: cudzy czat nie tworzy sesji (R2 — odmowa przed strumieniem).
    assert await session_count(sm, chat.id) == 0


# Profil zgodności jawny: ``CompatDep`` czyta nagłówek tylko dla principala klucza API (C7).
_V024_HEADER = {"X-RAGFlow-Compat": "0.24"}
_USER_MESSAGE = {"role": "user", "content": _QUESTION}


def _api_key_principal(user_id: str) -> Principal:
    """Principal klucza API — z ``auth_kind="jwt"`` nagłówek profilu byłby zignorowany (C7)."""
    return Principal(
        user_id,
        f"{user_id}@example.com",
        is_superuser=False,
        is_service=False,
        auth_kind="api_key",
    )


async def test_missing_chat_denied_like_stranger(container: Container) -> None:
    """Nieistniejący czat → 109 ``no authorization`` + ``data: false`` (DEC-092 p. 1).

    Upstream ``_ensure_owned_chat`` (chat_api.py:1266) nie odróżnia czatu nieistniejącego od
    cudzego; pre-check w trasie obejmuje oba warianty (``chat_id`` w ciele i w ścieżce).
    """
    app = _app(container, principal_for("whoever"))
    expected = {
        "code": RetCode.AUTHENTICATION_ERROR,
        "message": "no authorization",
        "data": False,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        path_variant = await client.post(
            "/api/v1/chats/missing-chat/completions",
            json={"question": _QUESTION, "stream": False},
        )
        body_variant = await client.post(
            "/api/v1/chat/completions",
            json={"chat_id": "missing-chat", "messages": [_USER_MESSAGE], "stream": False},
        )
    assert path_variant.status_code == _HTTP_OK
    assert path_variant.json() == expected
    assert body_variant.status_code == _HTTP_OK
    assert body_variant.json() == expected


async def test_missing_chat_v024_profiles(container: Container) -> None:
    """Profil 0.24: ``chats_completions`` odmawia jak upstream, ``chat_completions`` bez zmian.

    DEC-092 p. 1: pre-check jest tam, gdzie trasa ma wpis w ``PROFILES_V024`` (``chats_completions``
    → 102 „You don't own the chat <id>"); trasy ``chat_completions`` w v0.24 nie ma, więc zostaje
    przy dzisiejszym 102 „Chat not found!" z usługi.
    """
    app = _app(container, _api_key_principal("whoever"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        path_variant = await client.post(
            "/api/v1/chats/missing-chat/completions",
            json={"question": _QUESTION, "stream": False},
            headers=_V024_HEADER,
        )
        body_variant = await client.post(
            "/api/v1/chat/completions",
            json={"chat_id": "missing-chat", "messages": [_USER_MESSAGE], "stream": False},
            headers=_V024_HEADER,
        )
    assert path_variant.status_code == _HTTP_OK
    assert path_variant.json() == {
        "code": RetCode.DATA_ERROR,
        "message": "You don't own the chat missing-chat",
    }
    assert body_variant.status_code == _HTTP_OK
    assert body_variant.json() == {
        "code": RetCode.DATA_ERROR,
        "message": "Chat not found!",
        "data": None,
    }


async def session_count(sm: async_sessionmaker[AsyncSession], chat_id: str) -> int:
    """Liczba sesji czatu (test negatywny (e))."""
    async with sm() as session:
        return int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM chat_sessions WHERE chat_id = :id"), {"id": chat_id}
                )
            ).scalar_one()
        )
