"""Testy present/common: ts, date, http_date (C6, przykłady briefu dosłownie)."""

from app.api.ragflow.present.common import date, http_date, ts

_TS_MS = 1700000000123


def test_ts_passthrough_int() -> None:
    """ts(1700000000123) → 1700000000123."""
    assert ts(_TS_MS) == _TS_MS


def test_date_utc_format() -> None:
    """date(0) → DATE_FMT w UTC."""
    assert date(0) == "1970-01-01 00:00:00"


def test_http_date_rfc1123() -> None:
    """http_date(0) → RFC 1123."""
    assert http_date(0) == "Thu, 01 Jan 1970 00:00:00 GMT"
