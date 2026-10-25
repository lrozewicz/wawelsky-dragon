"""Testy fold, term_weight i prepare_query (CONTRACT WP E1-7 M2, R0)."""

import re

import pytest

from app.domain.retrieval.query import fold, prepare_query, term_weight
from app.domain.retrieval.stopwords import STOPWORDS
from app.domain.retrieval.types import QueryTerms

# Atrapa stemera z briefu T1 (przykłady wejście → wyjście).
STEM = {"tatrach": "tatra", "tatry": "tatra", "najwyzszy": "najwysoki", "szczyty": "szczyt"}
MIN_STOPWORDS = 150


def stem(token: str) -> str:
    return STEM.get(fold(token), fold(token))


def test_fold_lowercases_and_strips_diacritics() -> None:
    assert fold("Zażółć Łódź") == "zazolc lodz"


def test_fold_keeps_characters_outside_a_z0_9() -> None:
    # Kontrakt: fold zwraca ciąg, który może zawierać znaki spoza [a-z0-9], np. "_".
    assert fold("YaËl_2") == "yael_2"


@pytest.mark.parametrize(
    ("term", "expected"),
    [("umowa", 1.0), ("umowach", 1.5), ("2024", 1.5), ("rok2024", 2.0)],
)
def test_term_weight(term: str, expected: float) -> None:
    assert term_weight(term) == pytest.approx(expected)


def test_prepare_query_full_pipeline() -> None:
    qt = prepare_query(
        "Czy są szczyty w Tatrach?", stopwords=frozenset({"czy", "sa", "w"}), stem=stem
    )
    assert qt.raw_terms == ("szczyty", "tatrach")
    assert [t for t, _ in qt.terms] == ["szczyt", "tatra"]
    assert [w for _, w in qt.terms] == pytest.approx([0.6, 0.4])
    assert [b for b, _ in qt.bigrams] == ["szczyt tatra"]
    assert [w for _, w in qt.bigrams] == pytest.approx([0.9])
    assert qt.ft_raw == "szczyty tatrach"
    assert qt.ft_stem == "szczyt tatra"


@pytest.mark.parametrize("question", ["  ", "czy w"])
def test_prepare_query_empty(question: str) -> None:
    qt = prepare_query(question, stopwords=frozenset({"czy", "w"}), stem=stem)
    assert qt == QueryTerms(raw_terms=(), terms=(), bigrams=(), ft_raw="", ft_stem="")


def test_prepare_query_dedups_raw_terms() -> None:
    qt = prepare_query("umowa umowa Umowa", stopwords=frozenset(), stem=lambda t: t)
    assert qt.raw_terms == ("umowa",)
    assert qt.terms == (("umowa", 0.4),)
    assert qt.bigrams == ()


def test_prepare_query_filters_stopwords_via_fold() -> None:
    # Stopword rozpoznawany po fold: wielkie litery i diakrytyki ("SĄ" → "sa").
    qt = prepare_query("SĄ szczyty?", stopwords=frozenset({"sa"}), stem=stem)
    assert qt.raw_terms == ("szczyty",)
    assert qt.ft_stem == "szczyt"


def test_prepare_query_drops_stem_that_is_stopword() -> None:
    qt = prepare_query("psa", stopwords=frozenset({"sa"}), stem=lambda _t: "sa")
    assert qt.terms == ()
    assert qt.ft_stem == ""


def test_prepare_query_dedups_stems() -> None:
    qt = prepare_query("psa kot", stopwords=frozenset(), stem=lambda _t: "x")
    assert qt.raw_terms == ("psa", "kot")
    assert len(qt.terms) == 1
    assert qt.bigrams == ()


def test_stopwords_is_large_and_folded() -> None:
    assert len(STOPWORDS) >= MIN_STOPWORDS
    assert all(w == fold(w) for w in STOPWORDS)
    assert all(re.fullmatch(r"[a-z0-9]+", w) for w in STOPWORDS)
