"""Testy jednostkowe OpenAIGateway (kontrakt C8) — httpx2.MockTransport, bez sieci."""

import asyncio
import json
import math
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.llm.errors import LLMAuthError, LLMBadRequest, LLMRateLimited, LLMUnavailable
from app.llm.openai_gateway import LLMTimeouts, OpenAIGateway
from app.llm.types import (
    ChatResult,
    ModelRef,
    ReasoningDelta,
    StreamEnd,
    TextDelta,
)

BASE_URL = "http://llm.test/v1"
USER = {"role": "user", "content": "cześć"}

Handler = Callable[[httpx2.Request], Any]


def make_settings() -> Settings:
    return Settings(
        env="test",
        llm_base_url=BASE_URL,
        llm_api_key=SecretStr("k"),
        llm_max_retries=0,
    )


def chat_model(**extra: Any) -> ModelRef:
    return ModelRef(id=None, name="m", model_type="chat", **extra)


def make_gateway(handler: Handler, **extra: Any) -> OpenAIGateway:
    return OpenAIGateway(make_settings(), transport=httpx2.MockTransport(handler), **extra)


def completion(content: str) -> dict[str, Any]:
    """Odpowiedź chat.completion z usage 3/2 (przykłady z briefu)."""
    message = {"role": "assistant", "content": content}
    return {
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
    }


def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def sse(frames: list[dict[str, Any]], *, usage: dict[str, Any] | None) -> bytes:
    out = b""
    for frame in frames:
        out += b"data: " + json.dumps(frame).encode() + b"\n\n"
    if usage is not None:
        tail = {
            "id": "x",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [],
            "usage": usage,
        }
        out += b"data: " + json.dumps(tail).encode() + b"\n\n"
    return out + b"data: [DONE]\n\n"


STREAM_USAGE = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


async def test_chat_parses_think_and_usage() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=completion("<think>r</think>odp"))

    gateway = make_gateway(handler)
    result = await gateway.chat(chat_model(), [USER])
    assert result == ChatResult(
        text="odp", reasoning="r", tokens_in=3, tokens_out=2, finish_reason="stop"
    )
    await gateway.aclose()


async def test_chat_omits_none_options() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    await gateway.chat(chat_model(), [USER], temperature=None, top_p=None, max_tokens=None)
    for key in ("temperature", "top_p", "max_tokens", "extra_body"):
        assert key not in captured["body"]
    await gateway.aclose()


async def test_chat_merges_extra_body_and_sends_temperature() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    model = chat_model(extra={"extra_body": {"a": 1}})
    extra_arg = {"b": 2}
    await gateway.chat(model, [USER], extra=extra_arg, temperature=0.0)
    assert captured["body"]["a"] == 1
    assert captured["body"]["b"] == extra_arg["b"]
    assert captured["body"]["temperature"] == 0.0
    await gateway.aclose()


async def test_chat_never_sends_max_concurrency() -> None:
    """`max_concurrency` zostaje w rejestrze — do bramki idzie tylko `extra_body` (K13 p. 3)."""
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    model = chat_model(extra={"max_concurrency": 8, "extra_body": {"x": 1}})
    await gateway.chat(model, [USER])
    assert captured["body"]["x"] == 1
    assert "max_concurrency" not in captured["body"]
    await gateway.aclose()


async def test_embed_never_sends_max_concurrency() -> None:
    """`extra.max_concurrency` nie trafia do żądania embeddingu (K13 p. 3)."""
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "model": "m",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    gateway = make_gateway(handler)
    model = chat_model(extra={"max_concurrency": 8, "extra_body": {"x": 1}})
    await gateway.embed(model, ["a"])
    assert "max_concurrency" not in captured["body"]
    await gateway.aclose()


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, {"error": {"message": "rate limited"}}, LLMRateLimited),
        (401, {"error": {"message": "zły klucz"}}, LLMAuthError),
        (404, {"error": {"message": "nie ma", "code": "model_not_found"}}, LLMBadRequest),
        (500, {"error": {"message": "boom"}}, LLMUnavailable),
    ],
)
async def test_chat_error_mapping(
    status: int, body: dict[str, Any], expected: type[Exception]
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body)

    gateway = make_gateway(handler)
    with pytest.raises(expected):
        await gateway.chat(chat_model(), [USER])
    await gateway.aclose()


async def test_chat_connect_error_maps_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("brak trasy", request=request)

    gateway = make_gateway(handler)
    with pytest.raises(LLMUnavailable):
        await gateway.chat(chat_model(), [USER])
    await gateway.aclose()


async def test_stream_splits_think_and_ends_once() -> None:
    frames = [
        chunk({"role": "assistant", "content": ""}),
        chunk({"content": "<thi"}),
        chunk({"content": "nk>r</think>od"}),
        chunk({"content": "p"}),
        chunk({}, finish="stop"),
    ]
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(frames, usage=STREAM_USAGE),
        )

    gateway = make_gateway(handler)
    events = [e async for e in gateway.chat_stream(chat_model(), [USER])]
    reasoning = "".join(e.text for e in events if isinstance(e, ReasoningDelta))
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    ends = [e for e in events if isinstance(e, StreamEnd)]
    assert reasoning == "r"
    assert text == "odp"
    assert ends == [StreamEnd(tokens_in=3, tokens_out=2, finish_reason="stop")]
    assert isinstance(events[-1], StreamEnd)
    assert seen["body"]["stream_options"] == {"include_usage": True}
    await gateway.aclose()


async def test_stream_without_usage_yields_zero_tokens() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse([chunk({"content": "hej"}), chunk({}, finish="stop")], usage=None),
        )

    gateway = make_gateway(handler)
    events = [e async for e in gateway.chat_stream(chat_model(), [USER])]
    ends = [e for e in events if isinstance(e, StreamEnd)]
    assert ends == [StreamEnd(tokens_in=0, tokens_out=0, finish_reason="stop")]
    await gateway.aclose()


async def test_embed_empty_skips_call() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200, json={})

    gateway = make_gateway(handler)
    assert await gateway.embed(chat_model(), []) == []
    assert calls == []
    await gateway.aclose()


async def test_embed_orders_by_index_and_sends_float() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
                    {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
                ],
                "model": "m",
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    gateway = make_gateway(handler)
    vectors = await gateway.embed(chat_model(), ["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["body"]["encoding_format"] == "float"
    assert "dimensions" not in captured["body"]
    await gateway.aclose()


async def test_embed_query_returns_first_vector() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "model": "m",
            },
        )

    gateway = make_gateway(handler)
    assert await gateway.embed_query(chat_model(), "tekst") == [0.1, 0.2]
    await gateway.aclose()


async def test_rerank_maps_scores_auth_and_url() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        results = [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]
        return httpx2.Response(200, json={"id": "r", "results": results, "meta": {}})

    gateway = make_gateway(handler)
    reranker = ModelRef(id=None, name="r", model_type="rerank")
    scores = await gateway.rerank(reranker, "q", ["d0", "d1", "d2"])
    assert scores == pytest.approx([0.1, 0.9, 0.0])
    assert captured["url"] == f"{BASE_URL}/rerank"
    assert captured["auth"] == "Bearer k"
    assert captured["body"] == {"model": "r", "query": "q", "documents": ["d0", "d1", "d2"]}
    await gateway.aclose()


async def test_rerank_sigmoid_when_scores_out_of_range() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        results = [{"index": 0, "relevance_score": 2.0}, {"index": 1, "relevance_score": -1.0}]
        return httpx2.Response(200, json={"results": results})

    gateway = make_gateway(handler)
    reranker = ModelRef(id=None, name="r", model_type="rerank")
    scores = await gateway.rerank(reranker, "q", ["d0", "d1"])
    assert scores[0] == pytest.approx(1.0 / (1.0 + math.exp(-2.0)))
    assert scores[1] == pytest.approx(1.0 / (1.0 + math.exp(1.0)))
    await gateway.aclose()


async def test_rerank_empty_documents_skips_call() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200, json={})

    gateway = make_gateway(handler)
    reranker = ModelRef(id=None, name="r", model_type="rerank")
    assert await gateway.rerank(reranker, "q", []) == []
    assert calls == []
    await gateway.aclose()


async def test_rerank_500_maps_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"error": "boom"})

    gateway = make_gateway(handler)
    reranker = ModelRef(id=None, name="r", model_type="rerank")
    with pytest.raises(LLMUnavailable):
        await gateway.rerank(reranker, "q", ["d0"])
    await gateway.aclose()


async def test_vision_sends_data_url() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=completion("opis"))

    gateway = make_gateway(handler)
    text = await gateway.vision(chat_model(), "opisz", b"\x89PNG")
    assert text == "opis"
    content = captured["body"]["messages"][0]["content"]
    assert content[1]["image_url"]["url"] == "data:image/png;base64,iVBORw=="
    await gateway.aclose()


async def test_pool_reuse_and_close() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    await gateway.chat(chat_model(), [USER])
    assert len(gateway._pool) == 1
    await gateway.chat(chat_model(), [USER])
    assert len(gateway._pool) == 1
    other_base = "http://other.test/v1"
    await gateway.chat(chat_model(base_url=other_base), [USER])
    assert set(gateway._pool) == {(BASE_URL, "k"), (other_base, "k")}
    await gateway.aclose()
    assert len(gateway._pool) == 0


async def test_chat_sends_sampling_options() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=completion("ok"))

    gateway = make_gateway(handler)
    temperature, top_p, max_tokens = 0.5, 0.9, 256
    await gateway.chat(
        chat_model(), [USER], temperature=temperature, top_p=top_p, max_tokens=max_tokens
    )
    assert captured["body"]["temperature"] == temperature
    assert captured["body"]["top_p"] == top_p
    assert captured["body"]["max_tokens"] == max_tokens
    await gateway.aclose()


async def test_embed_error_maps_bad_request() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = {"error": {"message": "nie ma", "code": "model_not_found"}}
        return httpx2.Response(404, json=body)

    gateway = make_gateway(handler)
    with pytest.raises(LLMBadRequest):
        await gateway.embed(chat_model(), ["a"])
    await gateway.aclose()


async def test_embed_rate_limit_retries_only_in_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 na embed: dokładnie `MAX_ATTEMPTS` żądań transportu — SDK nie ponawia (C4).

    `llm_max_retries=3` celowo: gdyby SDK ponawiał, żądań byłoby wielokrotnie więcej.
    `BACKOFF_BASE_S=0` zeruje przerwy, żeby test nie czekał realnie.
    """
    from app.llm import rate_limit as rate_limit_module  # noqa: PLC0415

    monkeypatch.setattr(rate_limit_module, "BACKOFF_BASE_S", 0.0)
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(429, json={"error": {"message": "rate limited"}})

    settings = make_settings().model_copy(update={"llm_max_retries": 3})
    gateway = OpenAIGateway(settings, transport=httpx2.MockTransport(handler))
    with pytest.raises(LLMRateLimited):
        await gateway.embed(chat_model(), ["a"])
    assert len(calls) == rate_limit_module.MAX_ATTEMPTS
    await gateway.aclose()


async def test_stream_error_maps_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"error": {"message": "boom"}})

    gateway = make_gateway(handler)
    with pytest.raises(LLMUnavailable):
        async for _ in gateway.chat_stream(chat_model(), [USER]):
            pass
    await gateway.aclose()


async def test_stream_flushes_buffered_tag_prefix() -> None:
    # strumień kończy się w środku możliwego tagu <think> — flush emituje bufor jako text
    def handler(request: httpx2.Request) -> httpx2.Response:
        frames = [chunk({"content": "<th"}), chunk({}, finish="stop")]
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(frames, usage=None),
        )

    gateway = make_gateway(handler)
    events = [e async for e in gateway.chat_stream(chat_model(), [USER])]
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text == "<th"
    await gateway.aclose()


async def test_stream_total_timeout_maps_unavailable() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(0.5)  # slow_stream: przerwy między deltami (K10 §4)
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse([chunk({"content": "hej"})], usage=None),
        )

    gateway = make_gateway(handler, timeouts=LLMTimeouts(stream_total=0.05))
    with pytest.raises(LLMUnavailable) as exc_info:
        async for _ in gateway.chat_stream(chat_model(), [USER]):
            pass
    assert exc_info.value.message == "LLM stream timeout"
    assert exc_info.value.details == {"model": "m", "status": None}
    await gateway.aclose()


async def test_rerank_ignores_out_of_range_index() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"results": [{"index": 5, "relevance_score": 0.5}]})

    gateway = make_gateway(handler)
    reranker = ModelRef(id=None, name="r", model_type="rerank")
    assert await gateway.rerank(reranker, "q", ["d0"]) == [0.0]
    await gateway.aclose()
