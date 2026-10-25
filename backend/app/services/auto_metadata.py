"""Auto-metadane przy parsowaniu: schemat z ``parser_config``, prompt ``meta_data.md``, scalanie.

Moduł czysty (bez bazy) — wywołanie modelu przez ``LLMGateway``; wynik scalany z ``meta_fields``
dokumentu. Port zachowania upstream ``rag/svr/task_executor.py`` (``gen_metadata`` +
``common/metadata_utils.py::update_metadata_to``) i promptu ``rag/prompts/meta_data.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.llm.errors import LLMError
from app.llm.gateway import LLMGateway
from app.llm.types import ModelRef
from app.prompts import load_prompt

_PROMPT = load_prompt("meta_data")
_MAX_CONTENT_CHARS = 16000  # ograniczenie treści do analizy (K11 §10f p.4)
_THINK_PREFIX = re.compile(r"^.*</think>", re.DOTALL)
_TYPE_MAP = {"string": "string", "time": "string", "number": "number"}


class AutoMetadataError(Exception):
    """Błąd wywołania modelu auto-metadanych — parsowanie trwa dalej (K11 §10f p.4)."""


def _field_property(field: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Właściwość JSON-Schema z pola ``{key,type,description?,enum?}``; brak ``key`` → ``None``."""
    key = field.get("key")
    if not isinstance(key, str) or not key:
        return None
    spec: dict[str, Any] = {}
    enum = field.get("enum")
    if enum:
        spec["type"] = "string"
        spec["enum"] = list(enum)
    elif field.get("type") == "list":
        spec["type"] = "array"
        spec["items"] = {"type": "string"}
    else:
        spec["type"] = _TYPE_MAP.get(str(field.get("type") or "string"), "string")
    description = field.get("description")
    if description:
        spec["description"] = description
    return key, spec


def _properties(value: Any) -> dict[str, Any]:
    """Właściwości ze schematu JSON albo z listy pól; inny kształt → pusty słownik."""
    if isinstance(value, dict):
        if value.get("$schema") or value.get("type") == "object":
            props = value.get("properties")
            return dict(props) if isinstance(props, dict) else {}
        return {}
    if isinstance(value, list):
        result: dict[str, Any] = {}
        for item in value:
            if isinstance(item, dict):
                pair = _field_property(item)
                if pair is not None:
                    result[pair[0]] = pair[1]
        return result
    return {}


def metadata_schema(parser_config: Mapping[str, Any]) -> dict[str, Any] | None:
    """JSON-Schema pól auto-metadanych; ``None`` gdy krok wyłączony albo brak pól (K11 §10f p.4)."""
    if not parser_config.get("enable_metadata"):
        return None
    properties = {
        **_properties(parser_config.get("metadata")),
        **_properties(parser_config.get("built_in_metadata")),
    }
    if not properties:
        return None
    return {"type": "object", "properties": properties, "additionalProperties": False}


def render_prompt(schema: Mapping[str, Any], content: str) -> str:
    """Podstawia schemat (JSON) i treść w szablon ``meta_data.md`` (kolejność: schemat, treść)."""
    rendered = _PROMPT.replace("{{ schema }}", json.dumps(schema, ensure_ascii=False))
    return rendered.replace("{{ content }}", content)


def _strip_fence(text: str) -> str:
    """Zdejmuje ogrodzenie ``` z odpowiedzi modelu (jeśli jest)."""
    if not text.startswith("```"):
        return text
    body = text.split("\n", 1)[1] if "\n" in text else ""
    return body.rsplit("```", 1)[0].strip()


def parse_metadata(raw: str) -> dict[str, Any]:
    """Odpowiedź modelu → słownik; nie-JSON / nie-obiekt → ``{}`` (bez ``json_repair``)."""
    text = _strip_fence(_THINK_PREFIX.sub("", raw).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        return {}
    try:
        parsed: dict[str, Any] = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    return parsed


def _content(chunk_texts: Sequence[str]) -> str:
    """Treść do analizy: teksty chunków złączone ``\\n``, obcięte do ``_MAX_CONTENT_CHARS``."""
    return "\n".join(chunk_texts)[:_MAX_CONTENT_CHARS]


async def extract_auto_metadata(
    gateway: LLMGateway,
    model: ModelRef,
    schema: Mapping[str, Any],
    chunk_texts: Sequence[str],
) -> dict[str, Any]:
    """Wynik modelu dla złączonej treści chunków; błąd modelu → ``AutoMetadataError``."""
    messages: Sequence[dict[str, str]] = [
        {"role": "system", "content": render_prompt(schema, _content(chunk_texts))},
        {"role": "user", "content": "Output: "},
    ]
    try:
        result = await gateway.chat(model, messages, temperature=0.2, cache=True)
    except LLMError as exc:
        raise AutoMetadataError(str(exc)) from exc
    return parse_metadata(result.text)


def _is_empty(value: Any) -> bool:
    """Pusta wartość modelu (None / "" / [] / {}) — nie nadpisuje istniejącego pola."""
    return value is None or value in ("", [], {})


def merge_metadata(
    existing: Mapping[str, Any], extracted: Mapping[str, Any], schema: Mapping[str, Any]
) -> tuple[dict[str, Any], int]:
    """Scala wynik modelu w ``meta_fields``: nowe klucze dopisane, istniejące nadpisane tylko
    niepustą wartością, klucze spoza schematu odrzucone; nic nie znika (K11 §10f p.4).

    Zwraca ``(nowe meta_fields, liczba dodanych/zmienionych pól)``.
    """
    props = schema.get("properties")
    allowed = props if isinstance(props, dict) else {}
    merged = dict(existing)
    changed = 0
    for key, value in extracted.items():
        if key not in allowed or _is_empty(value):
            continue
        if merged.get(key) != value:
            changed += 1
        merged[key] = value
    return merged, changed
