"""Normalizacja tekstu pod FULLTEXT MariaDB — wspólne dla zapisu (E1-6) i zapytań (E1-7)."""

from __future__ import annotations

import functools
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stempel import StempelStemmer  # type: ignore[import-untyped]

# Białe znaki inne niż "\n" (spacje, taby, NBSP itd.) → jedna spacja.
_WS_RUN = re.compile(r"[^\S\n]+")
# ≥ 3 kolejne "\n" → jeden pusty wiersz ("\n\n").
_BLANK_RUN = re.compile(r"\n{3,}")
# Tokeny do stemowania: litery, cyfry i "_" (Unicode).
_WORD = re.compile(r"\w+")
# Tokeny po fold — same ASCII.
_ASCII_WORD = re.compile(r"[a-z0-9]+")


def ft_text(text: str) -> str:
    """Tekst do kolumny FULLTEXT: NFC, bez znaków kontrolnych (poza "\\n" i "\\t").

    Białe znaki poza "\\n" składane do jednej spacji, końce linii stripowane,
    ≥ 3 kolejne "\\n" zwinięte do "\\n\\n". Bez lower(), bez usuwania
    diakrytyków, bez stopwords — treść pozostaje czytelna.
    """
    s = unicodedata.normalize("NFC", text)
    # "\r\n" i "\r" do "\n" — zanim usuniemy znaki kategorii C* (inaczej "\r" zniknie bez śladu).
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = "".join(
        ch for ch in s if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )
    s = _WS_RUN.sub(" ", s)
    lines = (line.strip() for line in s.split("\n"))
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def fold(text: str) -> str:
    """Postać do porównań: NFKD, "ł"→"l", bez znaków diakrytycznych (Mn), tokeny [a-z0-9]."""
    s = unicodedata.normalize("NFKD", text.lower()).replace("ł", "l")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return " ".join(_ASCII_WORD.findall(s))


@functools.cache
def _stemmer() -> StempelStemmer:
    """Leniwa instancja stemmera: ładowanie tabeli trwa ~2 s — nie przy imporcie modułu."""
    from stempel import StempelStemmer  # noqa: PLC0415

    return StempelStemmer.polimorf()


def stem_text(text: str) -> str:
    """Stemming + fold — treść kolumny content_stem i postać zapytań FULLTEXT."""
    stems: list[str] = []
    for token in _WORD.findall(text.lower()):
        stem = _stemmer().stem(token)
        if not stem:
            # Stempel zwraca None (albo pusty string), gdy nie wygeneruje rdzenia.
            stem = token
        folded = fold(stem)
        if folded:
            stems.append(folded)
    return " ".join(stems)
