"""Testy filtra metadanych dokumentów (CONTRACT WP E1-7 M5)."""

import re
from typing import Any

import pytest

from app.core.errors import ValidationFailed, WDError
from app.domain.retrieval.metadata import (
    OPERATORS,
    MetadataCondition,
    MetadataFilter,
    match_documents,
    meta_data_filter_to_condition,
    parse_metadata_condition,
)

METAS: dict[str, dict[str, Any]] = {
    "d1": {"author": "Jan Kowalski", "year": "2024", "tags": ["HR", "urlop"], "draft": ""},
    "d2": {"author": "Anna", "year": 2021, "tags": ["IT"]},
    "d3": {},
}


def _match(raw: dict[str, Any], metas: dict[str, dict[str, Any]] | None = None) -> frozenset[str]:
    """Parsuje warunek i zwraca zbiór dokumentów pasujących (środek pomocniczy testów)."""
    return match_documents(metas if metas is not None else METAS, parse_metadata_condition(raw))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # is → = (bez wielkości liter)
        (
            {
                "conditions": [
                    {"name": "author", "comparison_operator": "is", "value": "jan kowalski"}
                ]
            },
            {"d1"},
        ),
        (
            {"conditions": [{"name": "author", "comparison_operator": "is", "value": "ANNA"}]},
            {"d2"},
        ),
        # not is → ≠ (d3 nie ma klucza → nie pasuje)
        (
            {"conditions": [{"name": "author", "comparison_operator": "not is", "value": "Anna"}]},
            {"d1"},
        ),
        # contains (lista: dowolny element)
        (
            {
                "conditions": [
                    {"name": "author", "comparison_operator": "contains", "value": "kowal"}
                ]
            },
            {"d1"},
        ),
        (
            {"conditions": [{"name": "tags", "comparison_operator": "contains", "value": "hr"}]},
            {"d1"},
        ),
        # not contains (lista: żaden element)
        (
            {
                "conditions": [
                    {"name": "author", "comparison_operator": "not contains", "value": "kowal"}
                ]
            },
            {"d2"},
        ),
        (
            {
                "conditions": [
                    {"name": "tags", "comparison_operator": "not contains", "value": "hr"}
                ]
            },
            {"d1", "d2"},
        ),
        # in / not in (bez wielkości liter po obu stronach)
        (
            {
                "conditions": [
                    {"name": "author", "comparison_operator": "in", "value": ["anna", "piotr"]}
                ]
            },
            {"d2"},
        ),
        (
            {
                "conditions": [
                    {"name": "author", "comparison_operator": "in", "value": ["ANNA", "PIOTR"]}
                ]
            },
            {"d2"},
        ),
        (
            {
                "conditions": [
                    {"name": "author", "comparison_operator": "not in", "value": ["anna"]}
                ]
            },
            {"d1"},
        ),
        # empty / not empty (brak klucza → nie pasuje, także dla "empty"; value wymagane)
        (
            {"conditions": [{"name": "draft", "comparison_operator": "empty", "value": ""}]},
            {"d1"},
        ),
        (
            {"conditions": [{"name": "draft", "comparison_operator": "not empty", "value": ""}]},
            set(),
        ),
        (
            {"conditions": [{"name": "author", "comparison_operator": "not empty", "value": ""}]},
            {"d1", "d2"},
        ),
        (
            {"conditions": [{"name": "author", "comparison_operator": "empty", "value": ""}]},
            set(),
        ),
        # porównania liczbowe: literal_eval obu stron — zgodne typy porównują się, int vs str nie
        ({"conditions": [{"name": "year", "comparison_operator": "=", "value": "2024"}]}, {"d1"}),
        # literal_eval po OBU stronach: int (2022) nie sparsuje wartości dokumentu jako int,
        # więc porównanie ``str`` vs ``int`` nie trafia (jak złoto metadata_e6--33)
        ({"conditions": [{"name": "year", "comparison_operator": ">", "value": 2022}]}, set()),
        ({"conditions": [{"name": "year", "comparison_operator": "<", "value": 2022}]}, set()),
        (
            {"conditions": [{"name": "year", "comparison_operator": "≥", "value": "2021"}]},
            {"d1", "d2"},
        ),
        ({"conditions": [{"name": "year", "comparison_operator": "≤", "value": 2021}]}, set()),
        (
            {"conditions": [{"name": "year", "comparison_operator": "≠", "value": 2024}]},
            {"d1", "d2"},
        ),
    ],
)
def test_match_single_condition(raw: dict[str, Any], expected: set[str]) -> None:
    assert _match(raw) == expected


def test_match_date_comparison_is_lexicographic() -> None:
    metas = {"a": {"date": "2024-05-01"}, "b": {"date": "2022-01-01"}}
    raw = {"conditions": [{"name": "date", "comparison_operator": ">", "value": "2023-01-01"}]}
    assert _match(raw, metas) == {"a"}


def test_match_comparison_any_list_element_matches() -> None:
    """Lista wartości rozwijana na wpisy (upstream): pasuje dowolny element (tu int vs str nie)."""
    metas = {"a": {"t": ["2024", "ign"]}}
    raw = {"conditions": [{"name": "t", "comparison_operator": "=", "value": 2024}]}
    assert _match(raw, metas) == set()
    raw_str = {"conditions": [{"name": "t", "comparison_operator": "=", "value": "2024"}]}
    assert _match(raw_str, metas) == {"a"}


def test_match_comparison_empty_list_does_not_match() -> None:
    metas = {"a": {"t": []}}
    raw = {"conditions": [{"name": "t", "comparison_operator": "=", "value": "x"}]}
    assert _match(raw, metas) == set()


def test_match_comparison_int_value_does_not_match_string_meta() -> None:
    metas = {"a": {"v": "2024a"}, "b": {"v": "2024"}}
    raw = {"conditions": [{"name": "v", "comparison_operator": "=", "value": 2024}]}
    assert _match(raw, metas) == set()


def test_match_in_with_list_document_value_any_element() -> None:
    """``in`` na liście dokumentu: pasuje dowolny element (expansja wartości, upstream)."""
    metas: dict[str, dict[str, Any]] = {
        "a": {"t": ["a", "b"]},
        "b": {"t": ["a", "x"]},
        "c": {"t": ["x"]},
    }
    raw = {"conditions": [{"name": "t", "comparison_operator": "in", "value": ["a", "b"]}]}
    assert _match(raw, metas) == {"a", "b"}


def test_match_not_in_with_list_document_value_any_element() -> None:
    metas: dict[str, dict[str, Any]] = {
        "a": {"t": ["a", "b"]},
        "b": {"t": ["a", "x"]},
        "c": {"t": ["z"]},
    }
    raw = {"conditions": [{"name": "t", "comparison_operator": "not in", "value": ["x", "y"]}]}
    assert _match(raw, metas) == {"a", "b", "c"}


def test_match_in_with_non_list_value_uses_membership() -> None:
    """Wartość bez listy → ``input in value`` (upstream; podciąg dla stringa)."""
    metas = {"a": {"t": "anna"}}
    raw = {"conditions": [{"name": "t", "comparison_operator": "in", "value": "anna"}]}
    assert _match(raw, metas) == {"a"}


def test_match_not_in_with_non_list_value_negates() -> None:
    metas = {"a": {"t": "anna"}}
    raw = {"conditions": [{"name": "t", "comparison_operator": "not in", "value": "piotr"}]}
    assert _match(raw, metas) == {"a"}


def test_match_in_lowercases_value_elements() -> None:
    metas = {"a": {"t": "x"}, "b": {"n": 2024}}
    raw = {
        "logic": "or",
        "conditions": [
            {"name": "t", "comparison_operator": "in", "value": [["HR", "urlop"], "X"]},
            {"name": "n", "comparison_operator": "in", "value": [2023, 2024]},
        ],
    }
    assert _match(raw, metas) == {"a"}


def test_match_logic_or_unions() -> None:
    raw = {
        "logic": "or",
        "conditions": [
            {"name": "author", "comparison_operator": "is", "value": "anna"},
            {"name": "year", "comparison_operator": "=", "value": 2024},
        ],
    }
    assert _match(raw) == {"d2"}


def test_match_logic_or_with_empty_first_filter() -> None:
    raw = {
        "logic": "or",
        "conditions": [
            {"name": "author", "comparison_operator": "is", "value": "xyz"},
            {"name": "year", "comparison_operator": "=", "value": 2024},
        ],
    }
    assert _match(raw) == set()


def test_match_logic_and_intersects() -> None:
    raw = {
        "logic": "and",
        "conditions": [
            {"name": "author", "comparison_operator": "is", "value": "anna"},
            {"name": "year", "comparison_operator": "=", "value": 2024},
        ],
    }
    assert _match(raw) == set()


def test_match_empty_conditions_matches_all_documents() -> None:
    result = _match({"conditions": []})
    assert result == {"d1", "d2", "d3"}
    assert isinstance(result, frozenset)


def test_parse_maps_operators_and_defaults() -> None:
    cond = parse_metadata_condition(
        {"conditions": [{"name": "author", "comparison_operator": "is", "value": "x"}]}
    )
    assert cond == MetadataCondition(
        logic="and", conditions=(MetadataFilter(name="author", op="=", value="x"),)
    )
    cond2 = parse_metadata_condition(
        {"logic": "or", "conditions": [{"name": "year", "comparison_operator": "not is"}]}
    )
    assert cond2 == MetadataCondition(
        logic="or", conditions=(MetadataFilter(name="year", op="≠", value=None),)
    )


def test_unknown_operator_matches_nothing() -> None:
    """Nieznany operator nie jest błędem i nie trafia w nic (kod 0; złoto metadata_e6--31)."""
    cond = parse_metadata_condition(
        {"conditions": [{"name": "author", "comparison_operator": "bogus", "value": "A"}]}
    )
    assert (
        _match({"conditions": [{"name": "author", "comparison_operator": "bogus", "value": "A"}]})
        == set()
    )
    assert cond.conditions[0].op == "bogus"


def test_empty_without_value_raises_key_error() -> None:
    """``empty``/``not empty`` bez klucza ``value`` → kod 100 KeyError('value') (złoto --30)."""
    with pytest.raises(WDError, match=re.escape("KeyError('value')")):
        parse_metadata_condition({"conditions": [{"name": "note", "comparison_operator": "empty"}]})


def test_parse_rejects_unknown_logic() -> None:
    with pytest.raises(ValidationFailed, match="Unsupported metadata logic: xor"):
        parse_metadata_condition({"logic": "xor", "conditions": []})


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"conditions": "x"},
        {"conditions": None},
        {"conditions": ["x"]},
        {"conditions": [{"value": "a"}]},
        {"conditions": [{"name": "", "comparison_operator": "is"}]},
        {"conditions": [{"name": 5, "comparison_operator": "is"}]},
    ],
)
def test_parse_rejects_invalid_condition(raw: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed, match=re.escape("Invalid metadata_condition.")):
        parse_metadata_condition(raw)


def test_operators_whitelist() -> None:
    expected = {
        "is",
        "not is",
        "contains",
        "not contains",
        "in",
        "not in",
        "start with",
        "end with",
        "empty",
        "not empty",
        "=",
        "≠",
        ">",
        "<",
        "≥",
        "≤",
        ">=",
        "<=",
        "!=",
    }
    assert frozenset(expected) == OPERATORS


def test_meta_data_filter_manual_maps_to_condition() -> None:
    """manual (K11 §10f p. 5): {key, op, value} → MetadataFilter; op aliasowane jak ciało API."""
    condition = meta_data_filter_to_condition(
        {
            "method": "manual",
            "logic": "and",
            "manual": [
                {"key": "author", "op": "=", "value": "A"},
                {"key": "year", "op": "=", "value": "2020"},
            ],
        }
    )
    assert condition == MetadataCondition(
        logic="and",
        conditions=(
            MetadataFilter(name="author", op="=", value="A"),
            MetadataFilter(name="year", op="=", value="2020"),
        ),
    )
    aliased = meta_data_filter_to_condition(
        {"method": "manual", "manual": [{"key": "year", "op": ">=", "value": "2020"}]}
    )
    assert aliased == MetadataCondition(
        logic="and", conditions=(MetadataFilter(name="year", op="≥", value="2020"),)
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"method": "auto"},
        {"method": "semi_auto", "semi_auto": ["author"]},
        {"method": "manual"},
        {"method": "manual", "manual": []},
        {},
    ],
)
def test_meta_data_filter_without_narrowing_is_none(raw: dict[str, Any]) -> None:
    """auto/semi_auto i pusta lista manual → None (brak zawężenia, złoto --43/44)."""
    assert meta_data_filter_to_condition(raw) is None


def test_meta_data_filter_no_match_is_empty_not_none() -> None:
    """manual bez trafień → warunek, który wybiera nic (nie None = brak filtra)."""
    condition = meta_data_filter_to_condition(
        {"method": "manual", "manual": [{"key": "author", "op": "=", "value": "Z"}]}
    )
    assert condition is not None
    assert match_documents(METAS, condition) == frozenset()


@pytest.mark.parametrize(
    "raw",
    [
        {"method": "manual", "manual": ["x"]},
        {"method": "manual", "manual": [{"op": "=", "value": "A"}]},
        {"method": "manual", "manual": [{"key": "author", "value": "A"}]},
        {"method": "manual", "logic": "xor", "manual": [{"key": "a", "op": "=", "value": 1}]},
    ],
)
def test_meta_data_filter_invalid_raises(raw: dict[str, Any]) -> None:
    """Zła struktura manual albo logika → ValidationFailed."""
    with pytest.raises(ValidationFailed):
        meta_data_filter_to_condition(raw)
