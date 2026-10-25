"""Parsowanie pola delimiterów i dzielenie akapitów (CONTRACT WP E1-5 C3).

Algorytm 1:1 z upstream RAGFlow v0.27.0 `rag/nlp/delim.py` l. 101-153 (bez logging.debug).
"""

import re

from app.domain.chunking.types import DelimiterSpec

_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _normalize_newlines(text: str) -> str:
    """Normalizacja CRLF i samotnego CR do LF (jak upstream normalize_text_newlines)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_delimiter_field(delimiter: str) -> DelimiterSpec:
    """Pole delimiterów → specyfikacja: dedup, najdłuższe pierwsze (sort stabilny).

    ``has_wrapped`` liczony na polu PRZED normalizacją (jak upstream has_wrapped_delimiter).
    """
    has_wrapped = _BACKTICK_RE.search(delimiter) is not None
    if not delimiter:
        return DelimiterSpec((), False)
    normalized = _normalize_newlines(delimiter)
    delimiters: list[str] = []
    seen: set[str] = set()
    cursor = 0
    for match in _BACKTICK_RE.finditer(normalized):
        start, end = match.span()
        # Znaki poza tokenami w backtickach — każdy znak osobno.
        for ch in normalized[cursor:start]:
            if ch not in seen:
                seen.add(ch)
                delimiters.append(ch)
        token = match.group(1)
        if token and token not in seen:
            seen.add(token)
            delimiters.append(token)
        cursor = end
    # Znaki po ostatnim tokenie (albo całe pole, gdy backticków nie ma).
    for ch in normalized[cursor:]:
        if ch not in seen:
            seen.add(ch)
            delimiters.append(ch)
    # Sort stabilny po długości, najdłuższe pierwsze.
    return DelimiterSpec(tuple(sorted(delimiters, key=len, reverse=True)), has_wrapped)


def split_paragraphs(text: str, spec: DelimiterSpec) -> list[str]:
    """Dzieli tekst wg specyfikacji; delimiter nigdy nie trafia do wyniku (C3)."""
    normalized = _normalize_newlines(text)
    if not spec.delimiters:
        return [normalized] if normalized.strip() else []
    body = "|".join(re.escape(d) for d in spec.delimiters)
    full_delimiter = re.compile(body)
    parts = re.split(f"({body})", normalized, flags=re.DOTALL)
    return [
        part.strip()
        for part in parts
        if part and not full_delimiter.fullmatch(part) and part.strip()
    ]
