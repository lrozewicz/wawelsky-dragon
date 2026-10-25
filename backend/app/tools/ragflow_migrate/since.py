"""Znacznik ``--since`` (ISO 8601) → milisekundy epoki UTC (kontrakt E4-6c §1)."""

from datetime import UTC, datetime

from app.core.timeutil import to_ms


def parse_since(text: str) -> int:
    """ISO 8601 → ms epoki UTC.

    Bez strefy znacznik jest UTC (``2026-09-30T12:00:00`` = 12:00 UTC), sama data to północ UTC
    (``2026-09-30``). Nierozpoznany tekst → ``ValueError``.
    """
    value = text.strip()
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"nieprawidłowy znacznik czasu: {text!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return to_ms(dt)
