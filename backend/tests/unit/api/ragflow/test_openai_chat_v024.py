"""Testy kształtu OpenAI-compat w profilu v0.24 (CONTRACT E2-2b C0 p. 7, brief T4 p. 5).

Ramki SSE OpenAI są bajtowo zgodne ze złotem ``openai_compat--03.sse`` (bez spacji po ``data:``).
``meta.model`` = „model” daje bajty v0.24, ``meta.model`` = id modelu czatu daje bajty v0.27.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.api.auth.principal import get_principal
from app.api.ragflow.compat import get_compat_profile
from app.api.ragflow.present.openai_chat import (
    DONE_FRAME,
    CompletionMeta,
    completion_json,
    sse_chunks,
)
from app.api.ragflow.routes import openai_chat
from app.domain.chat.events import AnswerDelta, ChatEvent, Final, StreamIds
from app.domain.policy import Principal
from app.services.chat import ChatStream, CompletionResult

META_V024 = CompletionMeta(id="chatcmpl-c1", model="model", created=1)
META_V027 = CompletionMeta(id="chatcmpl-c1", model="MODEL0", created=1)
REASONING_TOKENS = 6  # wartość ``reasoning_tokens`` z goldenu openai_compat--02.json

# Oczekiwana ramka treści — dosłownie złoto openai_compat--03.sse (klucze i kolejność).
# ``model`` = wartość z ``meta`` (podmieniana w teście v0.27).
FRAME_CONTENT = (
    b'data:{"id":"chatcmpl-c1","choices":[{"delta":{"content":"Hej","role":"assistant",'
    b'"function_call":null,"tool_calls":null,"reasoning_content":null},"finish_reason":null,'
    b'"index":0,"logprobs":null}],"created":1,"model":"model","object":"chat.completion.chunk",'
    b'"system_fingerprint":"","usage":null}\n\n'
)


async def _gen(events: tuple[ChatEvent, ...]) -> AsyncIterator[ChatEvent]:
    for event in events:
        yield event


async def _frames(meta: CompletionMeta, prompt: str = "") -> list[bytes]:
    return [
        frame async for frame in sse_chunks(_gen((AnswerDelta("Hej"),)), meta=meta, prompt=prompt)
    ]


async def test_content_frame_v024_bytes_match_golden() -> None:
    """Pierwsza ramka v0.24 == złoto: klucze chunku w kolejności, ``usage: null``."""
    frames = await _frames(META_V024)
    assert frames[0] == FRAME_CONTENT


async def test_frame_has_no_space_after_data_prefix() -> None:
    """v0.24: po ``data:`` nie ma spacji (złoto ``openai_compat--03.sse``, ``od -c``).

    Terminator ``data:[DONE]`` nie jest ramką JSON — sprawdzamy ramki chunku.
    """
    frames = await _frames(META_V024)
    chunks = [frame for frame in frames if frame != DONE_FRAME]
    assert chunks and all(frame.startswith(b"data:{") for frame in chunks)
    assert b"data: " not in b"".join(frames)


async def test_final_frame_and_terminator_match_golden() -> None:
    """Ostatnie ramki: chunek z ``finish_reason: stop`` i ``usage``, potem ``data:[DONE]``."""
    frames = await _frames(META_V024)
    final = frames[-2]
    assert final.startswith(b'data:{"id":"chatcmpl-c1","choices":[{"delta":{"content":null,')
    assert b'"finish_reason":"stop","index":0,"logprobs":null}' in final
    assert b'"usage":{"prompt_tokens":' in final
    assert b'"completion_tokens":' in final
    assert b'"total_tokens":' in final
    assert frames[-1] == DONE_FRAME == b"data:[DONE]\n\n"


async def test_v027_default_profile_bytes_unchanged() -> None:
    """Profil v0.27 bez zmian: ten sam kształt ramki, tylko ``model`` = id modelu czatu."""
    frames_v027 = await _frames(META_V027)
    assert frames_v027[0] == FRAME_CONTENT.replace(b'"model":"model"', b'"model":"MODEL0"')
    assert frames_v027[-1] == DONE_FRAME
    # Ten sam koder i profil domyślny: ramka v0.24 zostaje bajtowo bez zmian.
    assert (await _frames(META_V024))[0] == FRAME_CONTENT


def test_completion_json_keys_match_golden() -> None:
    """JSON ``chat.completion`` v0.24: ``logprobs`` i ``usage.completion_tokens_details``."""
    body = completion_json(
        meta=META_V024,
        content="Odpowiedź testowa: smokwawelski",
        prompt="q",
        reasoning_tokens=REASONING_TOKENS,
    )
    assert body["object"] == "chat.completion"
    assert body["id"] == "chatcmpl-c1"
    assert body["model"] == "model"
    assert list(body["choices"][0]) == ["message", "logprobs", "finish_reason", "index"]
    assert body["choices"][0]["logprobs"] is None
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "Odpowiedź testowa: smokwawelski",
    }
    assert list(body["usage"]) == [
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "completion_tokens_details",
    ]
    details = body["usage"]["completion_tokens_details"]
    assert list(details) == [
        "reasoning_tokens",
        "accepted_prediction_tokens",
        "rejected_prediction_tokens",
    ]
    assert details["reasoning_tokens"] == REASONING_TOKENS
    assert details["rejected_prediction_tokens"] == 0


# --- Trasa: domyślne ``stream`` zależne od profilu (brief T4 p. a2) ---
#
# Testy na atrapie kontenera (bez bazy): trasa rozstrzyga tylko, czy brak ``stream``
# kieruje żądanie na ścieżkę SSE (v0.24), czy na JSON ``chat.completion`` (v0.27).

_PROFILE_V024 = "ragflow_0_24"
_PROFILE_V027 = "ragflow_0_27"
_PRINCIPAL = Principal("u" * 32, "bob@x.pl", False, False, "api_key")
_MESSAGES: list[dict[str, str]] = [{"role": "user", "content": "smokwawelski"}]
_PATH = "/api/v1/chats_openai/{chat_id}/chat/completions"
_JSON = "application/json"
_SSE = "text/event-stream"
_OK = 200


async def _events() -> AsyncIterator[ChatEvent]:
    yield AnswerDelta("Hej")
    yield Final(
        answer="",
        reference={},
        prompt="",
        created_at=1.0,
        final_answer="Hej",
        thinking=None,
        usage=(1, 1),
        empty=False,
    )


class _Clock:
    """Zegar kontenera (trasa czyta ``now_ms``)."""

    def now_ms(self) -> int:
        return 1_000


class _FakeChat:
    """Port ``ChatService``: notuje, czy trasa wybrała strumień."""

    def __init__(self) -> None:
        self.streamed = False

    async def complete_once(self, principal: Principal, req: object) -> CompletionResult:
        return CompletionResult(
            ids=StreamIds("m1", None, None),
            answer="Hej",
            thinking=None,
            reference={},
            prompt="",
            created_at=1.0,
            usage=(1, 1),
        )

    async def start(self, principal: Principal, req: object) -> ChatStream:
        self.streamed = True
        return ChatStream(ids=StreamIds("m1", None, None), events=_events())


class _FakeOpenAIService:
    """Atrapa ``OpenAIService``: właściciel i model bez bazy (ścieżka streamu jest przedmiotem)."""

    def __init__(self, container: object) -> None:
        pass

    async def chat(self, principal: Principal, chat_id: str) -> object:
        return object()

    async def check_model(self, model: str, profile: str = _PROFILE_V027) -> None:
        return None

    async def response_model(self, chat: object, requested: str, profile: str) -> str:
        return "model"


class _Container:
    """Minimalny kontener dla trasy: usługa czatu + zegar."""

    def __init__(self, chat: _FakeChat) -> None:
        self.chat = chat
        self.clock = _Clock()


def _client(monkeypatch: pytest.MonkeyPatch, profile: str, chat: _FakeChat) -> httpx.AsyncClient:
    """Aplikacja z routerem OpenAI i atrapami zależności (profil profilu i principala)."""
    monkeypatch.setattr(openai_chat, "OpenAIService", _FakeOpenAIService)
    app = FastAPI()
    app.state.container = _Container(chat)
    app.include_router(openai_chat.router)
    app.dependency_overrides[get_principal] = lambda: _PRINCIPAL
    app.dependency_overrides[get_compat_profile] = lambda: profile
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _post(client: httpx.AsyncClient, body: dict[str, object]) -> httpx.Response:
    return await client.post(_PATH.format(chat_id="c1"), json=body)


async def test_v024_without_stream_streams_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.24 i brak ``stream`` → strumień SSE z ``data:[DONE]`` (nie JSON)."""
    chat = _FakeChat()
    async with _client(monkeypatch, _PROFILE_V024, chat) as client:
        response = await _post(client, {"model": "model", "messages": _MESSAGES})
    assert response.status_code == _OK
    assert chat.streamed is True
    assert response.headers["content-type"].startswith(_SSE)
    assert response.text.rstrip().endswith("data:[DONE]")


async def test_v024_stream_false_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.24 i ``stream: false`` → JSON ``chat.completion`` (jawne false wygrywa z domyślnym)."""
    chat = _FakeChat()
    async with _client(monkeypatch, _PROFILE_V024, chat) as client:
        response = await _post(client, {"model": "model", "messages": _MESSAGES, "stream": False})
    assert response.status_code == _OK
    assert chat.streamed is False
    assert response.headers["content-type"].startswith(_JSON)
    assert response.json()["object"] == "chat.completion"


async def test_v027_without_stream_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.27 i brak ``stream`` → JSON ``chat.completion`` (profil 0.27 bez zmian)."""
    chat = _FakeChat()
    async with _client(monkeypatch, _PROFILE_V027, chat) as client:
        response = await _post(client, {"model": "model", "messages": _MESSAGES})
    assert response.status_code == _OK
    assert chat.streamed is False
    assert response.headers["content-type"].startswith(_JSON)
    assert response.json()["object"] == "chat.completion"
