"""Wspólne prezentery wartości: znaczniki czasu i daty (C6) — bez duplikacji logiki."""

from app.api.ragflow.user_view import fmt_date
from app.core.timeutil import rfc1123


def ts(ms: int) -> int:
    """Milisekundy epoki jako int (C6)."""
    return int(ms)


def date(ms: int) -> str:
    """DATE_FMT w UTC (C6) — delegacja do fmt_date z user_view."""
    return fmt_date(ms)


def http_date(ms: int) -> str:
    """RFC 1123 (C6) — delegacja do timeutil.rfc1123."""
    return rfc1123(ms)
