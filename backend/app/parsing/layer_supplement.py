"""Uzupełnienie wyniku OCR/VLM strony PDF o linie warstwy tekstowej, które OCR pominął.

Model OCR (Xiaomi-OCR-0) przepisuje „główną treść” strony, a wnętrze map i wykresów zostawia:
z mapy „BIBLIOTEKI PUBLICZNE W 2024 R.” zostaje tytuł, a legenda ``pomorskie = 147`` ginie,
choć PDF ma ją w warstwie tekstowej. Gdy z warstwy znikła choć jedna liczba (poza rokiem),
dopisujemy na końcu strony linie warstwy nieobecne w wyniku OCR — także bez liczb, bo niosą
opis wartości („Czytelnicy bibliotek publicznych na 1000 ludności”). Pomijamy spis treści,
linie powtarzające się na wielu stronach (paginy, stopki) i rozsypane etykiety mapy.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from html import escape

_TAG = re.compile(r"<[^>]+>")
_THOUSANDS = re.compile(r"(?<=\d)[ \u00a0](?=\d{3}\b)")
_NUMBER = re.compile(r"(?<![^\W\d_])-?\d+(?:,\d+)?")  # bez cyfr jednostek: km2, m3
_YEAR = re.compile(r"^(1[89]|20)\d\d$")
_WORD = re.compile(r"[^\W\d_]{2,}")
_TOC = re.compile(r"\.{4,}|…{2,}")
_SKELETON = re.compile(r"[\W_]+")
_DIGITS = re.compile(r"\d+")
REPEATED_MIN_PAGES = 3  # linia (z cyframi zamienionymi na #) na tylu stronach to pagina/stopka
EDGE_LINES = 1  # pagina/stopka: pierwsza albo ostatnia linia warstwy; legenda mapy bywa tuż obok
_SCRAMBLED_SHARE = 0.4  # udział jednoznakowych tokenów: rozsypany podpis mapy („c h o d …”)


def _plain(html: str) -> str:
    return _TAG.sub(" ", html).replace("\u00a0", " ")


def _numbers(text: str) -> set[str]:
    """Liczby całe (``19 547`` = ``19547``, ``3.5`` = ``3,5``), bez dzielenia na grupy."""
    return set(_NUMBER.findall(_THOUSANDS.sub("", text).replace(".", ",")))


def _skeleton(text: str) -> str:
    return _SKELETON.sub("", text.lower())


def line_key(line: str) -> str:
    """Klucz linii niezależny od liczb — do wykrywania pagin i stopek między stronami."""
    return _DIGITS.sub("#", " ".join(line.lower().split()))


def _edges(lines: Sequence[str]) -> list[str]:
    return [*lines[:EDGE_LINES], *lines[EDGE_LINES:][-EDGE_LINES:]]


def repeated_keys(layers: Iterable[str]) -> frozenset[str]:
    """Klucze brzegowych linii warstwy (pagina, stopka) obecnych na ``REPEATED_MIN_PAGES`` stronach.

    Tylko brzegi: w środku strony ten sam szablon (``pomorskie = # pomorskie = #,#``) ma
    legenda każdej mapy, a to właśnie treść do odzyskania.
    """
    keys = (
        {line_key(x) for x in _edges([y for y in layer.splitlines() if y.strip()])}
        for layer in layers
    )
    counts = Counter(key for page in keys for key in page)
    return frozenset(key for key, n in counts.items() if n >= REPEATED_MIN_PAGES)


def _noise(line: str, *, edge: bool, drop: frozenset[str]) -> bool:
    tokens = line.split()
    return (
        not tokens
        or not _WORD.search(line)
        or bool(_TOC.search(line))
        or (edge and line_key(line) in drop)
        or sum(len(t) == 1 for t in tokens) / len(tokens) > _SCRAMBLED_SHARE
    )


def missing_lines(fragment: str, layer: str, drop: frozenset[str] = frozenset()) -> list[str]:
    """Linie warstwy nieobecne w ``fragment`` — tylko gdy OCR zgubił z warstwy jakąś liczbę."""
    text = _plain(fragment)
    found = _numbers(text)
    lines = [" ".join(x.split()) for x in layer.splitlines() if x.strip()]
    edge = set(range(EDGE_LINES)) | set(range(max(EDGE_LINES, len(lines) - EDGE_LINES), len(lines)))
    kept = [x for i, x in enumerate(lines) if not _noise(x, edge=i in edge, drop=drop)]
    lost = any(not _YEAR.match(n.lstrip("-")) for line in kept for n in _numbers(line) - found)
    if not lost:
        return []
    body = _skeleton(text)
    return [x for x in kept if _skeleton(x) not in body]


def supplement_html(lines: Sequence[str]) -> str:
    """Dopisek do HTML strony: każda linia jako akapit."""
    return "".join(f"<p>{escape(line)}</p>" for line in lines)
