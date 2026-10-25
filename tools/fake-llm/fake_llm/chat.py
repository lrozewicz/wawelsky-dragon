"""Endpoint `POST /v1/chat/completions` (K10 §4, C5)."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse

from fake_llm import metadata, stats, tool_calls
from fake_llm.answers import ChatRequest, answer_content, usage
from fake_llm.errors import OpenAIError, model_not_found, unsupported_params_error
from fake_llm.models import CHAT_MODELS, base_model

_COMPLETION_ID = "chatcmpl-fake"
_CHUNK_CHARS = 5
_SLOW_STREAM_DELAY_S = 0.2
_ERROR_500: dict[str, object] = {"message": "fake error", "type": "server_error"}
_ERROR_429: dict[str, object] = {"message": "rate limited", "type": "rate_limit_error"}

# Model emulujący rodzinę GPT-5/o-series za bramką LiteLLM (K10 poprawka 2026-10-04).
_STRICT_MODEL = "fake-chat-strict"
# Model OCR, dla którego działa sterowalne opóźnienie (C6, poprawka 2026-10-10).
_OCR_MODEL = "fake-ocr"
_REJECT_ORDER = ("presence_penalty", "frequency_penalty", "temperature", "top_p")
_SAMPLING_KEYS = frozenset({"temperature", "top_p"})
_PASSTHROUGH_VALUE = 1

router = APIRouter()


def _rejected_params(body: ChatRequest) -> list[str]:
    """Klucze odrzucane przez `fake-chat-strict`: obecne kary oraz `temperature`/`top_p` ≠ 1."""
    extra = body.model_extra or {}
    rejected: list[str] = []
    for key in _REJECT_ORDER:
        if key not in extra:
            continue
        if key in _SAMPLING_KEYS and extra[key] == _PASSTHROUGH_VALUE:
            continue
        rejected.append(key)
    return rejected


def _chunk_frame(
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None,
    usage_obj: dict[str, int] | None = None,
) -> str:
    """Ramka SSE `chat.completion.chunk` (C5)."""
    chunk: dict[str, Any] = {
        "id": _COMPLETION_ID,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage_obj is not None:
        chunk["usage"] = usage_obj
    return "data: " + json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n\n"


async def _frames(
    model: str,
    content: str,
    usage_obj: dict[str, int],
    scenario: str | None,
) -> AsyncIterator[str]:
    """Ramki strumienia: rola, delty content po 5 znaków, stop z usage, `[DONE]` (C5)."""
    yield _chunk_frame(model, {"role": "assistant", "content": ""}, None)
    for index, start in enumerate(range(0, len(content), _CHUNK_CHARS)):
        if scenario == "slow_stream" and index > 0:
            await asyncio.sleep(_SLOW_STREAM_DELAY_S)
        yield _chunk_frame(model, {"content": content[start : start + _CHUNK_CHARS]}, None)
    yield _chunk_frame(model, {}, "stop", usage_obj)
    yield "data: [DONE]\n\n"


@router.post("/v1/chat/completions", response_model=None)
async def create_chat_completion(
    body: ChatRequest,
    x_fake_scenario: Annotated[str | None, Header()] = None,
) -> Response | dict[str, Any]:
    """`POST /v1/chat/completions`: treść deterministyczna, scenariusze `X-Fake-Scenario`, SSE.

    Alias `<model>~<scope>` jest akceptowany jak baza: kontrole modelu po nazwie bazowej,
    treść odpowiedzi liczona jak dla bazy, a liczniki i reguły zawężone po pełnej nazwie (C8).
    """
    base = base_model(body.model)
    if base not in CHAT_MODELS:
        raise model_not_found(body.model)
    stats.record_chat_request(body.model)
    # Licznik współbieżności modelu (C6): od wejścia do wyjścia z handlera; dla strumienia liczony
    # do zwrócenia `StreamingResponse` (opóźnienie `fake-ocr` jest przed odpowiedzią).
    stats.enter_model(body.model)
    try:
        # Wstrzykiwanie 5xx (C7): po zliczeniu żądania, przed opóźnieniem `fake-ocr`. Reguła
        # zawężona po `body.model` (C8).
        upstream_error = stats.upstream_error_for("chat", body.model)
        if upstream_error is not None:
            raise upstream_error
        # Opóźnienie `fake-ocr` (C6): po zliczeniu żądania, przed odpowiedzią.
        # Dotyczy też żądania strumieniowego. Reguła zawężona po `body.model` (C8).
        ocr_delay_ms = stats.ocr_delay_ms(body.model)
        if base == _OCR_MODEL and ocr_delay_ms > 0:
            await asyncio.sleep(ocr_delay_ms / 1000)
        if x_fake_scenario == "error_500":
            raise OpenAIError(500, _ERROR_500)
        if x_fake_scenario == "error_429":
            raise OpenAIError(429, _ERROR_429, headers={"Retry-After": "1"})
        # Kolejność kontroli: 404 → X-Fake-Scenario → 400 parametrów (K10 poprawka 2026-10-04).
        if base == _STRICT_MODEL and x_fake_scenario is None:
            rejected = _rejected_params(body)
            if rejected:
                raise unsupported_params_error(body.model, rejected)
        # Hook `tools`/`tool_calls` (K10 2026-10-11c): rozstrzyga przed zwykłą treścią czatu,
        # ale nie przed promptami metadanych (K10 2026-10-11b) — te mają pierwszeństwo.
        tool_result = tool_calls.resolve(body.model, body.messages, body.tools)
        if tool_result is not None and tool_result.calls:
            return tool_calls.respond(
                body.model, tool_result.calls, usage(body.messages, ""), body.stream
            )
        # Prompty metadanych (K10 2026-10-11b): rozpoznane po wiadomości system, przed innymi
        # scenariuszami czatu; reszta zachowania (stats, usage, stream) jak zwykły czat.
        content = metadata.metadata_content(body.messages)
        if content is None:
            content = (
                tool_result.content
                if tool_result is not None
                else answer_content(base, body.messages, x_fake_scenario)
            )
        usage_obj = usage(body.messages, content)
        if body.stream:
            return StreamingResponse(
                _frames(body.model, content, usage_obj, x_fake_scenario),
                media_type="text/event-stream",
            )
        return {
            "id": _COMPLETION_ID,
            "object": "chat.completion",
            "created": 0,
            "model": body.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage_obj,
        }
    finally:
        stats.exit_model(body.model)
