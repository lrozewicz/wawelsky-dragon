"""Budowa korektora diakrytyków z ``parser_config["diacritics"]`` (CONTRACT WP E5-H4b §4, DEC-249).

Konfiguracja jest opcjonalnym obiektem ``{"layer": bool, "wordfreq": bool, "model": str | null}``.
Klucz nieobecny albo ``None`` daje domyślne opcje (tylko warstwa PDF, 0 USD). Walidacja typów i
brak modelu kończą się :class:`PermanentError` (ten sam kanał co nieznany model); pusty ``model``
nigdy nie trafia do ``ModelRegistry.resolve`` (P6 — to byłby domyślny model czatu).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.errors import NotFound
from app.llm.gateway import LLMGateway
from app.llm.registry import ModelRegistry
from app.parsing.diacritics_llm import LlmDiacriticsCorrector
from app.parsing.diacritics_stage import (
    WORDFREQ_DEFAULT,
    DiacriticsCorrector,
    DiacriticsOptions,
    StageCorrector,
)
from app.worker.errors import PermanentError

_KEY = "parser_config.diacritics"


async def build_diacritics(
    models: ModelRegistry, llm: LLMGateway, pc: Mapping[str, Any]
) -> DiacriticsCorrector | None:
    """Buduje :class:`StageCorrector` z ``parser_config["diacritics"]`` (brak etapów → ``None``)."""
    raw = pc.get("diacritics")
    if raw is None:
        return StageCorrector(DiacriticsOptions())
    if not isinstance(raw, dict):
        raise PermanentError(f"invalid {_KEY}: diacritics")
    layer = _flag(raw, "layer", True)
    wordfreq = _flag(raw, "wordfreq", WORDFREQ_DEFAULT)
    corrector = await _llm_corrector(models, llm, raw.get("model"))
    if not layer and not wordfreq and corrector is None:
        return None
    return StageCorrector(DiacriticsOptions(layer=layer, wordfreq=wordfreq, llm=corrector))


def _flag(raw: Mapping[str, Any], key: str, default: bool) -> bool:
    """Wartość bool klucza; ``None`` = brak klucza, inny typ → :class:`PermanentError`."""
    value = raw.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise PermanentError(f"invalid {_KEY}: {key}")
    return value


async def _llm_corrector(
    models: ModelRegistry, llm: LLMGateway, model: Any
) -> LlmDiacriticsCorrector | None:
    """Korektor LLM dla niepustej nazwy modelu; ``None``, brak i białe znaki → etap wyłączony."""
    if model is None:
        return None
    if not isinstance(model, str):
        raise PermanentError(f"invalid {_KEY}: model")
    name = model.strip()
    if not name:
        return None
    try:
        ref = await models.resolve(name, "chat")
    except NotFound as exc:
        raise PermanentError(f"diacritics model not found: {model}") from exc
    return LlmDiacriticsCorrector(llm, ref)
