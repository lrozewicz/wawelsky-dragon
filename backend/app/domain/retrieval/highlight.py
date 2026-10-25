"""Podświetlanie trafień w treści chunku (CONTRACT WP E1-7 M4)."""

import re
from collections.abc import Sequence

from app.domain.retrieval.query import fold

_TOKEN_RE = re.compile(r"\w+")


def highlight(text: str, terms: Sequence[str], window: int = 120) -> str:
    """Fragment tekstu wokół pierwszego trafienia z owiniętymi w ``<em>`` trafieniami.

    Trafienie = całe słowo (``\\w+``), porównanie po ``fold`` (bez wielkości liter
    i diakrytyków). Brak trafień → tekst bez zmian. Okno: ``window`` znaków przed
    początkiem i po końcu pierwszego trafienia, ograniczone do tekstu, bez "...".
    """
    keys = {fold(term) for term in terms if term}
    matches = [m for m in _TOKEN_RE.finditer(text) if fold(m.group()) in keys]
    if not matches:
        return text
    first = matches[0]
    start = max(0, first.start() - window)
    end = min(len(text), first.end() + window)
    parts: list[str] = []
    pos = start
    for m in matches:
        if m.start() < start or m.end() > end:
            continue
        parts.append(text[pos : m.start()])
        parts.append(f"<em>{m.group()}</em>")
        pos = m.end()
    parts.append(text[pos:end])
    return "".join(parts)
