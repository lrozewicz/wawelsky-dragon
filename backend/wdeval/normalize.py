"""Normalizacja tekstu do dopasowania odpowiedzi (port z bety, A7 SPEC 7.3).

Klasy znakow budowane sa jawnie z punktow kodowych (``chr``) — w becie te
same znaki siedza w literach jako niewidzialne znaki; tu sa rozpisane, zeby
byly widoczne w review i odporne na edytory.
"""

from __future__ import annotations

import re

# myslelniki: U+2010 HYPHEN, U+2013 EN DASH, U+2014 EM DASH, U+2015 HORIZONTAL
# BAR, U+2212 MINUS SIGN.
_DASHES = "".join(chr(cp) for cp in (0x2010, 0x2013, 0x2014, 0x2015, 0x2212))
_DASHES_RE = re.compile("[" + _DASHES + "]")
# spacje wygladajace jak separator tysiecy: U+00A0 NBSP, U+202F NARROW NO-BREAK
# SPACE, U+2009 THIN SPACE.
_NBSP_SPACES_RE = re.compile("[" + "".join(chr(cp) for cp in (0x00A0, 0x202F, 0x2009)) + "]")
_THOUSANDS_SEP_RE = re.compile(r"(?<=\d)\s+(?=\d)")
_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = _DASHES_RE.sub("-", text)
    text = _NBSP_SPACES_RE.sub(" ", text)
    # separator tysiecy: cyfra-spacja-cyfra (jeden przebieg wystarcza -
    # lookbehind/lookahead patrzy na oryginalny string, wiec 1 234 567
    # skleja sie w calosci)
    text = _THOUSANDS_SEP_RE.sub("", text)
    text = _DECIMAL_COMMA_RE.sub(".", text)
    text = text.casefold()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def contains(haystack: str, needle: str) -> bool:
    return normalize(needle) in normalize(haystack)
