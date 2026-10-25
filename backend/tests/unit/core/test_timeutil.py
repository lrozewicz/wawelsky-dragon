"""Testy narzędzi czasu (kontrakt C6)."""

import time
from datetime import UTC, datetime

import pytest

from app.core.timeutil import SystemClock, from_ms, iso, now_ms, rfc1123, seconds, to_ms

_RFC1123_MS = 1729232406000
_RFC1123_EXPECTED = "Fri, 18 Oct 2024 06:20:06 GMT"
_AWARE_DT = datetime(2026, 9, 23, 10, 0, 0, tzinfo=UTC)
_AWARE_MS = 1790157600000
_AWARE_MS_999 = 1790157600999
_NAIVE_DT = datetime(2026, 9, 23)
_AWARE_DT_MICROSECONDS = datetime(2026, 9, 23, 10, 0, 0, 123000, tzinfo=UTC)
_ISO_EXPECTED = "2026-09-23T10:00:00Z"
_SECONDS_INPUT_MS = 1500
_SECONDS_EXPECTED = 1.5
_NOW_TOLERANCE_MS = 1000


def test_rfc1123() -> None:
    assert rfc1123(_RFC1123_MS) == _RFC1123_EXPECTED


def test_to_ms_aware() -> None:
    assert to_ms(_AWARE_DT) == _AWARE_MS


def test_to_ms_naive_raises() -> None:
    with pytest.raises(ValueError):
        to_ms(_NAIVE_DT)


def test_from_ms() -> None:
    assert from_ms(_AWARE_MS) == _AWARE_DT


def test_from_ms_to_ms_roundtrip() -> None:
    assert from_ms(to_ms(_AWARE_DT_MICROSECONDS)) == _AWARE_DT_MICROSECONDS


@pytest.mark.parametrize("value", [_AWARE_MS, _AWARE_MS_999, _AWARE_DT], ids=["ms", "ms999", "dt"])
def test_iso(value: int | datetime) -> None:
    assert iso(value) == _ISO_EXPECTED


def test_iso_naive_raises() -> None:
    with pytest.raises(ValueError):
        iso(_NAIVE_DT)


def test_seconds() -> None:
    assert seconds(_SECONDS_INPUT_MS) == _SECONDS_EXPECTED


def test_now_ms_and_system_clock() -> None:
    reference = time.time_ns() // 1_000_000
    assert isinstance(now_ms(), int)
    assert isinstance(SystemClock().now_ms(), int)
    assert abs(now_ms() - reference) < _NOW_TOLERANCE_MS
    assert abs(SystemClock().now_ms() - reference) < _NOW_TOLERANCE_MS
