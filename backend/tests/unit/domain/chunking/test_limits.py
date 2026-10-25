"""Testy limitów chunkera (CONTRACT WP E1-5 C5); prawdziwy tiktoken z app.llm.tokens."""

import pytest

from app.domain.chunking.limits import split_sentences, split_to_limit
from app.llm.tokens import count_tokens

# Nazwane stałe zamiast liczb magicznych (PLR2004).
SHORT_TEXT_LIMIT = 50
THREE_SENTENCES_LIMIT = 25
_EXPECTED_PIECES = 2
LONG_SENTENCE_LIMIT = 20
_SINGLE_WORD = "x" * 500
_SINGLE_WORD_LIMIT = 10
_MIN_SENTENCE_PIECES = 3
_SENTENCE_ELEMENT_COUNT = 5
_PROPERTY_LIMITS = (5, 17, 64)
_MIN_WORDS_FOR_LIMIT = 2

_SENTENCE_1 = "Ala ma małego kota."
_SENTENCE_2 = "Kot śpi na kanapie."
_SENTENCE_3 = "Pies goni kaczkę ogrodem."

# Jedno długie zdanie bez kropek (~60 słów, każde słowo krótkie; wielka litera na starcie,
# żeby po kropce poprzedniego zdania następował podział).
_LONG_SENTENCE = " ".join(
    ["Kot", "pies", "lew", "ryś", "wilk", "bóbr", "łoś", "sarna", "dzik", "jeż"] * 6
)


def _property_text() -> str:
    """~300 słów PL z liczbami (powtórzone zdania)."""
    zdanie = "Rozdział {} opisuje {} przypadków testowych zespołu jakości oprogramowania."
    return " ".join(zdanie.format(i, i * 7) for i in range(1, 26))


def test_short_text_single_piece():
    """Tekst mieści się w limicie → jeden kawałek (C5)."""
    assert split_to_limit("krótki tekst", SHORT_TEXT_LIMIT, count_tokens) == ["krótki tekst"]


def test_three_sentences_greedy_merge():
    """3 zdania po ~9-12 tokenów, limit 25 → 2 kawałki: zdania 1-2, potem zdanie 3 (C5)."""
    tekst = f"{_SENTENCE_1} {_SENTENCE_2} {_SENTENCE_3}"
    wynik = split_to_limit(tekst, THREE_SENTENCES_LIMIT, count_tokens)
    assert len(wynik) == _EXPECTED_PIECES
    assert wynik == [f"{_SENTENCE_1} {_SENTENCE_2}", _SENTENCE_3]


def test_long_sentence_split_by_words():
    """Zdanie ponad limit dzielone po słowach; każdy kawałek mieści się w limicie (C5)."""
    wynik = split_to_limit(_LONG_SENTENCE, LONG_SENTENCE_LIMIT, count_tokens)
    assert len(wynik) >= _MIN_SENTENCE_PIECES
    assert all(count_tokens(kawalek) <= LONG_SENTENCE_LIMIT for kawalek in wynik)
    assert " ".join(wynik).split() == _LONG_SENTENCE.split()


def test_long_sentence_closes_previous_piece():
    """Krótkie zdanie zostaje zamknięte jako kawałek, zanim długie pocięte na słowa (C5)."""
    tekst = f"{_SENTENCE_1} {_LONG_SENTENCE}"
    wynik = split_to_limit(tekst, LONG_SENTENCE_LIMIT, count_tokens)
    assert wynik[0] == _SENTENCE_1
    assert " ".join(wynik).split() == tekst.split()


def test_single_word_longer_than_limit_not_split():
    """Słowo dłuższe niż limit zostaje całe — nigdy podział w środku słowa (C5)."""
    wynik = split_to_limit(_SINGLE_WORD, _SINGLE_WORD_LIMIT, count_tokens)
    assert wynik == [_SINGLE_WORD]


def test_split_sentences_basic():
    """Podział po . ! ? przed wielką literą; po '?' mała litera → brak podziału (C5)."""
    assert split_sentences("Ala ma kota. Kot ma Alę! Czy? tak.") == [
        "Ala ma kota.",
        "Kot ma Alę!",
        "Czy? tak.",
    ]


def test_split_sentences_quotes_and_ellipsis():
    """Cudzysłów „ i … kończą zdanie; liczba po kropce też zaczyna nowe (C5)."""
    wynik = split_sentences("Zdanie. „Cytat” dalej. Źródło 2. Koniec…  Nowe")
    assert wynik == ["Zdanie.", "„Cytat” dalej.", "Źródło 2.", "Koniec…", "Nowe"]
    assert len(wynik) == _SENTENCE_ELEMENT_COUNT


def test_split_sentences_whitespace_only():
    """Sam biały znak → brak zdań (gałąź odrzucenia pustych segmentów)."""
    assert split_sentences("   ") == []


def test_limit_zero_behaves_like_one():
    """Limit < 1 jak limit 1: bez wyjątku, słowa pojedynczo (C5)."""
    tekst = "ala ma kota"
    assert split_to_limit(tekst, 0, count_tokens) == ["ala", "ma", "kota"]
    assert split_to_limit(tekst, 0, count_tokens) == split_to_limit(tekst, 1, count_tokens)


@pytest.mark.parametrize("limit", _PROPERTY_LIMITS)
def test_property_invariants(limit):
    """Niezmiennik C5: żadne słowo nie ginie ani nie jest rozcinane; kawałki ≥ 2 słów ≤ limit."""
    tekst = _property_text()
    wynik = split_to_limit(tekst, limit, count_tokens)
    assert wynik
    assert " ".join(wynik).split() == tekst.split()
    for kawalek in wynik:
        if len(kawalek.split()) >= _MIN_WORDS_FOR_LIMIT:
            assert count_tokens(kawalek) <= limit
