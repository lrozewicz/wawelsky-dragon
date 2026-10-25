"""Liczenie tokenów cl100k_base (kontrakt C6, K5 §3.6, SP-6)."""

import functools

import tiktoken


@functools.cache
def _encoding() -> tiktoken.Encoding:
    """Kodowanie ładowane leniwie raz na proces."""
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Liczba tokenów tekstu; tagi specjalne liczone jako zwykły tekst (bez wyjątku)."""
    return len(_encoding().encode(text, disallowed_special=()))


def truncate_tokens(text: str, limit: int) -> str:
    """Obcięcie tekstu do co najwyżej `limit` tokenów; limit <= 0 → pusty string."""
    if limit <= 0:
        return ""
    tokens = _encoding().encode(text, disallowed_special=())
    if len(tokens) <= limit:
        return text
    return _encoding().decode(tokens[:limit])
