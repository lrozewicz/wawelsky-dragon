"""Testy ponowienia bez parametrów odrzuconych (T4, kontrakt §3) — httpx2.MockTransport."""

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.llm.errors import LLMBadRequest
from app.llm.openai_gateway import OpenAIGateway
from app.llm.param_retry import RETRY_PARAMS, safe_message, unsupported_params
from app.llm.types import ModelRef, TextDelta

BASE_URL = "http://llm.test/v1"
USER = {"role": "user", "content": "cześć"}
PRESENCE = 0.1  # wartość presence_penalty w extra_body
RETRY_REQUESTS = 2  # żądania po jednym ponowieniu

Handler = Callable[[httpx2.Request], Any]

# Dosłowny komunikat LiteLLM z briefu (jedna z fraz + lista w apostrofach).
LITELLM_MESSAGE = (
    "litellm.UnsupportedParamsError: openai does not support parameters: "
    "['presence_penalty', 'frequency_penalty'], for model=gpt-5.4-nano. "
    "To drop these, set `litellm.drop_params=True` ..."
)


def make_settings() -> Settings:
    return Settings(
        env="test", llm_base_url=BASE_URL, llm_api_key=SecretStr("k"), llm_max_retries=0
    )


def chat_model(**extra: Any) -> ModelRef:
    return ModelRef(id=None, name="m", model_type="chat", **extra)


def rejected_extra(**params: float) -> dict[str, Any]:
    """``extra`` wywołania z parametrami, które model ma odrzucić (trafiają do extra_body)."""
    return {"extra_body": params}


def make_gateway(handler: Handler, **extra: Any) -> OpenAIGateway:
    return OpenAIGateway(make_settings(), transport=httpx2.MockTransport(handler), **extra)


def completion(content: str) -> dict[str, Any]:
    message = {"role": "assistant", "content": content}
    return {
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
    }


def unsupported_body(params: list[str]) -> dict[str, Any]:
    listing = ", ".join(f"'{param}'" for param in params)
    message = (
        f"litellm.UnsupportedParamsError: openai does not support parameters: [{listing}], "
        "for model=m. To drop these, set `litellm.drop_params=True` ..."
    )
    return {"error": {"message": message, "type": "invalid_request_error", "code": "400"}}


def sse(frames: list[dict[str, Any]]) -> bytes:
    out = b""
    for frame in frames:
        out += b"data: " + json.dumps(frame).encode() + b"\n\n"
    return out + b"data: [DONE]\n\n"


def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


# --- unsupported_params ---------------------------------------------------------


def test_unsupported_params_litellm_example() -> None:
    assert unsupported_params(LITELLM_MESSAGE) == ["presence_penalty", "frequency_penalty"]


def test_unsupported_params_double_quotes_and_filtering() -> None:
    message = 'does not support parameters: ["top_p", "max_tokens"]'
    assert unsupported_params(message) == ["top_p"]


def test_unsupported_params_no_phrase_is_none() -> None:
    assert unsupported_params("bad schema foo") is None


@pytest.mark.parametrize(
    "message",
    [
        "UnsupportedParamsError: something went wrong",
        "does not support parameters: []",
        "UnsupportedParamsError: does not support parameters: ['max_tokens']",
    ],
)
def test_unsupported_params_falls_back_to_all(message: str) -> None:
    assert unsupported_params(message) == list(RETRY_PARAMS)


# --- safe_message ---------------------------------------------------------------


def test_safe_message_strips_header_line_with_secret() -> None:
    raw = "Authorization: Bearer sk-abcdef123456\nboom"
    result = safe_message(raw)
    assert "sk-abcdef123456" not in result
    assert "Authorization" not in result
    assert "boom" in result


def test_safe_message_masks_secret_patterns() -> None:
    raw = "leak sk-abcdef123456 and Bearer abcdefgh and api_key=secretvalue"
    result = safe_message(raw)
    for secret in ("sk-abcdef123456", "abcdefgh", "secretvalue"):
        assert secret not in result


def test_safe_message_cleans_url() -> None:
    raw = "call http://user:pw@host/v1?api_key=topsecret failed"
    result = safe_message(raw)
    assert "user:pw@" not in result
    assert "topsecret" not in result


def test_safe_message_collapses_whitespace_and_truncates() -> None:
    assert safe_message("a\n\n   b\tc") == "a b c"
    assert safe_message("x" * 400, limit=10) == "x" * 10


# --- gateway: ponowienie --------------------------------------------------------


async def test_retry_drops_unsupported_params_once() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "presence_penalty" in body or "frequency_penalty" in body:
            return httpx2.Response(
                400, json=unsupported_body(["presence_penalty", "frequency_penalty"])
            )
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    model = chat_model(
        extra={"extra_body": {"presence_penalty": PRESENCE, "frequency_penalty": PRESENCE}}
    )
    result = await gateway.chat(model, [USER])
    assert result.text == "ok"
    assert len(bodies) == RETRY_REQUESTS
    assert "presence_penalty" in bodies[0]
    assert "presence_penalty" not in bodies[1]
    assert "frequency_penalty" not in bodies[1]
    await gateway.aclose()


async def test_second_call_uses_remembered_dropped() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "presence_penalty" in body:
            return httpx2.Response(400, json=unsupported_body(["presence_penalty"]))
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    model = chat_model(extra=rejected_extra(presence_penalty=PRESENCE))
    await gateway.chat(model, [USER])
    bodies.clear()
    await gateway.chat(model, [USER])
    assert len(bodies) == 1
    assert "presence_penalty" not in bodies[0]
    await gateway.aclose()


async def test_other_model_keeps_params() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if body["model"] == "m" and "presence_penalty" in body:
            return httpx2.Response(400, json=unsupported_body(["presence_penalty"]))
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    await gateway.chat(chat_model(extra=rejected_extra(presence_penalty=PRESENCE)), [USER])
    bodies.clear()
    other = ModelRef(
        id=None, name="n", model_type="chat", extra=rejected_extra(presence_penalty=PRESENCE)
    )
    await gateway.chat(other, [USER])
    assert len(bodies) == 1
    assert bodies[0]["presence_penalty"] == PRESENCE
    await gateway.aclose()


async def test_retry_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if "presence_penalty" in body:
            return httpx2.Response(400, json=unsupported_body(["presence_penalty"]))
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    model = chat_model(extra=rejected_extra(presence_penalty=PRESENCE))
    with caplog.at_level(logging.WARNING, logger="app.llm"):
        await gateway.chat(model, [USER])
    records = [
        record
        for record in caplog.records
        if record.message == "model rejected params; retrying without"
    ]
    assert len(records) == 1
    assert records[0].model == "m"
    assert records[0].params == ["presence_penalty"]
    await gateway.aclose()


async def test_retry_that_fails_again_maps_bad_request() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(
            400, json=unsupported_body(["presence_penalty", "frequency_penalty"])
        )

    gateway = make_gateway(handler)
    model = chat_model(extra=rejected_extra(presence_penalty=PRESENCE, frequency_penalty=PRESENCE))
    with pytest.raises(LLMBadRequest) as exc_info:
        await gateway.chat(model, [USER])
    assert len(calls) == RETRY_REQUESTS
    assert exc_info.value.message.startswith("LLM bad request: ")
    assert "does not support parameters" in exc_info.value.message
    await gateway.aclose()


async def test_chat_stream_retries_after_400() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "presence_penalty" in body:
            return httpx2.Response(400, json=unsupported_body(["presence_penalty"]))
        frames = [chunk({"content": "hej"}), chunk({}, finish="stop")]
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse(frames)
        )

    gateway = make_gateway(handler)
    model = chat_model(extra=rejected_extra(presence_penalty=PRESENCE))
    events = [event async for event in gateway.chat_stream(model, [USER])]
    text = "".join(event.text for event in events if isinstance(event, TextDelta))
    assert text == "hej"
    assert len(bodies) == RETRY_REQUESTS
    assert "presence_penalty" not in bodies[1]
    await gateway.aclose()


# --- czytelny komunikat 400 -----------------------------------------------------


async def test_bad_request_includes_response_message() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"error": {"message": "bad schema foo"}})

    gateway = make_gateway(handler)
    with pytest.raises(LLMBadRequest) as exc_info:
        await gateway.chat(chat_model(), [USER])
    assert exc_info.value.message == "LLM bad request: bad schema foo"
    await gateway.aclose()


async def test_bad_request_redacts_secret() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        message = "Authorization: Bearer sk-abcdef123456\nboom"
        return httpx2.Response(400, json={"error": {"message": message}})

    gateway = make_gateway(handler)
    with pytest.raises(LLMBadRequest) as exc_info:
        await gateway.chat(chat_model(), [USER])
    assert "sk-abcdef123456" not in exc_info.value.message
    await gateway.aclose()
