"""Testy ponawiania transakcji zapisu przy konflikcie blokad InnoDB (brief T6, DEC-088)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.services.ingest_commit import (
    BACKOFF_S,
    MAX_ATTEMPTS,
    is_lock_conflict,
    retry_lock_conflicts,
)


def _lock_error(code: int) -> OperationalError:
    """OperationalError z kodem InnoDB w ``orig.args[0]`` (kształt z MariaDB/pymysql)."""
    return OperationalError("stmt", {}, Exception(code, "lock"))


class FakeSleep:
    """Atrapa ``asyncio.sleep``: notuje czasy, nie czeka."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


def _flaky(
    failures: list[BaseException], result: Any = "ok"
) -> tuple[Callable[[], Awaitable[Any]], list[int]]:
    """Buduje ``op``, który rzuca kolejne ``failures``, a potem zwraca ``result``.

    Zwraca ``op`` oraz jednokomórkową listę z liczbą prób (mutowalny licznik).
    """
    calls = [0]

    async def op() -> Any:
        calls[0] += 1
        if calls[0] <= len(failures):
            raise failures[calls[0] - 1]
        return result

    return op, calls


def test_orig_args_hold_db_code() -> None:
    assert _lock_error(1213).orig.args[0] == 1213  # noqa: PLR2004 — kod InnoDB z MariaDB


def test_is_lock_conflict_only_recognizes_retry_codes() -> None:
    assert is_lock_conflict(_lock_error(1213)) is True
    assert is_lock_conflict(_lock_error(1205)) is True
    assert is_lock_conflict(_lock_error(1045)) is False
    assert is_lock_conflict(ValueError("boom")) is False


async def test_two_conflicts_then_success_backs_off_twice() -> None:
    """1213 dwa razy, trzecia próba OK: wynik zwrócony, przerwy 0.2 i 0.5 (brief T6)."""
    op, calls = _flaky([_lock_error(1213), _lock_error(1213)])
    sleep = FakeSleep()
    assert await retry_lock_conflicts(op, sleep=sleep) == "ok"
    assert calls[0] == 3  # noqa: PLR2004 — 2 nieudane + 1 udana
    assert sleep.calls == [BACKOFF_S[0], BACKOFF_S[1]]


async def test_exhausted_attempts_propagate_error() -> None:
    """Trzy razy 1213 → wyjątek leci dalej po ``MAX_ATTEMPTS`` próbach (brief T6)."""
    op, calls = _flaky([_lock_error(1213)] * MAX_ATTEMPTS)
    sleep = FakeSleep()
    with pytest.raises(OperationalError):
        await retry_lock_conflicts(op, sleep=sleep)
    assert calls[0] == MAX_ATTEMPTS
    assert sleep.calls == [BACKOFF_S[0], BACKOFF_S[1]]


async def test_other_exception_not_retried() -> None:
    """ValueError → 1 próba, bez czekania (brief T6)."""
    op, calls = _flaky([ValueError("boom")])
    sleep = FakeSleep()
    with pytest.raises(ValueError):
        await retry_lock_conflicts(op, sleep=sleep)
    assert calls[0] == 1
    assert sleep.calls == []


async def test_other_db_error_not_retried() -> None:
    """OperationalError z kodem 1045 (auth) → 1 próba, bez czekania (brief T6)."""
    op, calls = _flaky([_lock_error(1045)])
    sleep = FakeSleep()
    with pytest.raises(OperationalError):
        await retry_lock_conflicts(op, sleep=sleep)
    assert calls[0] == 1
    assert sleep.calls == []


async def test_lock_wait_timeout_is_retried() -> None:
    """Kod 1205 (lock wait timeout) też jest ponawiany (brief T6)."""
    op, calls = _flaky([_lock_error(1205)])
    sleep = FakeSleep()
    assert await retry_lock_conflicts(op, sleep=sleep) == "ok"
    assert calls[0] == 2  # noqa: PLR2004 — 1 nieudana + 1 udana
    assert sleep.calls == [BACKOFF_S[0]]
