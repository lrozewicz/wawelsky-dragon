"""Narzędzia czasu: milisekundy epoki Unix i formaty RFC 1123 / ISO 8601 (kontrakt C6)."""

import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Protocol

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Clock(Protocol):
    """Źródło czasu wstrzykiwane w kontener."""

    def now_ms(self) -> int: ...


class SystemClock:
    """Zegar systemowy."""

    def now_ms(self) -> int:
        return now_ms()


def now_ms() -> int:
    """Aktualny czas w milisekundach epoki Unix."""
    return time.time_ns() // 1_000_000


def to_ms(dt: datetime) -> int:
    """Milisekundy epoki Unix dla datetime świadomej strefy; naive → ValueError."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return (dt - EPOCH) // timedelta(milliseconds=1)


def from_ms(ms: int) -> datetime:
    """Świadoma datetime w UTC z milisekund epoki Unix."""
    return EPOCH + timedelta(milliseconds=ms)


def rfc1123(ms: int) -> str:
    """Data w formacie RFC 1123 (nagłówek HTTP Date)."""
    return format_datetime(from_ms(ms), usegmt=True)


def iso(ms_or_dt: int | datetime) -> str:
    """Znacznik ISO 8601 w UTC ucięty do sekund; naive datetime → ValueError."""
    dt = from_ms(ms_or_dt) if isinstance(ms_or_dt, int) else ms_or_dt
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds(ms: int) -> float:
    """Milisekundy jako sekundy (do logów)."""
    return ms / 1000
