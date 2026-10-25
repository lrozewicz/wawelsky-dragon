"""Testy OpenAIGateway przeciw fake-llm po sieci (K10; uruchamia verify.sh)."""

import hashlib
import math
import os
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.llm.errors import LLMBadRequest, LLMRateLimited, LLMUnavailable
from app.llm.openai_gateway import LLMTimeouts, OpenAIGateway
from app.llm.types import ModelRef, ReasoningDelta, StreamEnd, StreamEvent, TextDelta

pytestmark = [
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

QUESTION = [{"role": "user", "content": "Jak się masz?"}]
ANSWER = "Odpowiedź testowa: Jak się masz?"
REASONING = "Rozważam pytanie."
PNG = b"\x89PNG\r\n\x1a\nreszta-bajtow"

_FAKE_CHAT = "fake-chat"
_FAKE_CHAT_THINK = "fake-chat-think"
_FAKE_RERANK = "fake-rerank"
_FAKE_VISION = "fake-vision"
_EMBED_CASES = (("fake-embed-3072", 3072), ("fake-embed-1024", 1024))
_EMBED_TEXTS = ["umowa najmu lokalu", "najmu lokalu", "prognoza pogody"]
_N_EMBED_TEXTS = 3
_NORM_TOL = 1e-6
_RELATED = "umowa najmu lokalu"
_UNRELATED = "prognoza pogody"
_RETRY_QUERY = "najmu lokalu"
_429_REQUESTS = 3  # 1 + 2 retry wg Retry-After (SDK, bez własnej pętli)
_429_MIN_SECONDS = 1.9  # 2 przerwy po ~1 s (Retry-After: 1)


def make_settings(max_retries: int = 0) -> Settings:
    return Settings(
        env="test",
        llm_base_url=os.environ["WD_LLM_BASE_URL"],
        llm_api_key=SecretStr("fake"),
        llm_max_retries=max_retries,
    )


def scenario_hook(scenario: str) -> Callable[[httpx2.Request], Any]:
    async def hook(request: httpx2.Request) -> None:
        request.headers["X-Fake-Scenario"] = scenario

    return hook


class CountingHook:
    """Hook liczący żądania i dopisujący nagłówek scenariusza (K10 §4)."""

    def __init__(self, scenario: str) -> None:
        self.count = 0
        self._scenario = scenario

    async def __call__(self, request: httpx2.Request) -> None:
        self.count += 1
        request.headers["X-Fake-Scenario"] = self._scenario


@pytest.fixture
async def gateway_factory() -> AsyncIterator[Callable[..., OpenAIGateway]]:
    created: list[OpenAIGateway] = []

    def factory(**kwargs: Any) -> OpenAIGateway:
        gateway = OpenAIGateway(kwargs.pop("settings", make_settings()), **kwargs)
        created.append(gateway)
        return gateway

    yield factory
    for gateway in created:
        await gateway.aclose()


async def test_chat_basic(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory()
    result = await gateway.chat(ModelRef(None, _FAKE_CHAT, "chat"), QUESTION)
    assert result.text == ANSWER
    assert result.reasoning is None
    assert result.finish_reason == "stop"
    assert result.tokens_in > 0


async def test_chat_think(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory()
    result = await gateway.chat(ModelRef(None, _FAKE_CHAT_THINK, "chat"), QUESTION)
    assert result.reasoning == REASONING
    assert result.text == ANSWER


async def test_chat_stream_matches_chat(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory()
    plain = await gateway.chat(ModelRef(None, _FAKE_CHAT, "chat"), QUESTION)
    events: list[StreamEvent] = [
        event async for event in gateway.chat_stream(ModelRef(None, _FAKE_CHAT, "chat"), QUESTION)
    ]
    text = "".join(event.text for event in events if isinstance(event, TextDelta))
    ends = [event for event in events if isinstance(event, StreamEnd)]
    assert text == plain.text
    assert len(ends) == 1
    assert ends[0].tokens_in > 0
    assert isinstance(events[-1], StreamEnd)


async def test_chat_stream_think(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory()
    stream = gateway.chat_stream(ModelRef(None, _FAKE_CHAT_THINK, "chat"), QUESTION)
    events: list[StreamEvent] = [event async for event in stream]
    reasoning = "".join(event.text for event in events if isinstance(event, ReasoningDelta))
    text = "".join(event.text for event in events if isinstance(event, TextDelta))
    assert reasoning == REASONING
    assert text == ANSWER


async def test_embed_dimensions_and_cosine(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory()
    for name, dim in _EMBED_CASES:
        model = ModelRef(None, name, "embedding")
        vectors = await gateway.embed(model, _EMBED_TEXTS)
        assert len(vectors) == _N_EMBED_TEXTS
        assert all(len(vector) == dim for vector in vectors)
        norms = [math.sqrt(sum(value * value for value in vector)) for vector in vectors]
        assert all(abs(norm - 1.0) <= _NORM_TOL for norm in norms)
        cos_01 = sum(a * b for a, b in zip(vectors[0], vectors[1], strict=True))
        cos_02 = sum(a * b for a, b in zip(vectors[0], vectors[2], strict=True))
        assert cos_01 > cos_02


async def test_rerank(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory()
    reranker = ModelRef(None, _FAKE_RERANK, "rerank")
    documents = [_UNRELATED, _RELATED]
    scores = await gateway.rerank(reranker, _RETRY_QUERY, documents)
    assert scores == pytest.approx([0.0, 1.0])


async def test_vision_ocr_hash(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory()
    model = ModelRef(None, _FAKE_VISION, "image2text")
    result = await gateway.vision(model, "opisz", PNG)
    assert result == f"<p>OCR:{hashlib.sha256(PNG).hexdigest()[:8]}</p>"


async def test_error_500(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory(event_hooks={"request": [scenario_hook("error_500")]})
    with pytest.raises(LLMUnavailable) as exc_info:
        await gateway.chat(ModelRef(None, _FAKE_CHAT, "chat"), QUESTION)
    assert exc_info.value.details == {"model": _FAKE_CHAT, "status": 500}


async def test_error_429_retries_with_backoff(
    gateway_factory: Callable[..., OpenAIGateway],
) -> None:
    hook = CountingHook("error_429")
    gateway = gateway_factory(
        settings=make_settings(max_retries=2),
        event_hooks={"request": [hook]},
    )
    start = time.perf_counter()
    with pytest.raises(LLMRateLimited):
        await gateway.chat(ModelRef(None, _FAKE_CHAT, "chat"), QUESTION)
    elapsed = time.perf_counter() - start
    assert hook.count == _429_REQUESTS
    assert elapsed >= _429_MIN_SECONDS


async def test_slow_stream_read_timeout(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory(
        timeouts=LLMTimeouts(stream_read=0.05),
        event_hooks={"request": [scenario_hook("slow_stream")]},
    )
    with pytest.raises(LLMUnavailable):
        async for _ in gateway.chat_stream(ModelRef(None, _FAKE_CHAT, "chat"), QUESTION):
            pass


async def test_slow_stream_total_timeout(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory(
        timeouts=LLMTimeouts(stream_read=5.0, stream_total=0.3),
        event_hooks={"request": [scenario_hook("slow_stream")]},
    )
    with pytest.raises(LLMUnavailable) as exc_info:
        async for _ in gateway.chat_stream(ModelRef(None, _FAKE_CHAT, "chat"), QUESTION):
            pass
    assert exc_info.value.message == "LLM stream timeout"
    assert exc_info.value.details == {"model": _FAKE_CHAT, "status": None}


async def test_unknown_model_is_bad_request(gateway_factory: Callable[..., OpenAIGateway]) -> None:
    gateway = gateway_factory()
    with pytest.raises(LLMBadRequest) as exc_info:
        await gateway.chat(ModelRef(None, "nie-ma-takiego", "chat"), QUESTION)
    assert exc_info.value.details == {"model": "nie-ma-takiego", "status": 404}
