"""Wykrywanie treści zgubionej przez OCR: liczby z warstwy tekstowej PDF kontra wynik OCR."""

from __future__ import annotations

import re
from collections import Counter

COVERAGE_NUMBERS_MIN = 0.85
_MIN_NUMBERS = 10  # poniżej tego jeden numer strony czy przypis zniekształca wynik
_TAG = re.compile(r"<[^>]+>")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_GROUP = 3
_MIN_INT_DIGITS = 4
_YEARS = range(1800, 2101)


def number_atoms(text: str) -> Counter[str]:
    """Liczby jako atomy niezależne od zapisu tysięcy: ``1 368 823`` i ``1368823`` są równe."""
    atoms: Counter[str] = Counter()
    for token in _NUMBER.findall(_TAG.sub("  ", text)):
        if token.isdigit() and len(token) >= _MIN_INT_DIGITS and int(token) not in _YEARS:
            head = len(token) % _GROUP
            if head:
                atoms[token[:head]] += 1
            atoms.update(token[i : i + _GROUP] for i in range(head, len(token), _GROUP))
        else:
            atoms[token] += 1
    return atoms


def coverage(found: Counter[str], expected: Counter[str]) -> float | None:
    """Odsetek ``expected`` obecny w ``found``; ``None``, gdy liczb jest za mało na ocenę."""
    total = sum(expected.values())
    if total < _MIN_NUMBERS:
        return None
    return sum((expected & found).values()) / total
