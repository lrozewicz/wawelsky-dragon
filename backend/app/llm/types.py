"""Typy modułu LLM (kontrakt C2, K5 §3.2)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import SecretStr

ModelType = Literal["chat", "embedding", "rerank", "image2text"]


@dataclass(frozen=True)
class ModelRef:
    """Referencja modelu — to, co bramka potrzebuje na drucie."""

    id: str | None  # models.id; None dla modelu spoza rejestru (testy)
    name: str  # nazwa na drucie bramki (models.name)
    model_type: ModelType
    base_url: str | None = None  # None = WD_LLM_BASE_URL
    api_key: SecretStr | None = None  # None = WD_LLM_API_KEY; odszyfrowany api_key_enc
    dimension: int | None = None
    max_tokens: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)  # m.in. extra_body (przekazywane do SDK)


ChatMessage = Mapping[str, Any]  # {"role": ..., "content": str | list[part]} — format OpenAI


@dataclass(frozen=True)
class ChatResult:
    """Wynik jednorazowego wywołania czatu."""

    text: str  # bez bloku <think>
    reasoning: str | None  # treść <think>…</think> (None, gdy brak)
    tokens_in: int
    tokens_out: int
    finish_reason: str | None


@dataclass(frozen=True)
class TextDelta:
    """Fragment tekstu odpowiedzi w strumieniu."""

    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    """Fragment rozumowania (<think>) w strumieniu."""

    text: str


@dataclass(frozen=True)
class StreamEnd:
    """Zamykające zdarzenie strumienia — dokładnie jedno na strumień."""

    tokens_in: int
    tokens_out: int
    finish_reason: str | None


StreamEvent = TextDelta | ReasoningDelta | StreamEnd
