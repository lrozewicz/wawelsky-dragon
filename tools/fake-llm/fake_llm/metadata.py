"""Deterministyczne odpowiedzi na prompty metadanych (K10 „Poprawka 2026-10-11b").

Dwa tryby rozpoznawane po nagłówku wiadomości systemowej, przed innymi scenariuszami czatu:
auto-metadane (`## Rola: specjalista od wyciągania metadanych.`) i filtr metadanych
(`Jesteś generatorem warunków filtrowania metadanych.`). Nagłówki odpowiadają własnym
promptom Wawelskiego Smoka (`backend/app/prompts/meta_data.md` i `meta_filter.md`).
"""

import ast
import json
import re
from typing import Any

from fake_llm.answers import ChatMessage, message_text

_AUTO_HEADER = "## Rola: specjalista od wyciągania metadanych."
_FILTER_HEADER = "Jesteś generatorem warunków filtrowania metadanych."
_SCHEMA_HEADER = "## Schemat wyciągu:"
_CONTENT_HEADER = "## Treść dokumentu:"
_KEYS_PREFIX = "- Dostępne klucze metadanych:"
_QUERY_PREFIX = "- Pytanie użytkownika:"
_INVALID_MARKER = "FAKE_METADATA_INVALID"
_NOT_A_JSON = "not a json"
_QUERY_PATTERN = re.compile(re.escape(_QUERY_PREFIX) + r'\s*"(?P<query>.*)"')


def _matching_system_text(messages: list[ChatMessage]) -> str | None:
    """Tekst pierwszej wiadomości system zaczynającej się od nagłówka metadanych; inaczej `None`."""
    for message in messages:
        if message.role != "system":
            continue
        text = message_text(message)
        if text.lstrip().startswith((_AUTO_HEADER, _FILTER_HEADER)):
            return text
    return None


def _load_mapping(text: str) -> dict[str, Any]:
    """Słownik z tekstu: JSON albo Python-literal (upstream renderuje schemat przez `str()`)."""
    try:
        value = json.loads(text)
    except ValueError:
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return {}
    return value if isinstance(value, dict) else {}


def _word_pattern(value: str) -> re.Pattern[str]:
    """Wzorzec wystąpienia `value` jako osobnego słowa (bez rozróżniania wielkości liter)."""
    return re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", re.IGNORECASE)


def _line_index(lines: list[str], header: str) -> int | None:
    """Indeks pierwszej linii równej nagłówkowi (po przycięciu białych znaków); inaczej `None`."""
    for index, line in enumerate(lines):
        if line.strip() == header:
            return index
    return None


def _line_after(text: str, prefix: str) -> str | None:
    """Treść pierwszej linii zaczynającej się od `prefix` (bez prefiksu); inaczej `None`."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def _split_schema_content(text: str) -> tuple[str, str]:
    """Część między `## Schemat wyciągu:` a `## Treść dokumentu:` oraz treść po niej."""
    lines = text.splitlines()
    schema_start = _line_index(lines, _SCHEMA_HEADER)
    content_start = _line_index(lines, _CONTENT_HEADER)
    if schema_start is None or content_start is None or content_start <= schema_start:
        return "", text
    schema = "\n".join(lines[schema_start + 1 : content_start]).strip()
    content = "\n".join(lines[content_start + 1 :])
    return schema, content


def _property_value(name: str, spec: Any, content: str) -> str | None:
    """Wartość właściwości: pierwszy trafiony `enum` albo pierwsza pasująca linia treści."""
    enum = spec.get("enum") if isinstance(spec, dict) else None
    if enum:
        for candidate in enum:
            if _word_pattern(str(candidate)).search(content):
                return str(candidate)
        return None
    pattern = re.compile(
        r"^\s*" + re.escape(name) + r"\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE
    )
    match = pattern.search(content)
    return match.group(1) if match else None


def _auto_metadata_answer(text: str) -> str:
    """Odpowiedź auto-metadanych: sam JSON obiektu (`{}` gdy nic); marker → `not a json`."""
    schema_text, content = _split_schema_content(text)
    if _INVALID_MARKER in content:
        return _NOT_A_JSON
    properties = _load_mapping(schema_text).get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    result = {
        name: value
        for name, spec in properties.items()
        if (value := _property_value(name, spec, content)) is not None
    }
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _filter_conditions(keys_text: str, query: str) -> list[dict[str, str]]:
    """Warunki: każda para (klucz, wartość) obecna w pytaniu jako osobne słowo, w kolejności."""
    conditions: list[dict[str, str]] = []
    for key, values in _load_mapping(keys_text).items():
        if not isinstance(values, list):
            continue
        for value in values:
            text_value = str(value)
            if _word_pattern(text_value).search(query):
                conditions.append({"key": key, "value": text_value, "op": "="})
    return conditions


def _filter_answer(text: str) -> str:
    """Odpowiedź filtra metadanych: `{"logic": "and", "conditions": [...]}` (pusta bez trafień).

    Szablon może zawierać linie `- Pytanie użytkownika:` także w przykładach przed sekcją
    `**Bieżące zadanie**:`; właściwe pytanie to ostatnie wystąpienie.
    """
    queries = _QUERY_PATTERN.findall(text)
    query = queries[-1] if queries else ""
    conditions = _filter_conditions(_line_after(text, _KEYS_PREFIX) or "", query)
    return json.dumps({"logic": "and", "conditions": conditions}, ensure_ascii=False)


def metadata_content(messages: list[ChatMessage]) -> str | None:
    """Treść odpowiedzi na prompt metadanych; `None`, gdy to nie prompt metadanych."""
    text = _matching_system_text(messages)
    if text is None:
        return None
    if text.lstrip().startswith(_AUTO_HEADER):
        return _auto_metadata_answer(text)
    return _filter_answer(text)
