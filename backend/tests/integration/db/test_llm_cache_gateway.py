"""Cache odpowiedzi i embeddingów w OpenAIGateway na MariaDB + fake-llm (brief T5, kontrakt C10)."""

import asyncio
import os
from collections.abc import AsyncIterator

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.llm.cache import cached_vision
from app.llm.cache_keys import CACHE_TTL_MS
from app.llm.hooks import TaskLlmHooks, install_hooks, reset_hooks
from app.llm.openai_gateway import OpenAIGateway
from app.llm.types import ChatMessage, ChatResult, ModelRef
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

MESSAGES: list[ChatMessage] = [{"role": "user", "content": "Jak się masz?"}]
CHAT_MODEL = "fake-chat-think"
EMBED_MODEL = ModelRef(None, "fake-embed-1024", "embedding")
QUERY = "umowa najmu"
VISION_MODEL_NAME = "fake-ocr"
VISION_PROMPT = "przepisz stronę"
VISION_PNG = b"\x89PNG\r\n vision page bytes"
_TOL = 1e-6
_TWO_REQUESTS = 2
# (model, dim, LENGTH(vector)) dla fake-embed-1024: float32 LE = 4 bajty na wymiar
_EMBED_ROW = (1024, 4096)

Env = tuple[OpenAIGateway, "RequestCounter", FrozenClock, async_sessionmaker[AsyncSession]]


class RequestCounter:
    """Hook httpx2 liczący żądania wysłane do fake-llm."""

    def __init__(self) -> None:
        self.count = 0

    async def __call__(self, request: httpx2.Request) -> None:
        self.count += 1


@pytest.fixture
async def env(fresh_db: Settings) -> AsyncIterator[Env]:
    """Zmigrowana świeża baza + gateway z cache w bazie, zamrożonym zegarem i licznikiem żądań."""
    await asyncio.to_thread(command.upgrade, alembic_cfg(fresh_db), "head")
    engine = make_engine(fresh_db)
    sm = make_sessionmaker(engine)
    clock = FrozenClock()
    counter = RequestCounter()
    settings = fresh_db.model_copy(
        update={
            "llm_base_url": os.environ["WD_LLM_BASE_URL"],
            "llm_api_key": SecretStr("fake"),
            "llm_max_retries": 0,
        }
    )
    gateway = OpenAIGateway(
        settings,
        sessionmaker=sm,
        clock=clock,
        event_hooks={"request": [counter]},
    )
    yield gateway, counter, clock, sm
    await gateway.aclose()
    await engine.dispose()


async def test_chat_cache_hit(env: Env) -> None:
    """Drugi chat(cache=True) z cache — wyniki równe, jedno żądanie, jeden wiersz llm_cache."""
    gateway, counter, _clock, sm = env
    model = ModelRef(None, CHAT_MODEL, "chat")
    first = await gateway.chat(model, MESSAGES, cache=True)
    second = await gateway.chat(model, MESSAGES, cache=True)
    assert counter.count == 1
    assert (first.text, first.reasoning) == (second.text, second.reasoning)
    assert (first.tokens_in, first.tokens_out) == (second.tokens_in, second.tokens_out)
    assert first.finish_reason == second.finish_reason
    async with sm() as session:
        rows = (await session.execute(text("SELECT model FROM llm_cache"))).all()
    assert rows == [(CHAT_MODEL,)]


async def test_chat_cache_false(env: Env) -> None:
    """cache=False — każde wywołanie idzie do LLM, baza nietknięta."""
    gateway, counter, _clock, sm = env
    model = ModelRef(None, CHAT_MODEL, "chat")
    await gateway.chat(model, MESSAGES, cache=False)
    await gateway.chat(model, MESSAGES, cache=False)
    assert counter.count == _TWO_REQUESTS
    async with sm() as session:
        rows = (await session.execute(text("SELECT model FROM llm_cache"))).all()
    assert rows == []


async def test_chat_cache_expired(env: Env) -> None:
    """Wygasły wpis = brak trafienia; ponowny zapis nadpisuje ten sam wiersz."""
    gateway, counter, clock, sm = env
    model = ModelRef(None, CHAT_MODEL, "chat")
    await gateway.chat(model, MESSAGES, cache=True)
    clock.advance(CACHE_TTL_MS)
    await gateway.chat(model, MESSAGES, cache=True)
    assert counter.count == _TWO_REQUESTS
    async with sm() as session:
        rows = (await session.execute(text("SELECT model FROM llm_cache"))).all()
    assert len(rows) == 1


async def test_chat_cache_temperature_varies(env: Env) -> None:
    """Inna temperatura = inny klucz cache — dwa żądania."""
    gateway, counter, _clock, _sm = env
    model = ModelRef(None, CHAT_MODEL, "chat")
    await gateway.chat(model, MESSAGES, cache=True, temperature=0.0)
    await gateway.chat(model, MESSAGES, cache=True)
    assert counter.count == _TWO_REQUESTS


async def test_embed_query_cache_hit(env: Env) -> None:
    """Drugi embed_query z cache — jedno żądanie; wektor float32 LE (4 bajty na wymiar)."""
    gateway, counter, _clock, sm = env
    first = await gateway.embed_query(EMBED_MODEL, QUERY)
    second = await gateway.embed_query(EMBED_MODEL, QUERY)
    assert counter.count == 1
    assert first == pytest.approx(second, abs=_TOL)
    async with sm() as session:
        rows = (
            await session.execute(text("SELECT dim, LENGTH(`vector`) FROM embedding_cache"))
        ).all()
    assert rows == [_EMBED_ROW]


async def test_embed_query_cache_expired(env: Env) -> None:
    """Po TTL wektora cache nie trafia — drugie żądanie do LLM."""
    gateway, counter, clock, _sm = env
    await gateway.embed_query(EMBED_MODEL, QUERY)
    clock.advance(CACHE_TTL_MS)
    await gateway.embed_query(EMBED_MODEL, QUERY)
    assert counter.count == _TWO_REQUESTS


async def test_embed_query_dimension_varies(env: Env) -> None:
    """dimension w ModelRef wchodzi do klucza (None → 0) — inny klucz, drugie żądanie."""
    gateway, counter, _clock, _sm = env
    await gateway.embed_query(EMBED_MODEL, QUERY)
    other = ModelRef(None, "fake-embed-1024", "embedding", dimension=1024)
    await gateway.embed_query(other, QUERY)
    assert counter.count == _TWO_REQUESTS


# --- cache wizji (kontrakt E5-H8e §C3) ---


def _vision_call_args(model: ModelRef) -> dict[str, object]:
    """Argumenty klucza cache wizji (bez ``call`` i ``sessionmaker``)."""
    return {
        "model": model,
        "base_url": "http://fake/v1",
        "image_png": VISION_PNG,
        "prompt": VISION_PROMPT,
        "temperature": 0.0,
        "max_tokens": 8192,
        "extra_body": None,
    }


async def test_vision_cache_hit(env: Env) -> None:
    """Drugi vision(cache=True) z cache — ten sam tekst, jedno żądanie, jeden wiersz."""
    gateway, counter, _clock, sm = env
    model = ModelRef(None, VISION_MODEL_NAME, "image2text")
    first = await gateway.vision(model, VISION_PROMPT, VISION_PNG, cache=True)
    second = await gateway.vision(model, VISION_PROMPT, VISION_PNG, cache=True)
    assert counter.count == 1
    assert first == second
    async with sm() as session:
        rows = (await session.execute(text("SELECT model FROM llm_cache"))).all()
    assert rows == [(VISION_MODEL_NAME,)]


async def test_vision_cache_false(env: Env) -> None:
    """cache=False — każde wywołanie idzie do LLM, baza nietknięta (C3)."""
    gateway, counter, _clock, sm = env
    model = ModelRef(None, VISION_MODEL_NAME, "image2text")
    await gateway.vision(model, VISION_PROMPT, VISION_PNG, cache=False)
    await gateway.vision(model, VISION_PROMPT, VISION_PNG, cache=False)
    assert counter.count == _TWO_REQUESTS
    async with sm() as session:
        rows = (await session.execute(text("SELECT model FROM llm_cache"))).all()
    assert rows == []


async def test_vision_cache_key_varies_with_image(env: Env) -> None:
    """Inny obraz = inny klucz cache wizji — dwa żądania."""
    gateway, counter, _clock, _sm = env
    model = ModelRef(None, VISION_MODEL_NAME, "image2text")
    await gateway.vision(model, VISION_PROMPT, VISION_PNG, cache=True)
    await gateway.vision(model, VISION_PROMPT, VISION_PNG + b"x", cache=True)
    assert counter.count == _TWO_REQUESTS


async def test_vision_cache_expired(env: Env) -> None:
    """Wygasły wpis = brak trafienia; ponowny zapis nadpisuje ten sam wiersz."""
    gateway, counter, clock, sm = env
    model = ModelRef(None, VISION_MODEL_NAME, "image2text")
    await gateway.vision(model, VISION_PROMPT, VISION_PNG, cache=True)
    clock.advance(CACHE_TTL_MS)
    await gateway.vision(model, VISION_PROMPT, VISION_PNG, cache=True)
    assert counter.count == _TWO_REQUESTS
    async with sm() as session:
        rows = (await session.execute(text("SELECT model FROM llm_cache"))).all()
    assert len(rows) == 1


async def test_cached_vision_miss_writes_then_hit(env: Env) -> None:
    """Chybienie → call() + zapis (tekst + tokeny); trafienie → brak wywołania."""
    _gateway, _counter, clock, sm = env
    model = ModelRef(None, VISION_MODEL_NAME, "image2text")
    calls: list[int] = []

    async def call() -> ChatResult:
        calls.append(1)
        return ChatResult(
            text="<p>x</p>", reasoning=None, tokens_in=10, tokens_out=5, finish_reason="stop"
        )

    first = await cached_vision(sm, clock, **_vision_call_args(model), call=call)  # type: ignore[arg-type]
    second = await cached_vision(sm, clock, **_vision_call_args(model), call=call)  # type: ignore[arg-type]
    assert first == second == "<p>x</p>"
    assert len(calls) == 1
    async with sm() as session:
        rows = (await session.execute(text("SELECT tokens_in, tokens_out FROM llm_cache"))).all()
    assert rows == [(10, 5)]


async def test_cached_vision_empty_text_not_stored(env: Env) -> None:
    """Pusty tekst nie jest zapisywany — kolejne wywołanie znów woła LLM (DEC-293 p.1)."""
    _gateway, _counter, clock, sm = env
    model = ModelRef(None, VISION_MODEL_NAME, "image2text")
    calls: list[int] = []

    async def call() -> ChatResult:
        calls.append(1)
        return ChatResult(
            text="   ", reasoning=None, tokens_in=1, tokens_out=0, finish_reason="stop"
        )

    await cached_vision(sm, clock, **_vision_call_args(model), call=call)  # type: ignore[arg-type]
    await cached_vision(sm, clock, **_vision_call_args(model), call=call)  # type: ignore[arg-type]
    assert len(calls) == _TWO_REQUESTS
    async with sm() as session:
        rows = (await session.execute(text("SELECT model FROM llm_cache"))).all()
    assert rows == []


async def test_cached_vision_exception_not_stored(env: Env) -> None:
    """Wyjątek z call() propaguje i nic nie zapisuje."""
    _gateway, _counter, clock, sm = env
    model = ModelRef(None, VISION_MODEL_NAME, "image2text")

    async def call() -> ChatResult:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await cached_vision(sm, clock, **_vision_call_args(model), call=call)  # type: ignore[arg-type]
    async with sm() as session:
        rows = (await session.execute(text("SELECT model FROM llm_cache"))).all()
    assert rows == []


async def test_cached_vision_hooks_counters(env: Env) -> None:
    """Trafienie → vision_cache_hits, chybienie → vision_model_calls (kontrakt C3)."""
    _gateway, _counter, clock, sm = env
    model = ModelRef(None, VISION_MODEL_NAME, "image2text")
    logs: list[str] = []

    async def log(msg: str) -> None:
        logs.append(msg)

    async def check_cancel() -> None:
        return None

    async def call() -> ChatResult:
        return ChatResult(
            text="<p>x</p>", reasoning=None, tokens_in=1, tokens_out=1, finish_reason="stop"
        )

    hooks = TaskLlmHooks(log=log, check_cancel=check_cancel)
    token = install_hooks(hooks)
    try:
        await cached_vision(sm, clock, **_vision_call_args(model), call=call)  # type: ignore[arg-type]
        await cached_vision(sm, clock, **_vision_call_args(model), call=call)  # type: ignore[arg-type]
    finally:
        reset_hooks(token)
    assert (hooks.vision_model_calls, hooks.vision_cache_hits) == (1, 1)
