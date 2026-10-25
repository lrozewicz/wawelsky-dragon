"""Filtr metadanych dokumentów (CONTRACT WP E1-7 M5; port common/metadata_utils.py:23-150).

Semantyka porównań 1:1 z upstream ``meta_filter``/``filter_out`` (K11 §10f p. 1): wartości
porównywane po ``ast.literal_eval`` OBU stron (z fallbackiem do stringa), aliasy operatorów
z ``convert_conditions`` (``is``→``=``, ``not is``→``≠``, ``>=``→``≥``, ``<=``→``≤``, ``!=``→``≠``),
nieznany operator = brak trafienia (kod 0), a ``empty``/``not empty`` bez klucza ``value`` to
błąd ``KeyError('value')`` (upstream czyta ``cond["value"]`` bez zabezpieczenia).
"""

import ast
import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.core.errors import ValidationFailed, WDError

OPERATORS: frozenset[str] = frozenset(
    {
        # Operatory wewnętrzne (upstream metadata_utils.py:96-123).
        "=",
        "≠",
        ">",
        "<",
        "≥",
        "≤",
        "contains",
        "not contains",
        "in",
        "not in",
        "start with",
        "end with",
        "empty",
        "not empty",
        # Aliasy ciała API (convert_conditions, :26).
        "is",
        "not is",
        ">=",
        "<=",
        "!=",
    }
)

# Mapowanie operatorów API na operatory wewnętrzne (port convert_conditions, :26).
_OP_MAPPING: dict[str, str] = {"is": "=", "not is": "≠", ">=": "≥", "<=": "≤", "!=": "≠"}

# Komunikat błędu dla ``empty``/``not empty`` bez klucza ``value`` (upstream KeyError, kod 100).
MSG_KEY_VALUE = "KeyError('value')"
# Długość daty ``YYYY-MM-DD`` (upstream ``is_*_date``, :90-94).
_DATE_LEN = 10
_COMPARISON_OPS: frozenset[str] = frozenset({"=", "≠", ">", "<", "≥", "≤"})
_CMP_FUNCS: dict[str, Callable[[Any, Any], bool]] = {
    "=": operator.eq,
    "≠": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    "≥": operator.ge,
    "≤": operator.le,
}


@dataclass(frozen=True)
class MetadataFilter:
    """Pojedynczy filtr: pole metadanych dokumentu, operator i wartość porównania."""

    name: str
    op: str  # po mapowaniu: "is"→"=", "not is"→"≠"
    value: Any


@dataclass(frozen=True)
class MetadataCondition:
    """Warunek na metadane: logika łączenia filtrów ("and"/"or") i krotka filtrów."""

    logic: Literal["and", "or"]
    conditions: tuple[MetadataFilter, ...]


def parse_metadata_condition(raw: Mapping[str, Any]) -> MetadataCondition:
    """Parsuje słownik ``metadata_condition`` z API do :class:`MetadataCondition`.

    Oczekuje ``{"logic": "and"|"or" (domyślnie "and"), "conditions": [...]}``, gdzie każdy
    element ma niepusty ``name`` (str) i ``comparison_operator``; nieznana logika albo
    nieprawidłowa struktura → ``ValidationFailed``. Nieznany operator nie jest błędem
    (upstream opada do braku trafienia — złoto ``metadata_e6--31``), a ``empty``/``not empty``
    bez klucza ``value`` → ``KeyError('value')`` (upstream ``convert_conditions`` czyta
    ``cond["value"]`` bez zabezpieczenia — złoto ``metadata_e6--30``).
    """
    logic = raw.get("logic", "and")
    if logic not in ("and", "or"):
        raise ValidationFailed(f"Unsupported metadata logic: {logic}")
    conditions = raw.get("conditions")
    if not isinstance(conditions, list):
        raise ValidationFailed("Invalid metadata_condition.")
    filters: list[MetadataFilter] = []
    for item in conditions:
        if not isinstance(item, Mapping):
            raise ValidationFailed("Invalid metadata_condition.")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValidationFailed("Invalid metadata_condition.")
        op = item.get("comparison_operator")
        if not isinstance(op, str):
            raise ValidationFailed("Invalid metadata_condition.")
        internal = _OP_MAPPING.get(op, op)
        if internal in ("empty", "not empty") and "value" not in item:
            raise WDError(MSG_KEY_VALUE)
        filters.append(MetadataFilter(name=name, op=internal, value=item.get("value")))
    return MetadataCondition(logic=logic, conditions=tuple(filters))


def meta_data_filter_to_condition(f: Mapping[str, Any]) -> MetadataCondition | None:
    """Konwertuje ``meta_data_filter`` na :class:`MetadataCondition` (K11 §10f p. 5).

    Zawężenie realizuje wyłącznie ``method: "manual"`` z niepustą listą ``manual``
    (``[{key, op, value}]`` + ``logic``, domyślnie ``and``); ``op`` mapowany jak aliasy
    ciała API (``>=``→``≥``, ``!=``→``≠``, ``is``→``=`` itd.). ``auto``/``semi_auto``
    oraz brak/pusta lista ``manual`` → ``None`` (brak zawężenia — złoto ``metadata_e6--43/44``;
    T3b dopisuje model). Pusty wynik dopasowania NIE jest tu „brakiem zawężenia" — rozstrzyga
    go ``match_documents`` (zbiór pusty → 0 chunków, złoto ``metadata_e6--42``).
    """
    if f.get("method") != "manual":
        return None
    manual = f.get("manual")
    if not isinstance(manual, list) or not manual:
        return None
    logic = f.get("logic", "and")
    if logic not in ("and", "or"):
        raise ValidationFailed(f"Unsupported metadata logic: {logic}")
    filters: list[MetadataFilter] = []
    for item in manual:
        if not isinstance(item, Mapping):
            raise ValidationFailed("Invalid meta_data_filter.")
        key = item.get("key")
        op = item.get("op")
        if not isinstance(key, str) or not key or not isinstance(op, str):
            raise ValidationFailed("Invalid meta_data_filter.")
        filters.append(
            MetadataFilter(name=key, op=_OP_MAPPING.get(op, op), value=item.get("value"))
        )
    return MetadataCondition(logic=logic, conditions=tuple(filters))


def _is_date(text: str) -> bool:
    """Czy tekst jest w formacie YYYY-MM-DD (upstream ``is_*_date``, :90-94)."""
    return (
        len(text) == _DATE_LEN
        and text[4] == "-"
        and text[7] == "-"
        and text[:4].isdigit()
        and text[5:7].isdigit()
        and text[8:10].isdigit()
    )


def _normalize_string_values(value: Any) -> Any:
    """Obniża wielkość liter: str → lower, lista → elementy str → lower (upstream :33-39)."""
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, list):
        return [item.lower() if isinstance(item, str) else item for item in value]
    return value


def _literal_eval(value: Any) -> tuple[bool, Any]:
    """``ast.literal_eval`` z fallbackiem: ``(sparsowano?, wartość)`` (upstream ``filter_out``).

    Prawa strona porównania (``value`` stałe w filtrze) liczona raz na filtr — DEC-300 p. 1.
    """
    try:
        return True, ast.literal_eval(value)
    except Exception:  # noqa: BLE001 — parsowanie opcjonalne (upstream), jak filter_out
        return False, value


def _compare(input_value: str, op: str, value: Any, right: tuple[bool, Any] | None = None) -> bool:
    """Porównanie ``=``, ``≠``, ``>``, ``<``, ``≥``, ``≤`` (upstream ``filter_out``, :46-93).

    Wartości dat (YYYY-MM-DD) porównywane tekstowo; inaczej ``ast.literal_eval`` OBU stron
    (fallback do stringa) i porównanie po obniżeniu liter. Niezgodne typy (np. ``"2020"`` vs
    int 2020) → brak trafienia (złoto ``metadata_e6--33``). ``right`` to sparsowana raz na filtr
    prawa strona (DEC-300 p. 1); gdy prawa strona się nie parsuje, lewej **nie** parsujemy
    (jak upstream: przy błędzie obie zostają surowymi stringami).
    """
    input_str = str(input_value).strip()
    value_str = str(value).strip()
    if _is_date(value_str):
        if not _is_date(input_str):
            return False
        left, right_value = input_str, value_str
    else:
        if right is None:
            right = _literal_eval(value)
        right_ok, parsed_right = right
        left_ok, parsed_left = False, input_value
        if right_ok:
            left_ok, parsed_left = _literal_eval(input_value)
        # Jedna z dwóch stron bez literal_eval → obie surowe (upstream: literal_eval OBU razem).
        if right_ok and left_ok:
            left, right_value = parsed_left, parsed_right
        else:
            left, right_value = input_value, value
        if isinstance(left, str):
            left = left.lower()
        if isinstance(right_value, str):
            right_value = right_value.lower()
    try:
        return bool(_CMP_FUNCS[op](left, right_value))
    except Exception:  # noqa: BLE001 — porównanie niezgodnych typów = brak trafienia (upstream)
        return False


def _non_comparison(input_value: str, op: str, value: Any) -> bool:
    """Operatory tekstowe/zbiorowe (upstream ``filter_out``, :96-123).

    Wartości normalizowane (lower). Nieznany operator → brak trafienia (kod 0, złoto ``--31``).
    """
    input_value = _normalize_string_values(input_value)
    value = _normalize_string_values(value)
    try:
        if op == "contains":
            matched = str(input_value).find(value) >= 0
        elif op == "not contains":
            matched = str(input_value).find(value) == -1
        elif op == "in":
            matched = input_value in value
        elif op == "not in":
            matched = input_value not in value
        elif op == "start with":
            matched = str(input_value).lower().startswith(str(value).lower())
        elif op == "end with":
            matched = str(input_value).lower().endswith(str(value).lower())
        elif op == "empty":
            matched = not input_value
        elif op == "not empty":
            matched = bool(input_value)
        else:
            return False  # nieznany operator → brak trafienia (upstream)
    except Exception:  # noqa: BLE001 — niezgodne typy = brak trafienia (upstream)
        return False
    return matched


def _matches(input_value: str, op: str, value: Any, right: tuple[bool, Any] | None = None) -> bool:
    """Sprawdza jedną wartość metadanych przeciw jednemu filtrowi (upstream ``filter_out``).

    ``right`` (opcjonalne) to sparsowana raz na filtr prawa strona porównania (DEC-300 p. 1).
    """
    if op in _COMPARISON_OPS:
        return _compare(input_value, op, value, right)
    return _non_comparison(input_value, op, value)


def match_documents(
    metas: Mapping[str, Mapping[str, Any]], cond: MetadataCondition
) -> frozenset[str]:
    """Wylicza zbiór ``document_id`` spełniających warunek (port meta_filter, :30-150).

    ``metas``: document_id → meta_fields. Wartości metadanych są indeksowane jako **stringi**,
    a lista wartości rozwijana na osobne wpisy (upstream ``get_flatted_meta_by_kbs``, :844-851):
    dokument pasuje, gdy którykolwiek jego wpis pasuje. Logika "and" = przecięcie zbiorów
    filtrów, "or" = suma; brak filtrów → wszystkie dokumenty. Dokument bez klucza filtra nie
    pasuje (także dla operatora "empty", jak upstream).

    ``_matches`` jest czyste względem ``(str(entry), op, value)``, a ``value`` stałe w filtrze,
    więc wynik pamiętamy w słowniku ``str(entry) → bool`` per filtr (memo, DEC-300 p. 1) — przy
    powtarzających się wartościach metadanych liczymy ``literal_eval`` raz, nie per wiersz.
    """
    result: set[str] | None = None
    for f in cond.conditions:
        right = _literal_eval(f.value)  # prawa strona porównania raz na filtr (DEC-300 p. 1)
        cache: dict[str, bool] = {}
        matching: set[str] = set()
        for doc_id, meta in metas.items():
            if f.name not in meta:
                continue
            raw = meta[f.name]
            entries = raw if isinstance(raw, list) else [raw]
            for entry in entries:
                if entry is None:
                    continue
                key = str(entry)
                matched = cache.get(key)
                if matched is None:
                    matched = _matches(key, f.op, f.value, right)
                    cache[key] = matched
                if matched:
                    matching.add(doc_id)
                    break
        if result is None:
            result = matching
        elif cond.logic == "and":
            result &= matching
        else:
            result |= matching
    if result is None:
        return frozenset(metas)
    return frozenset(result)


# Znaki, których obecność w nazwie pola wyklucza pushdown SQL (DEC-300 p. 2): ``name``
# wchodzi do ścieżki JSON ``'$."<name>"'`` jako literał, więc cudzysłów/ukośnik/kontrolne
# są niebezpieczne.
_PUSHDOWN_FORBIDDEN_CHARS = frozenset({'"', "\\"})
_FIRST_PRINTABLE_CHAR = 32  # znak sterujący = ord < 32 (DEC-300 p. 2)


@dataclass(frozen=True)
class MetadataPushdown:
    """Zawężenie SQL kandydatów (nadzbiór dopasowań) dla filtra metadanych (DEC-300 p. 2)."""

    logic: Literal["and", "or"]
    filters: tuple[MetadataFilter, ...]


def _is_pushdown_filter(f: MetadataFilter) -> bool:
    """Czy filtr nadaje się na pushdown SQL jako nadzbiór (DEC-300 p. 2, ``metadata.py``).

    Wymaga: operator wewnętrzny ``=`` (po mapowaniu ``is``→``=``), ``value`` będące ``str``,
    ``value`` nie datą (``YYYY-MM-DD``) i nierozkładalne przez ``ast.literal_eval`` (czysty
    tekst → Python porównuje ``str(entry).lower() == value.lower()``; literał liczbowy/lista
    idą do Pythona bez oceny w SQL), a nazwa pola bez ``"``, ``\\`` i znaków sterujących.
    """
    if f.op != "=" or not isinstance(f.value, str):
        return False
    if _is_date(f.value.strip()):
        return False
    if _literal_eval(f.value)[0]:  # czysty tekst: literal_eval nie parsuje (DEC-300 p. 2)
        return False
    return not any(
        char in _PUSHDOWN_FORBIDDEN_CHARS or ord(char) < _FIRST_PRINTABLE_CHAR for char in f.name
    )


def pushdown_condition(cond: MetadataCondition) -> MetadataPushdown | None:
    """Wyznacza pushdown SQL jako NADZBIÓR kandydatów (DEC-300 p. 2); ``None`` = brak pushdownu.

    Logika ``and``: pushujemy podzbiór pushowalnych warunków (≥ 1). Logika ``or``: pushdown
    tylko gdy **wszystkie** warunki pushowalne (wtedy OR w SQL). Brak pushowalnych → ``None``
    (dzisiejsza ścieżka pełnego odczytu). Ostateczne dopasowanie zawsze liczy
    ``match_documents`` na kandydatach — semantyka zależy wyłącznie od tego, że SQL nie gubi
    trafień (nadzbiór).
    """
    pushable = tuple(f for f in cond.conditions if _is_pushdown_filter(f))
    if not pushable:
        return None
    if cond.logic == "and":
        return MetadataPushdown(logic="and", filters=pushable)
    if len(pushable) == len(cond.conditions):
        return MetadataPushdown(logic="or", filters=pushable)
    return None
