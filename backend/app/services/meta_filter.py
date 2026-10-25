"""Generowanie warunków ``meta_data_filter`` modelem — ``auto``/``semi_auto`` (K11 §10f p. 5).

Port upstream ``common/metadata_utils.py::apply_meta_data_filter`` (gałęzie ``auto``/``semi_auto``,
:239-266) i ``rag/prompts/generator.py::gen_meta_filter`` (:527-564). Prompt ``meta_filter.md``
renderujemy ręcznie (bez jinja2): ``- Dostępne klucze metadanych: <json>`` oraz
``- Pytanie użytkownika: "<pytanie>"`` to linie czytane przez fake-llm (K10 „Poprawka 2026-10-11b"),
więc muszą wystąpić w tej dokładnej postaci.
Odpowiedź modelu parsujemy jako JSON (tolerancja ogrodzeń ```); niepoprawna odpowiedź albo puste
``conditions`` → brak zawężenia (``None``), nie błąd (złoto ``metadata_e6--43/44``). Warunki
budujemy tym samym kodem co ``manual`` (``meta_data_filter_to_condition`` — aliasy ``op``
mapowane tak samo).
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.errors import ValidationFailed, WDError
from app.domain.retrieval.metadata import (
    MetadataCondition,
    match_documents,
    meta_data_filter_to_condition,
)
from app.llm.gateway import LLMGateway
from app.llm.registry import ModelRegistry
from app.llm.types import ModelRef
from app.prompts import load_prompt

_PROMPT = load_prompt("meta_filter")
# Zdjęcie bloku myślenia i ogrodzeń ``` z odpowiedzi modelu (upstream generator.py:559).
_THINK = re.compile(r"^.*</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\n?")
# Linia z ograniczeniami operatorów w szablonie jinja (render ręczny).
_CONSTRAINTS_BLOCK = "{% if constraints %}\n- Operator constraints: {{ constraints }}\n{% endif %}"

__all__ = [
    "available_metadata",
    "document_scope",
    "generate_condition",
    "parse_filter_response",
    "render_filter_prompt",
    "resolve_filter",
]


def available_metadata(
    metas: Mapping[str, Mapping[str, Any]], keys: set[str] | None = None
) -> dict[str, list[str]]:
    """Słownik ``klucz → lista wartości`` ze wszystkich dokumentów zakresu (K11 §10f p. 5).

    Wartości jako **stringi**, unikalne, w kolejności pierwszego wystąpienia; wartość listowa
    rozwijana na osobne wpisy. ``keys`` (``semi_auto``) zawęża zbiór kluczy; ``None`` = wszystkie.
    """
    result: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for meta in metas.values():
        for key, value in meta.items():
            if keys is not None and key not in keys:
                continue
            bucket = result.setdefault(key, [])
            bucket_seen = seen.setdefault(key, set())
            for item in value if isinstance(value, list) else [value]:
                if item is None:
                    continue
                text = str(item)
                if text in bucket_seen:
                    continue
                bucket_seen.add(text)
                bucket.append(text)
    return result


def render_filter_prompt(
    available: Mapping[str, list[str]], question: str, constraints: Mapping[str, str] | None = None
) -> str:
    """Renderuje ``meta_filter.md``: data, klucze (JSON) i pytanie; opcjonalne ograniczenia op.

    Linie ``- Dostępne klucze metadanych: <json>`` i ``- Pytanie użytkownika: "<pytanie>"`` muszą
    wystąpić w tej dokładnej postaci (fake-llm rozpoznaje po nich prompt — K10 2026-10-11b); JSON
    bez ``ensure_ascii`` wyłącznie, by zachować znaki narodowe.
    """
    text = _PROMPT.replace("{{ current_date }}", datetime.date.today().isoformat())
    text = text.replace("{{ metadata_keys }}", json.dumps(available, ensure_ascii=False))
    text = text.replace("{{ user_question }}", question)
    if constraints:
        replacement = "- Operator constraints: " + json.dumps(constraints, ensure_ascii=False)
        text = text.replace(_CONSTRAINTS_BLOCK, replacement)
    else:
        text = text.replace(_CONSTRAINTS_BLOCK, "")
    return text


def parse_filter_response(text: str) -> MetadataCondition | None:
    """Odpowiedź modelu → :class:`MetadataCondition`; nie-JSON albo puste warunki → ``None``.

    Tolerancja ogrodzeń ``` i bloku `` thinking``; ``logic`` inny niż ``and``/``or`` → ``and``.
    Pojedynczy warunek niepoprawny (brak ``key``/``op``) → ``None`` (całość odrzucona — brak
    zawężenia, złoto ``metadata_e6--43``).
    """
    cleaned = _FENCE.sub("", _THINK.sub("", text))
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    conditions = value.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        return None
    logic = value.get("logic", "and")
    if logic not in ("and", "or"):
        logic = "and"
    try:
        return meta_data_filter_to_condition(
            {"method": "manual", "logic": logic, "manual": conditions}
        )
    except (ValidationFailed, WDError):
        return None


def _semi_auto_selection(spec: Mapping[str, Any]) -> tuple[set[str], dict[str, str]]:
    """Klucze i ograniczenia ``op`` z listy ``semi_auto`` (upstream :246-257: str albo dict)."""
    keys: set[str] = set()
    constraints: dict[str, str] = {}
    for item in spec.get("semi_auto") or []:
        if isinstance(item, str):
            keys.add(item)
        elif isinstance(item, Mapping):
            key = item.get("key")
            if isinstance(key, str):
                keys.add(key)
                op = item.get("op")
                if isinstance(op, str):
                    constraints[key] = op
    return keys, constraints


async def generate_condition(
    gateway: LLMGateway,
    model: ModelRef,
    metas: Mapping[str, Mapping[str, Any]],
    question: str,
    spec: Mapping[str, Any],
) -> MetadataCondition | None:
    """Warunek z ``meta_data_filter``: ``manual`` wprost, ``auto``/``semi_auto`` przez model.

    Brak kluczy (``semi_auto`` bez pola) albo brak dostępnych metadanych → ``None`` (brak
    zawężenia). Wywołanie modelu poza transakcjami bazy (bramka LLM).
    """
    method = spec.get("method")
    if method not in ("auto", "semi_auto"):
        return meta_data_filter_to_condition(spec)
    keys: set[str] | None = None
    constraints: dict[str, str] = {}
    if method == "semi_auto":
        keys, constraints = _semi_auto_selection(spec)
        if not keys:
            return None
    available = available_metadata(metas, keys)
    if not available:
        return None
    messages: Sequence[dict[str, str]] = [
        {"role": "system", "content": render_filter_prompt(available, question, constraints)},
        {"role": "user", "content": "Generate filters:"},
    ]
    result = await gateway.chat(model, messages, temperature=0.2, cache=True)
    return parse_filter_response(result.text)


async def resolve_filter(
    gateway: LLMGateway,
    models: ModelRegistry,
    metas: Mapping[str, Mapping[str, Any]],
    question: str,
    spec: Mapping[str, Any],
) -> MetadataCondition | None:
    """``meta_data_filter`` → warunek: ``manual`` wprost, ``auto``/``semi_auto`` modelem czatu.

    Model czatu domyślny profilu (jak pozostałe pomocnicze wywołania czatu); wywołanie poza
    transakcjami bazy.
    """
    if spec.get("method") not in ("auto", "semi_auto"):
        return meta_data_filter_to_condition(spec)
    model = await models.resolve(None, "chat")
    return await generate_condition(gateway, model, metas, question, spec)


def document_scope(
    metas: Mapping[str, Mapping[str, Any]],
    condition: MetadataCondition | None,
    document_ids: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    """Zakres dokumentów po warunku metadanych: ``None`` = bez filtra; ``()`` = filtr wybrał nic.

    Zbiór dopasowanych dokumentów zawęża się do ``document_ids`` żądania (jeśli podane).
    """
    if condition is None:
        return document_ids
    allowed = match_documents(metas, condition)
    if not allowed:
        return ()
    if document_ids is not None:
        allowed = allowed & set(document_ids)
    return tuple(sorted(allowed))
