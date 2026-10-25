"""Generatory identyfikatorów: własny UUIDv7 (RFC 9562) i skróty chunków (kontrakt C5)."""

import re
import secrets
import threading
import time
from typing import Protocol

import xxhash

from app.core.errors import ValidationFailed

# Stan monotoniczności generatora UUIDv7 — wspólny dla procesu, chroniony _lock.
_lock = threading.Lock()
_last_ms = 0
_counter = 0

_COUNTER_MAX = 0xFFF

_HEX32_RE = re.compile(r"[0-9a-fA-F]{32}")
_DASHED_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class IdGenerator(Protocol):
    """Źródło identyfikatorów wstrzykiwane w kontener."""

    def new_id(self) -> str: ...


class UuidV7Generator:
    """Domyślny generator — UUIDv7."""

    def new_id(self) -> str:
        return new_id()


def new_id() -> str:
    """UUIDv7: 48 bitów znacznika czasu ms, licznik monotoniczności w rand_a, rand_b z secrets."""
    global _last_ms, _counter  # noqa: PLW0603 — stan monotoniczności w zmiennych modułowych pod _lock (kontrakt C5)
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            # Nowa milisekunda: losowy zapas licznika zostawia miejsce na wywołania w tej samej ms.
            _counter = secrets.randbits(11)
            _last_ms = ms
        else:
            # Ta sama ms albo zegar cofnięty: trzymamy starą ms i liczymy dalej.
            ms = _last_ms
            _counter += 1
            if _counter > _COUNTER_MAX:
                _last_ms += 1
                ms = _last_ms
                _counter = 0
        value = (ms << 80) | (7 << 76) | (_counter << 64) | (0b10 << 62) | secrets.randbits(62)
        return f"{value:032x}"


def new_chunk_id(document_id: str, ordinal: int, content: str) -> str:
    """Deterministyczny identyfikator chunka: xxh64 z dokumentu, porządku i treści."""
    return xxhash.xxh64(f"{document_id}\x1f{ordinal}\x1f{content}".encode()).hexdigest()


def is_valid_id(value: str) -> bool:
    """True dla 32 znaków hex albo kanonicznego UUID z myślnikami."""
    return _HEX32_RE.fullmatch(value) is not None or _DASHED_RE.fullmatch(value) is not None


def normalize_id(value: str) -> str:
    """Znormalizowana forma identyfikatora: małe znaki hex, bez myślników."""
    if not is_valid_id(value):
        raise ValidationFailed(f"Invalid id: {value}")
    return value.replace("-", "").lower()
