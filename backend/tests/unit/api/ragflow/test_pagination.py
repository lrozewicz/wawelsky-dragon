"""Testy paginacji (C5, przykłady briefu dosłownie)."""

import dataclasses

import pytest

from app.api.ragflow.pagination import Page, parse_page
from app.core.errors import ValidationFailed

_DEFAULT_SIZE = 30
_EXPLICIT_SIZE = 50


def test_defaults() -> None:
    """Puste query — Page(1, 30, 'create_time', True)."""
    assert parse_page({}, max_size=1000) == Page(1, 30, "create_time", True)


def test_non_numeric_page_and_negative_size_fall_back() -> None:
    """'abc' nieliczbowy → page 1; '-3' < 1 → page_size domyślny."""
    result = parse_page({"page": "abc", "page_size": "-3"}, max_size=1000)
    assert result == Page(1, 30, "create_time", True)


def test_size_clamped_to_max() -> None:
    """page_size ponad limit → przycięty do max_size."""
    result = parse_page({"page": "2", "page_size": "5000"}, max_size=1000)
    assert result == Page(2, 1000, "create_time", True)


def test_zero_size_requires_flag() -> None:
    """page_size '0' → domyślny; z allow_zero_size=True → 0."""
    assert parse_page({"page_size": "0"}, max_size=1000).page_size == _DEFAULT_SIZE
    assert parse_page({"page_size": "0"}, max_size=1000, allow_zero_size=True).page_size == 0


def test_float_size_is_non_numeric() -> None:
    """'1.5' nie parsuje się int() → page_size domyślny."""
    assert parse_page({"page_size": "1.5"}, max_size=1000).page_size == _DEFAULT_SIZE


def test_size_in_range_is_kept() -> None:
    """Jawny page_size w zakresie (≥1 i ≤ max) pozostaje bez zmian."""
    assert parse_page({"page_size": "50"}, max_size=1000).page_size == _EXPLICIT_SIZE


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_page_below_one_or_non_numeric_falls_back_to_one(value: str) -> None:
    """page nieliczbowy albo < 1 → 1."""
    assert parse_page({"page": value}, max_size=1000).page == 1


def test_orderby_outside_allowed_raises_validation_failed() -> None:
    """orderby spoza zbioru → ValidationFailed z komunikatem upstream."""
    with pytest.raises(ValidationFailed) as exc_info:
        parse_page({"orderby": "name"}, max_size=1000)
    assert exc_info.value.message == (
        "Field: <orderby> - Message: <Input should be 'create_time' or 'update_time'>"
        " - Value: <name>"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("False", False), ("0", True), ("true", True)],
)
def test_desc_uses_to_bool(raw: str, expected: bool) -> None:
    """desc przez to_bool: tylko 'false' daje False."""
    assert parse_page({"desc": raw}, max_size=1000).desc is expected


def test_custom_orderby_allowed_and_default() -> None:
    """Własny zbiór orderby i domyślna wartość orderby."""
    result = parse_page(
        {}, max_size=1000, orderby_allowed=frozenset({"name"}), default_orderby="name"
    )
    assert result.orderby == "name"
    explicit = parse_page({"orderby": "name"}, max_size=1000, orderby_allowed=frozenset({"name"}))
    assert explicit.orderby == "name"


def test_page_is_frozen() -> None:
    """Page zamrożony (C5)."""
    page = parse_page({}, max_size=1000)
    with pytest.raises(dataclasses.FrozenInstanceError):
        page.page = 2  # type: ignore[misc]
