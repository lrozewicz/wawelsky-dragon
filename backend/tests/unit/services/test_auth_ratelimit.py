"""Testy `parse_rate` limitera logowania (CONTRACT E5-2a §4).

Semantyka `LoginGuard` (okno, blokada konta, współdzielony stan) jest testowana na bazie
MariaDB w `tests/integration/auth/test_login_guard_db.py` — tu zostaje wyłącznie parsowanie.
"""

import pytest

from app.services.auth_ratelimit import parse_rate


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("10/min", (10, 60_000)),
        ("5/s", (5, 1_000)),
        ("100/h", (100, 3_600_000)),
    ],
)
def test_parse_rate_valid(spec: str, expected: tuple[int, int]) -> None:
    assert parse_rate(spec) == expected


@pytest.mark.parametrize("spec", ["10", "x/min", "10/day"])
def test_parse_rate_invalid_raises_value_error(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_rate(spec)
