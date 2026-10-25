"""Czat na modelu odrzucającym parametry generacji (brief T5, K10 poprawka 2026-10-04).

Model ``fake-chat-strict`` emuluje rodzinę GPT-5/o-series za bramką LiteLLM: 400, gdy ciało
zawiera ``presence_penalty``/``frequency_penalty`` albo ``temperature``/``top_p`` != 1.
Sprawdzamy cały stos (trasa HTTP → usługa czatu → bramka → fake-llm):

* domyślny ``llm_setting`` (kary doklejone z ``LLM_SETTING_FALLBACK``, zgodnie z upstream
  ``LLM_SETTING_DEFAULTS``) → 400 → jedno ponowienie bez nich → 200 z treścią;
* jawne kary (``*_penalty_enabled``) → tak samo;
* pamięć odrzuconych parametrów: drugie żądanie to JEDNO wywołanie fake-llm (licznik);
* trwały 400 (inny niż ``UnsupportedParams``) → ``LLM bad request: <przyczyna>``
  w ramce błędu SSE i w polu ``message`` odpowiedzi JSON.
"""

import json

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.api.ragflow.sse import TERMINATOR
from app.core.container import Container
from app.core.error_codes import RetCode
from app.db.repositories.chats import ChatRow
from app.domain.chat.events import ErrorEvent, Final
from app.domain.policy import Principal
from app.llm.openai_gateway import OpenAIGateway
from app.main import create_app
from app.services.chat import CompletionRequest
from tests.integration.chat.conftest import (
    collect,
    register_strict_model,
    seed_chat,
    seed_user,
)
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

# Dokument o smoku wawelskim; pytanie zawiera jego słowa (tryb termowy, w=0.0).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_QUESTION = "Gdzie mieszkał smok wawelski?"
_MODEL = "fake-chat-strict"
_HTTP_OK = 200
# Żądania do fake-llm: pierwsze na modelu to 400 + ponowienie, kolejne już bez ponowienia.
_FIRST_REQUEST_CALLS = 2
_REMEMBERED_CALLS = 1
# Trwały 400 inny niż ``UnsupportedParams`` (bramka nie wskazuje parametrów do pominięcia).
_PERSISTENT_400 = {
    "error": {
        "message": "invalid_request_error: context window exceeded",
        "type": "invalid_request_error",
        "code": "400",
    }
}


def _req(chat_id: str, question: str) -> CompletionRequest:
    """CompletionRequest jednego pytania user (K4 §3.3, jak w testach scenariuszy)."""
    return CompletionRequest(
        chat_id=chat_id,
        session_id=None,
        messages=({"role": "user", "content": question},),
    )


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na życiu kontenerze (bez lifespan) z nadpisanym uwierzytelnianiem."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _frames(content: bytes) -> list[bytes]:
    """Ramki SSE: podział po b\"\\n\\n\"; treść musi kończyć się TERMINATORem."""
    parts = content.split(b"\n\n")
    assert parts[-1] == b""
    return parts[:-1]


def _streamed_answer(frames: list[bytes]) -> str:
    """Treść odpowiedzi z delt SSE (ramka finalna ma ``answer: ""``)."""
    return "".join(json.loads(frame[5:])["data"]["answer"] for frame in frames[:-2])


async def _seed_strict_chat(container: Container, sm: async_sessionmaker[AsyncSession]) -> ChatRow:
    """Dataset z dokumentem + czat na ``fake-chat-strict`` (tryb termowy, w=0.0)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    return await seed_chat(
        sm,
        dataset.tenant_id,
        [dataset.id],
        llm_id=_MODEL,
        similarity_threshold=0.0,
        vector_similarity_weight=0.0,
    )


async def _chat_requests(container: Container) -> int:
    """Licznik żądań ``POST /v1/chat/completions`` dla ``fake-chat-strict`` (K10, T3)."""
    url = f"{container.settings.llm_base_url.rstrip('/')}/fake/stats"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    response.raise_for_status()
    return int(response.json()["chat_completions"].get(_MODEL, 0))


async def test_default_llm_setting_streams_answer(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(a) stream: domyślny ``llm_setting`` (kary z fallbacku) → 400 → ponowienie → 200."""
    chat = await _seed_strict_chat(container, sm)
    await register_strict_model(sm)
    app = _app(container, principal_for(chat.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/chats/{chat.id}/completions", json={"question": _QUESTION}
        )
    assert response.status_code == _HTTP_OK
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    frames = _frames(response.content)
    assert frames[-1] + b"\n\n" == TERMINATOR
    assert "[ID:0]" in _streamed_answer(frames), "ponowienie bez kar dało treść"


async def test_default_llm_setting_json_answer(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(a) nie-stream: domyślny ``llm_setting`` → 200 i niepusta treść w JSON."""
    chat = await _seed_strict_chat(container, sm)
    await register_strict_model(sm)
    app = _app(container, principal_for(chat.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/chats/{chat.id}/completions",
            json={"question": _QUESTION, "stream": False},
        )
    assert response.status_code == _HTTP_OK
    body = response.json()
    assert body["code"] == RetCode.SUCCESS
    assert "[ID:0]" in body["data"]["answer"]


async def test_enabled_penalties_still_answer(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(b) jawne kary w żądaniu (``*_penalty_enabled=true``) → 200 i treść."""
    chat = await _seed_strict_chat(container, sm)
    await register_strict_model(sm)
    app = _app(container, principal_for(chat.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/chats/{chat.id}/completions",
            json={
                "question": _QUESTION,
                "stream": False,
                "presence_penalty": 0.4,
                "presence_penalty_enabled": True,
                "frequency_penalty": 0.7,
                "frequency_penalty_enabled": True,
            },
        )
    assert response.status_code == _HTTP_OK
    body = response.json()
    assert body["code"] == RetCode.SUCCESS
    assert body["data"]["answer"], "odpowiedź po ponowieniu bez kar"


async def test_second_request_has_no_retry(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(c) pamięć odrzuconych parametrów: drugie żądanie to JEDNO wywołanie fake-llm."""
    chat = await _seed_strict_chat(container, sm)
    await register_strict_model(sm)
    principal = principal_for(chat.tenant_id)
    before = await _chat_requests(container)
    first = await collect(await container.chat.start(principal, _req(chat.id, _QUESTION)))
    assert any(isinstance(event, Final) for event in first)
    after_first = await _chat_requests(container)
    assert after_first - before == _FIRST_REQUEST_CALLS, "400 + jedno ponowienie"
    second = await collect(await container.chat.start(principal, _req(chat.id, _QUESTION)))
    assert any(isinstance(event, Final) for event in second)
    after_second = await _chat_requests(container)
    assert after_second - after_first == _REMEMBERED_CALLS, "parametry zapamiętane per model"


async def test_persistent_400_reaches_sse_and_json(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(d) trwały 400 (nie o parametrach) → ``LLM bad request: <przyczyna>`` w SSE i JSON."""
    container.llm = OpenAIGateway(
        container.settings,
        sessionmaker=container.sessionmaker,
        clock=container.clock,
        transport=httpx2.MockTransport(lambda request: httpx2.Response(400, json=_PERSISTENT_400)),
    )
    # Czat bez datasetów: brak retrievalu, więc bramka robi wyłącznie wywołanie czatu.
    tenant = await seed_user(sm)
    chat = await seed_chat(sm, tenant, [])
    principal = principal_for(tenant)
    events = await collect(await container.chat.start(principal, _req(chat.id, _QUESTION)))
    error = events[-1]
    assert isinstance(error, ErrorEvent)
    assert error.message.startswith("LLM bad request: ")
    assert "context window exceeded" in error.message
    app = _app(container, principal)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/chats/{chat.id}/completions",
            json={"question": _QUESTION, "stream": False},
        )
    assert response.status_code == _HTTP_OK
    body = response.json()
    assert body["code"] == RetCode.CONNECTION_ERROR
    assert body["message"] == error.message
