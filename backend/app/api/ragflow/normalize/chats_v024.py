"""Normalizacja ciała Chat v0.24 → kanoniczne v0.27 (CONTRACT C1, 02-api §7.1)."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.core.errors import Conflict

# llm → llm_setting: przenoszone tylko te klucze (C1).
_LLM_SETTING_KEYS = (
    "temperature",
    "top_p",
    "presence_penalty",
    "frequency_penalty",
    "max_tokens",
)

# prompt → prompt_config: (klucz v0.24, klucz kanoniczny) — tylko obecne.
_PROMPT_CONFIG_KEYS = (
    ("prompt", "system"),
    ("opener", "prologue"),
    ("show_quote", "quote"),
    ("variables", "parameters"),
    ("empty_response", "empty_response"),
    ("tts", "tts"),
    ("refine_multiturn", "refine_multiturn"),
)

# prompt → klucze górnego poziomu przenoszone pod tą samą nazwą (C1).
_PROMPT_TOP_LEVEL_KEYS = ("similarity_threshold", "top_n", "top_k")


def _translate_llm(canonical: dict[str, Any]) -> None:
    """``llm`` → ``llm_id`` + ``llm_setting`` (klucz ``llm`` zawsze znika); C1."""
    llm = canonical.pop("llm")
    if not isinstance(llm, Mapping):
        raise Conflict("`llm` should be an object.")
    if "model_name" in llm:
        canonical["llm_id"] = llm["model_name"]
    llm_setting = {key: llm[key] for key in _LLM_SETTING_KEYS if key in llm}
    if llm_setting:
        canonical["llm_setting"] = llm_setting


def _translate_prompt(canonical: dict[str, Any]) -> None:
    """``prompt`` → ``prompt_config`` + klucze górnego poziomu (C1)."""
    prompt = canonical.pop("prompt")
    if not isinstance(prompt, Mapping):
        raise Conflict("`prompt` should be an object.")
    prompt_config = {
        canonical_key: prompt[source_key]
        for source_key, canonical_key in _PROMPT_CONFIG_KEYS
        if source_key in prompt
    }
    if prompt_config:
        canonical["prompt_config"] = prompt_config
    for key in _PROMPT_TOP_LEVEL_KEYS:
        if key in prompt:
            canonical[key] = prompt[key]
    if "rerank_model" in prompt:
        canonical["rerank_id"] = prompt["rerank_model"]
    if "keywords_similarity_weight" in prompt:
        weight = prompt["keywords_similarity_weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise Conflict("`keywords_similarity_weight` should be a number.")
        canonical["vector_similarity_weight"] = round(1 - weight, 6)


def to_canonical(body: Mapping[str, Any]) -> dict[str, Any]:
    """Ciało Chat v0.24 → ciało kanoniczne (v0.27); czysta funkcja, nie mutuje wejścia."""
    # Kopia głęboka: klucze spoza tabeli przechodzą bez zmian, a wynik nie dzieli
    # obiektów z wejściem (C1 p. 1).
    canonical: dict[str, Any] = deepcopy(dict(body))

    # avatar → icon (klucz z tabeli nadpisuje kanoniczny o tej samej nazwie).
    if "avatar" in canonical:
        canonical["icon"] = canonical.pop("avatar")

    if "llm" in canonical:
        _translate_llm(canonical)

    if "prompt" in canonical:
        _translate_prompt(canonical)

    # datasets[].id → dataset_ids, tylko gdy wejście nie ma własnego dataset_ids.
    datasets = canonical.pop("datasets", None)
    if isinstance(datasets, list) and "dataset_ids" not in canonical:
        canonical["dataset_ids"] = [
            item["id"] for item in datasets if isinstance(item, Mapping) and "id" in item
        ]

    # Klucze v0.24 nieistniejące w kanonie (C1): do_refer, show_quotation.
    canonical.pop("do_refer", None)
    canonical.pop("show_quotation", None)

    return canonical
