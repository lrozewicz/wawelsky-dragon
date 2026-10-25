"""Testy przycinania tekstów audytu (brief T5, kontrakt C4) — czysta funkcja ``trim``."""

import pytest

from app.integrations.audit import trim

MESSAGE_LIMIT = 2000
SMALL_LIMIT = 5


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("", SMALL_LIMIT, ""),  # puste
        ("abcd", SMALL_LIMIT, "abcd"),  # limit - 1
        ("abcde", SMALL_LIMIT, "abcde"),  # dokładnie limit
        ("abcdef", SMALL_LIMIT, "abcd…"),  # limit + 1
    ],
)
def test_trim_boundaries(text: str, limit: int, expected: str) -> None:
    result = trim(text, limit)
    assert result == expected
    assert len(result) <= limit


def test_trim_shorter_than_limit_is_unchanged() -> None:
    text = "a" * (MESSAGE_LIMIT - 1)
    assert trim(text, MESSAGE_LIMIT) == text


def test_trim_at_limit_is_unchanged() -> None:
    text = "a" * MESSAGE_LIMIT
    assert trim(text, MESSAGE_LIMIT) == text


def test_trim_long_text_has_exact_limit() -> None:
    result = trim("a" * (MESSAGE_LIMIT + 1), MESSAGE_LIMIT)
    assert result == "a" * (MESSAGE_LIMIT - 1) + "…"
    assert len(result) == MESSAGE_LIMIT


def test_trim_counts_characters_not_bytes() -> None:
    result = trim("ż" * (SMALL_LIMIT * 2), SMALL_LIMIT)
    assert result == "ż" * (SMALL_LIMIT - 1) + "…"
    assert len(result) == SMALL_LIMIT
    assert len(result.encode("utf-8")) > SMALL_LIMIT
