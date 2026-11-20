"""Przygotowanie zapytania: fold, wagi termów, unigramy i bigramy (CONTRACT WP E1-7 M2)."""

import re
import unicodedata
from collections.abc import Callable
from itertools import pairwise

from app.domain.retrieval.types import QueryTerms

_TOKEN_RE = re.compile(r"\w+")
# Kontrakt M2: waga 1.5 dla termów o długości >= 6.
_LONG_TERM_MIN_LEN = 6
# Identyfikator w pytaniu (skrót wersalikami „ZKM”, „PKB”, kod z cyfrą „SKARBNET4”, numer „1270”):
# premia wagi, bo inaczej przegrywa ze zwykłymi długimi słowami pytania („oznacza”), a to on
# wskazuje fragment — wektory takich napisów nie odróżniają.
IDENT_BONUS = 1.0


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


_YEAR_RE = re.compile(r"(19|20)\d\d")
_IDENT_NUMBER_MIN_LEN = 3


def _is_ident(token: str) -> bool:
    """Identyfikator: skrót wersalikami („ZKM”, „PKB”), kod z literami i cyframi („SKARBNET4”)
    albo numer co najmniej 3-cyfrowy („poz. 1270”). Lata i dni („2023”, „31”) są w prawie
    każdej tabeli roczników, więc premia przesuwałaby ranking ku przypadkowym fragmentom.
    """
    letters = [ch for ch in token if ch.isalpha()]
    if letters:
        caps = len(letters) >= 2 and all(ch.isupper() for ch in letters)  # noqa: PLR2004
        return caps or any(ch.isdigit() for ch in token)
    return len(token) >= _IDENT_NUMBER_MIN_LEN and not _YEAR_RE.fullmatch(token)


def prepare_query(
    question: str, *, stopwords: frozenset[str], stem: Callable[[str], str]
) -> QueryTerms:
    """Buduje QueryTerms z pytania (algorytm krok po kroku wg M2).

    Tokenizuje po NFC i lower, odrzuca stopwords (porównanie po ``fold``), deduplikuje
    z zachowaniem kolejności, stemuje i liczy wagi unigramów (0.4 * waga) oraz bigramów
    (0.6 * maksimum wag sąsiadów, klucz "a b"). Identyfikatory (``_is_ident`` na tokenie
    przed lower) dostają ``IDENT_BONUS``. Puste lub same stopwords → pola puste.
    """
    raw_terms: list[str] = []
    idents: set[str] = set()
    for original in _TOKEN_RE.findall(unicodedata.normalize("NFC", question)):
        token = original.lower()
        if fold(token) in stopwords:
            continue
        if _is_ident(original):
            idents.add(token)
        if token not in raw_terms:
            raw_terms.append(token)
    stems: list[str] = []
    ident_stems: set[str] = set()
    for term in raw_terms:
        for st in stem(term).split():
            if term in idents:
                ident_stems.add(st)
            if st in stopwords or st in stems:
                continue
            stems.append(st)

    def weight(st: str) -> float:
        return term_weight(st) + (IDENT_BONUS if st in ident_stems else 0.0)

    terms = tuple((st, 0.4 * weight(st)) for st in stems)
    bigrams = tuple((f"{a} {b}", 0.6 * max(weight(a), weight(b))) for a, b in pairwise(stems))
    return QueryTerms(
        raw_terms=tuple(raw_terms),
        terms=terms,
        bigrams=bigrams,
        ft_raw=" ".join(raw_terms),
        ft_stem=" ".join(stems),
    )
