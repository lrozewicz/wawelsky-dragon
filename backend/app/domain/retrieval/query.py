"""Przygotowanie zapytania: fold, wagi termów, unigramy i bigramy (CONTRACT WP E1-7 M2)."""

import re
import unicodedata
from collections.abc import Callable
from itertools import pairwise

from app.domain.retrieval.types import QueryTerms

_TOKEN_RE = re.compile(r"\w+")
# Kontrakt M2: waga 1.5 dla termów o długości >= 6.
_LONG_TERM_MIN_LEN = 6


def fold(token: str) -> str:
    """Normalizuje token: lower, "ł"→"l", NFKD, bez znaków diakrytycznych (kategoria Mn).

    Zwraca ciąg, który może zawierać znaki spoza [a-z0-9] (np. "_"); "ł" nie rozkłada
    się w NFKD, więc jest zamieniane jawnie po lower.
    """
    lowered = token.lower().replace("ł", "l")
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", lowered) if unicodedata.category(ch) != "Mn"
    )


def term_weight(term: str) -> float:
    """Waga termu: 1.0, +0.5 dla dłuższych niż 5 znaków, +0.5 gdy zawiera cyfrę."""
    weight = 1.0
    if len(term) >= _LONG_TERM_MIN_LEN:
        weight += 0.5
    if any(ch.isdigit() for ch in term):
        weight += 0.5
    return weight


def prepare_query(
    question: str, *, stopwords: frozenset[str], stem: Callable[[str], str]
) -> QueryTerms:
    """Buduje QueryTerms z pytania (algorytm krok po kroku wg M2).

    Tokenizuje po NFC i lower, odrzuca stopwords (porównanie po ``fold``), deduplikuje
    z zachowaniem kolejności, stemuje i liczy wagi unigramów (0.4 * waga) oraz bigramów
    (0.6 * maksimum wag sąsiadów, klucz "a b"). Puste lub same stopwords → pola puste.
    """
    text = unicodedata.normalize("NFC", question).lower()
    raw_terms: list[str] = []
    for token in _TOKEN_RE.findall(text):
        if fold(token) in stopwords or token in raw_terms:
            continue
        raw_terms.append(token)
    stems: list[str] = []
    for term in raw_terms:
        for st in stem(term).split():
            if st in stopwords or st in stems:
                continue
            stems.append(st)
    terms = tuple((st, 0.4 * term_weight(st)) for st in stems)
    bigrams = tuple(
        (f"{a} {b}", 0.6 * max(term_weight(a), term_weight(b))) for a, b in pairwise(stems)
    )
    return QueryTerms(
        raw_terms=tuple(raw_terms),
        terms=terms,
        bigrams=bigrams,
        ft_raw=" ".join(raw_terms),
        ft_stem=" ".join(stems),
    )
