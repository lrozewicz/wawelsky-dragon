"""Bramka LLM na ``openai`` 3.x / ``httpx2`` (kontrakt C8, K5 §3.3).

Pula klientów per ``(base_url, api_key)``, timeouty per wywołanie, mapowanie wyjątków SDK/httpx2
na błędy modułu, parsowanie `` thinking``; klucz API nigdy nie trafia do logów ani ``details``.
"""

import asyncio
import base64
import math
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

import httpx2
import openai
from openai.types.chat import ChatCompletionChunk
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.timeutil import Clock, SystemClock
from app.llm.cache import cached_chat, cached_embed_query, cached_vision
from app.llm.errors import LLMUnavailable, map_http_error, map_sdk_error
from app.llm.param_retry import retry_without_unsupported
from app.llm.rate_limit import call_with_retry
from app.llm.think import ThinkStreamParser, split_think
from app.llm.types import (
    ChatMessage,
    ChatResult,
    ModelRef,
    ReasoningDelta,
    StreamEnd,
    StreamEvent,
    TextDelta,
)

_SCORE_MIN = 0.0
_SCORE_MAX = 1.0


@dataclass(frozen=True)
class LLMTimeouts:
    """Timeouty pojedynczych wywołań w sekundach (C8)."""

    chat: float = 120.0  # z Settings.llm_timeout_s przy konstrukcji domyślnej
    embed: float = 60.0
    stream_read: float = 30.0
    stream_total: float = 300.0
    rerank: float = 30.0
    vision: float = 120.0


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _stream_event(kind: str, text: str) -> StreamEvent:
    if kind == "reasoning":
        return ReasoningDelta(text)
    return TextDelta(text)


def _vision_messages(prompt: str, image_png: bytes) -> list[ChatMessage]:
    """Wiadomość czatu z obrazem jako ``data:`` URL (C8)."""
    encoded = base64.b64encode(image_png).decode("ascii")
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }
    ]


class OpenAIGateway:
    """Implementacja portu ``LLMGateway`` na SDK ``openai`` 3.x."""

    def __init__(  # noqa: PLR0913 — sygnatura z kontraktu C8
        self,
        settings: Settings,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        clock: Clock | None = None,
        timeouts: LLMTimeouts | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
        event_hooks: Mapping[str, list[Callable[..., Any]]] | None = None,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker  # cache w bazie — zadanie T5
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._timeouts = timeouts or LLMTimeouts(chat=settings.llm_timeout_s)
        self._transport = transport
        self._event_hooks = event_hooks
        self._pool: dict[tuple[str, str], tuple[openai.AsyncOpenAI, httpx2.AsyncClient]] = {}
        # klucze odrzucone przez model (kontrakt §3): per model.name, w pamięci procesu
        self._dropped: dict[str, frozenset[str]] = {}

    async def chat(  # noqa: PLR0913
        self,
        model: ModelRef,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
        cache: bool = False,
    ) -> ChatResult:
        call = partial(
            self._chat,
            model,
            messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            extra=extra,
            timeout_s=self._timeouts.chat,
        )
        if not cache or self._sessionmaker is None:
            return await call()
        return await cached_chat(
            self._sessionmaker,
            self._clock,
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            extra=extra,
            call=call,
        )

    async def chat_stream(  # noqa: PLR0913
        self,
        model: ModelRef,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        client, _http = self._client(model)
        parser = ThinkStreamParser()
        tokens_in = 0
        tokens_out = 0
        finish_reason: str | None = None
        stream: AsyncIterator[ChatCompletionChunk] | None = None
        try:
            async with asyncio.timeout(self._timeouts.stream_total):
                # 400 przychodzi przy otwarciu strumienia (przed zdarzeniami) — jedno ponowienie
                opened = await retry_without_unsupported(
                    lambda: client.chat.completions.create(
                        model=model.name,
                        messages=cast(Any, list(messages)),
                        stream=True,
                        stream_options={"include_usage": True},
                        timeout=httpx2.Timeout(self._timeouts.stream_read),
                        **self._options(model, extra, temperature, top_p, max_tokens),
                    ),
                    model=model.name,
                    dropped=self._dropped,
                )
                stream = opened
                async for chunk in opened:
                    # usage czytany z każdego chunku (przychodzi na ostatnim, choices=[])
                    if chunk.usage is not None:
                        tokens_in = chunk.usage.prompt_tokens
                        tokens_out = chunk.usage.completion_tokens
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason is not None:
                        finish_reason = choice.finish_reason
                    if not choice.delta.content:
                        continue
                    for kind, text in parser.feed(choice.delta.content):
                        yield _stream_event(kind, text)
                for kind, text in parser.flush():
                    yield _stream_event(kind, text)
        except openai.OpenAIError as exc:
            raise map_sdk_error(exc, model.name) from exc
        except TimeoutError:
            raise LLMUnavailable(
                "LLM stream timeout",
                details={"model": model.name, "status": None},
            ) from None
        finally:
            if stream is not None:
                await cast(Any, stream).close()
        yield StreamEnd(tokens_in=tokens_in, tokens_out=tokens_out, finish_reason=finish_reason)

    async def embed(self, model: ModelRef, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        client, _http = self._client(model)
        # Ponowienia 429 robi pętla bramki (C4), nie SDK — pojedyncze wywołanie bez retry SDK.
        sdk = client.with_options(max_retries=0)

        async def call() -> openai.types.CreateEmbeddingResponse:
            return await sdk.embeddings.create(
                model=model.name,
                input=list(texts),
                encoding_format="float",
                timeout=self._timeouts.embed,
            )

        try:
            response = await call_with_retry(call, what="Embedding", model_name=model.name)
        except openai.OpenAIError as exc:
            raise map_sdk_error(exc, model.name) from exc
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]

    async def embed_query(self, model: ModelRef, text: str) -> list[float]:
        """embedding_cache gdy jest sessionmaker (C10); bez bazy zawsze wywołanie LLM."""
        if self._sessionmaker is None:
            return await self._embed_one(model, text)
        return await cached_embed_query(
            self._sessionmaker,
            self._clock,
            model,
            text,
            call=partial(self._embed_one, model, text),
        )

    async def _embed_one(self, model: ModelRef, text: str) -> list[float]:
        """Pojedynczy wektor — embed jednego tekstu (C8)."""
        return (await self.embed(model, [text]))[0]

    async def rerank(self, model: ModelRef, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        base_url, api_key = self._endpoint(model)
        _client, http = self._client(model)
        try:
            response = await http.post(
                f"{base_url.rstrip('/')}/rerank",
                json={"model": model.name, "query": query, "documents": list(documents)},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=self._timeouts.rerank,
            )
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            raise map_http_error(exc, model.name) from exc
        payload: dict[str, Any] = response.json()
        scores = [0.0] * len(documents)
        values = {int(item["index"]): float(item["relevance_score"]) for item in payload["results"]}
        if any(not (_SCORE_MIN <= score <= _SCORE_MAX) for score in values.values()):
            # wyniki spoza [0,1] (np. logity) — sigmoid na wszystkich zwróconych (C8)
            values = {index: _sigmoid(score) for index, score in values.items()}
        for index, score in values.items():
            if 0 <= index < len(scores):
                scores[index] = score
        return scores

    async def vision(  # noqa: PLR0913 — sygnatura z portu (C3)
        self,
        model: ModelRef,
        prompt: str,
        image_png: bytes,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cache: bool = False,
    ) -> str:
        call = partial(
            self._chat,
            model,
            _vision_messages(prompt, image_png),
            temperature=temperature,
            top_p=None,
            max_tokens=max_tokens,
            extra=None,
            timeout_s=self._timeouts.vision,
            rate_limit=True,  # ścieżka VlmRecognizer: ponowienia 429 w bramce (C4)
        )
        if not cache:
            return (await call()).text
        # cache=True — llm_cache wizji (C3); bez sessionmaker od razu model (chybienie).
        return await cached_vision(
            self._sessionmaker,
            self._clock,
            model=model,
            base_url=self._endpoint(model)[0],
            image_png=image_png,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=model.extra.get("extra_body"),
            call=call,
        )

    async def aclose(self) -> None:
        for client, http in self._pool.values():
            await client.close()
            await http.aclose()
        self._pool.clear()

    async def _chat(  # noqa: PLR0913 — wspólny trzon chat/vision (timeout per wywołanie)
        self,
        model: ModelRef,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None,
        top_p: float | None,
        max_tokens: int | None,
        extra: Mapping[str, Any] | None,
        timeout_s: float,
        rate_limit: bool = False,
    ) -> ChatResult:
        client, _http = self._client(model)
        # Ścieżka z ponowieniami 429 (wizja) nie może mnożyć ich z retry SDK (C4).
        sdk = client.with_options(max_retries=0) if rate_limit else client

        def create() -> Any:
            return sdk.chat.completions.create(
                model=model.name,
                messages=cast(Any, list(messages)),
                stream=False,
                timeout=timeout_s,
                **self._options(model, extra, temperature, top_p, max_tokens),
            )

        async def call() -> Any:
            return await retry_without_unsupported(create, model=model.name, dropped=self._dropped)

        try:
            completion = (
                await call_with_retry(call, what="Vision", model_name=model.name)
                if rate_limit
                else await call()
            )
        except openai.OpenAIError as exc:
            raise map_sdk_error(exc, model.name) from exc
        choice = completion.choices[0]
        usage = completion.usage
        reasoning, text = split_think(choice.message.content or "")
        return ChatResult(
            text=text,
            reasoning=reasoning,
            tokens_in=usage.prompt_tokens if usage is not None else 0,
            tokens_out=usage.completion_tokens if usage is not None else 0,
            finish_reason=choice.finish_reason,
        )

    def _endpoint(self, model: ModelRef) -> tuple[str, str]:
        """(base_url, api_key) modelu — None znaczy wartość z Settings (C8)."""
        base_url = model.base_url or self._settings.llm_base_url
        api_key = (model.api_key or self._settings.llm_api_key).get_secret_value() or "none"
        return base_url, api_key

    def _client(self, model: ModelRef) -> tuple[openai.AsyncOpenAI, httpx2.AsyncClient]:
        """Klient SDK i klient httpx2 z puli per (base_url, api_key) — leniwie (C8)."""
        key = self._endpoint(model)
        entry = self._pool.get(key)
        if entry is None:
            base_url, api_key = key
            http = httpx2.AsyncClient(
                transport=self._transport,
                event_hooks=self._event_hooks,
                timeout=httpx2.Timeout(self._timeouts.chat),
                # Pula ≥ MAX_CONCURRENCY (32), kontrakt C4 — zapas na równoległe partie.
                limits=httpx2.Limits(max_connections=64, max_keepalive_connections=32),
            )
            client = openai.AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                max_retries=self._settings.llm_max_retries,
                timeout=self._timeouts.chat,
                http_client=http,
            )
            entry = (client, http)
            self._pool[key] = entry
        return entry

    def _options(
        self,
        model: ModelRef,
        extra: Mapping[str, Any] | None,
        temperature: float | None,
        top_p: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        """Parametry create(): None = nie wysyłane; pomija odrzucone; extra_body scalone."""
        dropped = self._dropped.get(model.name, frozenset())
        options: dict[str, Any] = {}
        if temperature is not None and "temperature" not in dropped:
            options["temperature"] = temperature
        if top_p is not None and "top_p" not in dropped:
            options["top_p"] = top_p
        if max_tokens is not None:
            options["max_tokens"] = max_tokens  # nigdy nie pomijany (kontrakt §3)
        extra_body = {**model.extra.get("extra_body", {}), **(extra or {})}
        extra_body = {key: value for key, value in extra_body.items() if key not in dropped}
        if extra_body:
            options["extra_body"] = extra_body
        return options
