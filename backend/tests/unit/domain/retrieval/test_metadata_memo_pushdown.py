"""Memo dopasowań i klasyfikator pushdownu filtra metadanych (DEC-300 p. 1-2).

Memo w ``match_documents`` (``str(entry) → bool`` per filtr) musi dawać wynik identyczny ze
ścieżką bez memo — tu liczoną przez ``_matches`` wołane per wiersz (dawna implementacja).
Klasyfikator ``pushdown_condition`` decyduje, które warunki idą do SQL jako nadzbiór.
"""

from typing import Any

import pytest

from app.domain.retrieval.metadata import (
    MetadataCondition,
    MetadataFilter,
    MetadataPushdown,
    _matches,
    match_documents,
    parse_metadata_condition,
    pushdown_condition,
)

# Metadane z powtórzonymi wartościami (memo trafia w cache) i wszystkich typach przypadków
# z briefu: int, "2020", "0x7E4", "2_020", " 2020", data, lista, None, bool, "".
MEMO_METAS: dict[str, dict[str, Any]] = {
    "int": {"v": 2020},
    "str": {"v": "2020"},
    "str2": {"v": "2020"},  # druga wartość identyczna → memo
    "hex": {"v": "0x7E4"},
    "underscore": {"v": "2_020"},
    "space": {"v": " 2020"},
    "space2": {"v": " 2020"},  # memo
    "date": {"v": "2024-05-01"},
    "list": {"v": ["2020", "x"]},
    "none": {"v": None},
    "bool": {"v": True},
    "empty": {"v": ""},
    "missing": {"other": "x"},
}

# (op, value) — reprezentatywne dla całej tabeli porównań i operatorów tekstowych.
FILTERS: list[tuple[str, Any]] = [
    ("=", "2020"),
    ("=", 2020),
    ("=", "0x7E4"),
    ("=", "2_020"),
    ("=", " 2020"),
    ("=", "2024-05-01"),
    ("≠", "2020"),
    (">", "2023-01-01"),
    ("≥", 2020),
    ("<", "2021"),
    ("≤", " 2020"),
    ("=", None),
    ("=", True),
    ("contains", "2020"),
    ("not contains", "2020"),
    ("in", ["2020", "x"]),
    ("not in", ["2020"]),
    ("start with", "20"),
    ("end with", "0"),
    ("empty", ""),
    ("not empty", ""),
    ("bogus", "2020"),  # nieznany operator → brak trafienia
]


def _reference(metas: dict[str, dict[str, Any]], cond: MetadataCondition) -> frozenset[str]:
    """Ścieżka bez memo (dawna implementacja): ``_matches`` liczone per wiersz."""
    result: set[str] | None = None
    for f in cond.conditions:
        matching = {
            doc_id
            for doc_id, meta in metas.items()
            if f.name in meta
            and any(
                _matches(str(entry), f.op, f.value)
                for entry in (meta[f.name] if isinstance(meta[f.name], list) else [meta[f.name]])
                if entry is not None
            )
        }
        if result is None:
            result = matching
        elif cond.logic == "and":
            result &= matching
        else:
            result |= matching
    return frozenset(metas) if result is None else frozenset(result)


@pytest.mark.parametrize(("op", "value"), FILTERS)
@pytest.mark.parametrize("logic", ["and", "or"])
def test_memo_matches_reference_without_memo(op: str, value: Any, logic: str) -> None:
    """Memo (match_documents) daje wynik identyczny ze ścieżką bez memo (per wiersz)."""
    cond = MetadataCondition(
        logic=logic, conditions=(MetadataFilter(name="v", op=op, value=value),)
    )
    assert match_documents(MEMO_METAS, cond) == _reference(MEMO_METAS, cond)


def test_memo_two_filters_and_or_match_reference() -> None:
    """Dwa filtry (and/or) — memo per filtr, wynik jak bez memo."""
    for logic in ("and", "or"):
        cond = MetadataCondition(
            logic=logic,
            conditions=(
                MetadataFilter(name="v", op="=", value="2020"),
                MetadataFilter(name="v", op="≠", value="x"),
            ),
        )
        assert match_documents(MEMO_METAS, cond) == _reference(MEMO_METAS, cond)


def test_memo_empty_conditions_returns_all() -> None:
    """Brak filtrów → wszystkie dokumenty (bez memo i z memo)."""
    cond = MetadataCondition(logic="and", conditions=())
    assert match_documents(MEMO_METAS, cond) == frozenset(MEMO_METAS)


# --- klasyfikator pushdown (DEC-300 p. 2) ---


def _cond(logic: str, *filters: MetadataFilter) -> MetadataCondition:
    return MetadataCondition(logic=logic, conditions=filters)


def _f(name: str, value: Any, op: str = "=") -> MetadataFilter:
    return MetadataFilter(name=name, op=op, value=value)


def test_pushdown_pushable_plain_text() -> None:
    """Czysty tekst z op ``=`` jest pushowalny (autor/rok tekstowy)."""
    result = pushdown_condition(_cond("and", _f("author", "Adam")))
    assert result == MetadataPushdown(logic="and", filters=(_f("author", "Adam"),))


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("2020", "literał liczbowy"),
        ("0x7E4", "literał liczbowy szesnastkowy"),
        ("2_020", "literal_eval parsuje podkreślenia"),
        (" 2020", "literal_eval parsuje z wiodącą spacją"),
        ("2024-05-01", "data (porównanie tekstowe)"),
        (2020, "nie-str"),
        (None, "nie-str"),
        (["Adam"], "nie-str"),
    ],
)
def test_pushdown_not_pushable_values(value: Any, reason: str) -> None:
    """Wartości nie-czysto-tekstowe nie są pushowalne (STOP → brak pushdownu)."""
    assert pushdown_condition(_cond("and", _f("author", value))) is None


@pytest.mark.parametrize("name", ['a"b', "a\\b", "a\tb", "a\nb"])
def test_pushdown_not_pushable_name(name: str) -> None:
    """Nazwa z ``"``/``\\``/znakiem sterującym nie jest pushowalna (bezpieczeństwo ścieżki JSON)."""
    assert pushdown_condition(_cond("and", _f(name, "Adam"))) is None


def test_pushdown_not_pushable_other_operator() -> None:
    """Operator inny niż ``=`` (np. ``contains``) nie jest pushowalny."""
    assert pushdown_condition(_cond("and", _f("author", "Adam", op="contains"))) is None


def test_pushdown_and_keeps_pushable_subset() -> None:
    """Logika ``and``: pushujemy podzbiór pushowalnych warunków (≥ 1)."""
    result = pushdown_condition(
        _cond("and", _f("author", "Adam"), _f("year", "2020"), _f("topic", "rag"))
    )
    assert result == MetadataPushdown(
        logic="and", filters=(_f("author", "Adam"), _f("topic", "rag"))
    )


def test_pushdown_or_requires_all_pushable() -> None:
    """Logika ``or``: pushdown tylko gdy WSZYSTKIE warunki pushowalne."""
    all_ok = pushdown_condition(_cond("or", _f("a", "Adam"), _f("b", "Ewa")))
    assert all_ok == MetadataPushdown(logic="or", filters=(_f("a", "Adam"), _f("b", "Ewa")))
    mixed = pushdown_condition(_cond("or", _f("a", "Adam"), _f("b", "2020")))
    assert mixed is None


def test_pushdown_none_when_nothing_pushable() -> None:
    """Brak pushowalnych warunków → ``None`` (dzisiejsza ścieżka pełnego odczytu)."""
    assert pushdown_condition(_cond("and", _f("year", "2020"))) is None
    assert pushdown_condition(_cond("and")) is None


def test_pushdown_from_parsed_condition_api_is_operator() -> None:
    """``is`` (API) mapuje się na ``=`` → pushowalny; zły JSON-owy odpowiednik liczbowy nie."""
    cond = parse_metadata_condition(
        {"conditions": [{"name": "author", "comparison_operator": "is", "value": "Adam"}]}
    )
    assert pushdown_condition(cond) == MetadataPushdown(
        logic="and", filters=(_f("author", "Adam"),)
    )
