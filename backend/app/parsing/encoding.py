"""Detekcja kodowania tekstu (kontrakt C5) — nigdy errors="replace"."""

from __future__ import annotations

import unicodedata

from charset_normalizer import from_bytes

from app.parsing.errors import corrupted_file

# Znaki typowe dla uszkodzonego dekodowania (05 §8.2).
MOJIBAKE_GLYPHS: frozenset[str] = frozenset("ȥ˷ɇɽƃ�￾")

_POLISH = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
# Symbole dopuszczone przez rozstrzygnięcie TL (05 §8.2).
_ALLOWED_SYMBOLS = "°€©®™±×÷≤≥←→•§"  # noqa: RUF001 — symbole celowe (lista kontraktu C5)
_BOM_UTF8 = b"\xef\xbb\xbf"
_BOM_UTF16 = (b"\xff\xfe", b"\xfe\xff")
_CANDIDATES = ("cp1250", "iso8859_2")


def decode_bytes(data: bytes, *, fmt: str = "txt") -> tuple[str, str]:
    """Dekoduje bajty do tekstu; zwraca (tekst, nazwa kodowania). Pierwsze trafienie wygrywa."""
    if data.startswith(_BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data[:2] in _BOM_UTF16:
        return data.decode("utf-16"), "utf-16"
    if b"\x00" in data[:8192]:
        raise corrupted_file(fmt, "binary content in a text file")
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    best_text: str | None = None
    best_name = ""
    best_score = -1
    for name in _CANDIDATES:
        try:
            text = data.decode(name)
        except UnicodeDecodeError:
            continue
        if any("\u0080" <= ch <= "\u009f" for ch in text):  # niedozwolone znaki kontrolne C1
            continue
        score = sum(ch in _POLISH for ch in text)
        if score > best_score:  # remis wygrywa cp1250 (pierwszy kandydat)
            best_text, best_name, best_score = text, name, score
    if best_text is not None:
        return best_text, best_name
    best = from_bytes(data).best()
    if best is None:
        raise corrupted_file(fmt, "unknown text encoding")
    return str(best), best.encoding


def mojibake_ratio(text: str) -> float:
    """Udział znaków nie-białych wyglądających na uszkodzone (glify / poza L, N, P, ASCII, symbole)."""  # noqa: E501
    bad = 0
    total = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        if ch in MOJIBAKE_GLYPHS or not _char_ok(ch):
            bad += 1
    return bad / max(1, total)


def _char_ok(ch: str) -> bool:
    """Dopuszcza ASCII drukowalne, typowe symbole i kategorie Unicode L/N/P (rozstrzygnięcie TL)."""
    if "!" <= ch <= "~":
        return True
    if ch in _ALLOWED_SYMBOLS:
        return True
    return unicodedata.category(ch)[0] in ("L", "N", "P")
