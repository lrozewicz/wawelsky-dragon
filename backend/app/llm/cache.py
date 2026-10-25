"""Pomocniki cache bramki LLM (kontrakt C10, K5 §3.5) — wydzielone z openai_gateway (limit 400).

Każda operacja bazodanowa w osobnej `transaction` (nie trzymać transakcji w czasie wywołania LLM);
`call` to wywołanie LLM wykonywane tylko przy chybieniu.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.timeutil import Clock
from app.db.repositories import embedding_cache, llm_cache
from app.db.uow import transaction
from app.llm.cache_keys import (
    CACHE_TTL_MS,
    chat_cache_key,
    embedding_cache_key,
    pack_vector,
    unpack_vector,
    vision_cache_key,
)
from app.llm.hooks import current_hooks
from app.llm.types import ChatMessage, ChatResult, ModelRef


async def cached_chat(  # noqa: PLR0913 — argumenty klucza + call (C10)
    sessionmaker: async_sessionmaker[AsyncSession],
    clock: Clock,
    *,
    model: ModelRef,
    messages: Sequence[ChatMessage],
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    extra: Mapping[str, Any] | None,
    call: Callable[[], Awaitable[ChatResult]],
) -> ChatResult:
    """llm_cache: trafienie → ChatResult z JSON-a bez LLM; chybienie → call() + zapis."""
    key = chat_cache_key(model.name, messages, temperature, top_p, max_tokens, extra)
    async with transaction(sessionmaker) as session:
        cached = await llm_cache.get(session, key, clock.now_ms())
    if cached is not None:
        response, tokens_in, tokens_out = cached
        payload: dict[str, Any] = json.loads(response)
        return ChatResult(
            text=payload["text"],
            reasoning=payload["reasoning"],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            finish_reason=payload["finish_reason"],
        )
    result = await call()
    now_ms = clock.now_ms()
    response_json = json.dumps(
        {"text": result.text, "reasoning": result.reasoning, "finish_reason": result.finish_reason},
        ensure_ascii=False,
    )
    async with transaction(sessionmaker) as session:
        await llm_cache.put(
            session,
            key_hash=key,
            model=model.name,
            response=response_json,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            expires_at=now_ms + CACHE_TTL_MS,
            now_ms=now_ms,
        )
    return result


async def cached_vision(  # noqa: PLR0913 — argumenty klucza + call (kontrakt E5-H8e §C3)
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    clock: Clock,
    *,
    model: ModelRef,
    base_url: str,
    image_png: bytes,
    prompt: str,
    temperature: float | None,
    max_tokens: int | None,
    extra_body: Mapping[str, Any] | None,
    call: Callable[[], Awaitable[ChatResult]],
) -> str:
    """llm_cache wizji: trafienie → tekst z JSON-a bez LLM; chybienie → call() + zapis.

    Bez ``sessionmaker`` (brak bazy) cache jest pomijany — wywołanie liczy się jak chybienie
    (``vision_model_calls``). Pusty tekst (``not text.strip()``) nie jest zapisywany — druga
    próba strony musi trafić do modelu (DEC-293 p.1).
    """
    hooks = current_hooks()
    if sessionmaker is None:
        if hooks is not None:
            hooks.vision_model_calls += 1
        return (await call()).text
    key = vision_cache_key(
        model=model.name,
        base_url=base_url,
        image_sha256=hashlib.sha256(image_png).hexdigest(),
        prompt=prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )
    async with transaction(sessionmaker) as session:
        cached = await llm_cache.get(session, key, clock.now_ms())
    if cached is not None:
        if hooks is not None:
            hooks.vision_cache_hits += 1
        response, _tokens_in, _tokens_out = cached
        payload: dict[str, Any] = json.loads(response)
        return str(payload["text"])
    result = await call()
    if hooks is not None:
        hooks.vision_model_calls += 1
    if result.text.strip():
        now_ms = clock.now_ms()
        response_json = json.dumps({"text": result.text}, ensure_ascii=False)
        async with transaction(sessionmaker) as session:
            await llm_cache.put(
                session,
                key_hash=key,
                model=model.name,
                response=response_json,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                expires_at=now_ms + CACHE_TTL_MS,
                now_ms=now_ms,
            )
    return result.text


async def cached_embed_query(
    sessionmaker: async_sessionmaker[AsyncSession],
    clock: Clock,
    model: ModelRef,
    text: str,
    call: Callable[[], Awaitable[list[float]]],
) -> list[float]:
    """embedding_cache: klucz z `model.dimension or 0`; wektor float32 LE; TTL 30 dni (C10)."""
    key = embedding_cache_key(model.name, model.dimension or 0, text)
    async with transaction(sessionmaker) as session:
        cached = await embedding_cache.get(session, key, clock.now_ms())
    if cached is not None:
        return unpack_vector(cached)
    vector = await call()
    async with transaction(sessionmaker) as session:
        await embedding_cache.put(
            session,
            key_hash=key,
            model=model.name,
            dim=len(vector),
            vector=pack_vector(vector),
            expires_at=clock.now_ms() + CACHE_TTL_MS,
        )
    return vector
