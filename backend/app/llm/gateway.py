"""Port bramy LLM (kontrakt C4, K5 §3.3) — implementacja w app.llm.openai_gateway."""

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Protocol

from app.llm.types import ChatMessage, ChatResult, ModelRef, StreamEvent


class LLMGateway(Protocol):
    """Port bramy LLM: czat (zwykły i strumień), embeddingi, rerank, wizja."""

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
    ) -> ChatResult: ...

    def chat_stream(  # noqa: PLR0913
        self,
        model: ModelRef,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]: ...

    # dokładnie jeden StreamEnd na końcu; usage z ostatniego chunku (include_usage);
    # brak usage → 0/0

    async def embed(self, model: ModelRef, texts: Sequence[str]) -> list[list[float]]: ...

    # kolejność = texts; pusta lista → [] bez wywołania

    async def embed_query(self, model: ModelRef, text: str) -> list[float]: ...

    # przez embedding_cache (K5 §3.5)

    async def rerank(
        self, model: ModelRef, query: str, documents: Sequence[str]
    ) -> list[float]: ...

    # POST {base_url}/rerank (httpx2, kształt K10 §5); wynik [0,1] wg kolejności documents;
    # wyniki spoza [0,1] → sigmoid; brak indeksu → 0.0

    async def vision(  # noqa: PLR0913 — port bramy (C4, E5-H8e §C3)
        self,
        model: ModelRef,
        prompt: str,
        image_png: bytes,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cache: bool = False,
    ) -> str: ...

    # chat z częścią image_url data:image/png;base64,…; cache=True + sessionmaker → llm_cache (C3)

    async def aclose(self) -> None: ...
