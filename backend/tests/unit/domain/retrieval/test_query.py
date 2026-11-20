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


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        # skrót wersalikami: 1.0 + premia 1.0 (inaczej przegrywa z „oznacza” 1.5)
        ("Co oznacza ZKM", {"co": 0.4, "oznacza": 0.6, "zkm": 0.8}),
        ("SKARBNET4", {"skarbnet4": 1.2}),  # litery + cyfra: 1.5 + 0.5 + 1.0
        ("poz. 1270", {"poz": 0.4, "1270": 1.0}),  # numer >= 3 cyfr
        # lata i dni są w każdej tabeli — bez premii; pojedyncza wielka litera to nie skrót
        ("rok 2023, dzień 31", {"rok": 0.4, "2023": 0.6, "dzien": 0.4, "31": 0.6}),
        ("Zkm W", {"zkm": 0.4, "w": 0.4}),
    ],
)
def test_prepare_query_identifier_bonus(question: str, expected: dict[str, float]) -> None:
    qt = prepare_query(question, stopwords=frozenset(), stem=fold)
    assert dict(qt.terms) == pytest.approx(expected)


def test_prepare_query_identifier_bonus_in_bigram() -> None:
    qt = prepare_query("tabela PKB", stopwords=frozenset(), stem=fold)
    assert qt.bigrams == (("tabela pkb", pytest.approx(0.6 * 2.0)),)  # max(1.5, 1.0 + 1.0)


def test_prepare_query_identifier_detected_on_any_occurrence() -> None:
    # dedup po lower: „pkb … PKB” to jeden term, ale wersaliki gdziekolwiek dają premię
    qt = prepare_query("pkb PKB", stopwords=frozenset(), stem=fold)
    assert qt.terms == (("pkb", pytest.approx(0.8)),)


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
