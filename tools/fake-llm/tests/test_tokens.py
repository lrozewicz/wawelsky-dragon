"""Testy tokenizacji — przykłady dosłownie z briefu (C3)."""

from fake_llm.tokens import tokenize


def test_polish_diacritics_removed() -> None:
    assert tokenize("Zażółć GĘŚLĄ jaźń") == ["zazolc", "gesla", "jazn"]


def test_punctuation_splits_and_digits_kept() -> None:
    assert tokenize("Umowa-najmu, 2024r.") == ["umowa", "najmu", "2024r"]


def test_empty_text() -> None:
    assert tokenize("") == []


def test_only_punctuation() -> None:
    assert tokenize("!!!") == []
