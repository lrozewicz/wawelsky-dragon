"""Konfiguracja czatu: domyślne prompt_config i parametry generacji (CONTRACT WP E1-8 C7)."""

# Tekst domyślnego promptu systemowego napisany własnymi słowami (E5-7 / DEC-331, licencja);
# struktura pól, wartości flag i pozostałe napisy bez zmian względem wcześniejszej konfiguracji.

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

DEFAULT_PROMPT_CONFIG: Final[Mapping[str, Any]] = {
    "system": (
        "You are an assistant grounded in the dataset below; answer from it and keep the running "
        "conversation in mind.\n"
        "Rules:\n"
        "  - Walk through the dataset entries matching the question and lay them out one by one.\n"
        "  - Back a full answer with the data you found (e.g. answer a Polish question about the "
        "Wawel dragon with the legend facts from the dataset).\n"
        "  - Reply in the same language as the question.\n"
        "  - If the dataset does not cover the question, say so openly and finish with this exact "
        'sentence: "The answer you are looking for is not found in the dataset!"\n'
        "Knowledge base:\n"
        "      {knowledge}\n"
        "End of knowledge base."
    ),
    "prologue": "Hi! I'm your assistant. What can I do for you?",
    "parameters": [{"key": "knowledge", "optional": False}, {"key": "date", "optional": True}],
    "empty_response": "Sorry! No relevant content was found in the knowledge base!",
    "quote": True,
    "tts": False,
    "refine_multiturn": True,
}

DEFAULT_DIRECT_CHAT_PROMPT_CONFIG: Final[Mapping[str, Any]] = {
    "system": "",
    "prologue": "",
    "parameters": [],
    "empty_response": "",
    "quote": False,
    "tts": False,
    "refine_multiturn": True,
}


@dataclass(frozen=True)
class RetrievalDefaults:
    """Parametry retrievalu ścieżki bez czatu (``/sessions/ask``, upstream ``async_ask``)."""

    page_size: int
    similarity_threshold: float
    vector_similarity_weight: float
    top_k: int
    rerank_candidates_count: int


# Upstream v0.24 ``dialog_service.py:1115-1130`` (page_size=12, prog 0.1, w=0.3, top=1024).
ASK_RETRIEVAL: Final[RetrievalDefaults] = RetrievalDefaults(
    page_size=12,
    similarity_threshold=0.1,
    vector_similarity_weight=0.3,
    top_k=1024,
    rerank_candidates_count=64,
)

LLM_SETTING_FALLBACK: Final[Mapping[str, float]] = {
    "temperature": 0.1,
    "top_p": 0.3,
    "frequency_penalty": 0.7,
    "presence_penalty": 0.4,
}

_GENERATION_KEYS: Final = (
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "max_tokens",
)
_EXTRA_KEYS: Final = ("frequency_penalty", "presence_penalty")


def merge_prompt_config(stored: Mapping[str, Any]) -> dict[str, Any]:
    """Domyślny prompt_config nadpisany wartościami zapisanymi w czacie."""
    return {**DEFAULT_PROMPT_CONFIG, **stored}


@dataclass(frozen=True)
class GenerationParams:
    """Parametry wywołania LLM po rozstrzygnięciu flag ``*_enabled`` i budżetu tokenów."""

    temperature: float | None
    top_p: float | None
    max_tokens: int | None
    extra: dict[str, Any]  # frequency_penalty / presence_penalty (gdy obecne)


def generation_params(
    chat_setting: Mapping[str, Any],
    override: Mapping[str, Any] | None,
    *,
    model_max_tokens: int,
    used_tokens: int,
) -> GenerationParams:
    """Port DS l. 826, 852-853: klucz pomijany gdy ``k_enabled is False`` albo brak klucza.

    ``max_tokens = min(ustawione, model_max_tokens - used_tokens)``; override wygrywa
    z ustawieniami czatu, fallback domyka resztę.
    """
    merged: dict[str, Any] = {**LLM_SETTING_FALLBACK, **chat_setting, **(override or {})}
    chosen: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    max_tokens: int | None = None
    for key in _GENERATION_KEYS:
        if merged.get(f"{key}_enabled") is False or key not in merged:
            continue
        if key == "max_tokens":
            max_tokens = min(int(merged["max_tokens"]), model_max_tokens - used_tokens)
        elif key in _EXTRA_KEYS:
            extra[key] = merged[key]
        else:
            chosen[key] = merged[key]
    return GenerationParams(
        temperature=chosen.get("temperature"),
        top_p=chosen.get("top_p"),
        max_tokens=max_tokens,
        extra=extra,
    )
