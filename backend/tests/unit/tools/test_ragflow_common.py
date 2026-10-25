"""Testy wspólnych helperów etapów migracji (kontrakt §3, WP E4-6b1)."""

from datetime import UTC, datetime

import pytest

from app.tools.ragflow_migrate.stages.common import (
    datetime_ms,
    dumps_json,
    ms_naive,
    pick_times,
    same_json,
)

#: `2025-10-01 08:00:00` UTC — oś czasu fixture'u źródła (README §3).
T_2025_10_01_08_00 = datetime(2025, 10, 1, 8, 0, 0)
T_2025_10_01_08_00_MS = 1759305600000
NOW_MS = 1800000000000


def test_datetime_ms_none_stays_none() -> None:
    """NULL w źródle nie zamienia się na `now_ms` ani na 0."""
    assert datetime_ms(None) is None


def test_datetime_ms_naive_is_utc() -> None:
    """Naiwna `datetime` źródła (TIMESTAMP/DATETIME) jest traktowana jak UTC."""
    assert datetime_ms(T_2025_10_01_08_00) == T_2025_10_01_08_00_MS


def test_datetime_ms_aware_uses_its_zone() -> None:
    """`datetime` świadoma strefy jest przeliczana, nie przepisywana."""
    aware = datetime(2025, 10, 1, 10, 0, 0, tzinfo=UTC)
    assert datetime_ms(aware) == T_2025_10_01_08_00_MS + 2 * 3600 * 1000


def test_ms_naive_returns_naive_datetime() -> None:
    """Kolumny `*_date` (DATETIME(3)) dostają wartość bez strefy."""
    value = ms_naive(T_2025_10_01_08_00_MS)
    assert value == T_2025_10_01_08_00
    assert value.tzinfo is None


def test_ms_naive_keeps_milliseconds() -> None:
    """Milisekundy nie są gubione (kolumna DATETIME(3) je mieści)."""
    assert ms_naive(T_2025_10_01_08_00_MS + 123) == datetime(2025, 10, 1, 8, 0, 0, 123000)


def test_pick_times_uses_source_values() -> None:
    """Czasy podane w źródle wygrywają — także przy istniejącym wierszu celu."""
    existing = {"create_time": 1, "update_time": 2}
    assert pick_times(10, 20, existing, NOW_MS) == (10, 20)
    assert pick_times(10, 20, None, NOW_MS) == (10, 20)


def test_pick_times_without_existing_falls_back_to_now() -> None:
    """Bez wiersza celu źródłowe NULL-e zastępuje `now_ms`."""
    assert pick_times(None, None, None, NOW_MS) == (NOW_MS, NOW_MS)


def test_pick_times_keeps_existing_for_both_nulls() -> None:
    """Oba NULL-e przy istniejącym wierszu celu → czasy już zapisane w celu (idempotencja)."""
    existing = {"create_time": 111, "update_time": 222}
    assert pick_times(None, None, existing, NOW_MS) == (111, 222)


def test_pick_times_one_null_takes_only_that_time_from_existing() -> None:
    """Jeden NULL → z celu tylko ten czas; drugi nadal ze źródła."""
    existing = {"create_time": 111, "update_time": 222}
    assert pick_times(None, 20, existing, NOW_MS) == (111, 20)
    assert pick_times(10, None, existing, NOW_MS) == (10, 222)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ('{"a": 1, "b": [2]}', {"b": [2], "a": 1}),
        ({"a": 1}, '{"a": 1}'),
        (["a", "b"], '["a", "b"]'),
        ('["a", "b"]', ["a", "b"]),
    ],
)
def test_same_json_text_and_value_are_equal(a: object, b: object) -> None:
    """Tekst JSON i gotowa wartość są równe niezależnie od kolejności kluczy."""
    assert same_json(a, b) is True


def test_same_json_none_equals_none() -> None:
    """Dwa NULL-e to ta sama (brak) wartość."""
    assert same_json(None, None) is True


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (None, "{}"),
        ("{}", None),
        (None, "[]"),
        ('{"a": 1}', '{"a": 2}'),
        ("[1]", "[1, 2]"),
    ],
)
def test_same_json_detects_differences(a: object, b: object) -> None:
    """NULL vs niepuste oraz różne treści → False."""
    assert same_json(a, b) is False


def test_same_json_bytes_are_parsed() -> None:
    """`bytes` (np. z kolumny BLOB) parsuje się jak tekst."""
    assert same_json(b'{"a": 1}', {"a": 1}) is True


def test_dumps_json_keeps_non_ascii() -> None:
    """`ensure_ascii=False` — polskie znaki zostają znakami (kontrakt §3)."""
    assert dumps_json({"nazwa": "Zażółć gęślą jaźń"}) == '{"nazwa": "Zażółć gęślą jaźń"}'


def test_dumps_json_round_trips_with_same_json() -> None:
    """Zapis i porównanie są spójne dla wartości zagnieżdżonej."""
    value = {"chunk_token_num": 128, "delimiter": "\n!?;"}
    assert dumps_json(value) == '{"chunk_token_num": 128, "delimiter": "\\n!?;"}'
    assert same_json(dumps_json(value), value) is True
