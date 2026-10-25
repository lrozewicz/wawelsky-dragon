"""Testy limitera logowania na tabeli `login_attempts` (CONTRACT E5-2a §4).

Semantyka przeniesiona z usuwanych testów jednostkowych `LoginGuard` (in-memory) —
teraz na bazie MariaDB: okno przesuwne, blokada konta, współdzielony stan.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import RateLimited
from app.db.uow import transaction
from app.services.auth_ratelimit import LoginGuard
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.db

_MSG_TOO_MANY = "Too many login attempts, please try again later."
_EXPECTED_ROWS_AFTER_REJECTED = 13  # 10 + 2 klucze oboczne + utrwalona odrzucona 11. próba
_EXPECTED_ROWS_AFTER_FAILURES = 10
_EXPECTED_ROWS_AFTER_ONE_ATTEMPT_AND_FAILURE = 2


async def _count(sm: async_sessionmaker[AsyncSession]) -> int:
    """Liczba wierszy `login_attempts` w świeżej transakcji (poza transakcją guardu)."""
    async with transaction(sm) as session:
        result = await session.execute(text("SELECT COUNT(*) FROM login_attempts"))
        return int(result.scalar_one())


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def guard(sm: async_sessionmaker[AsyncSession], clock: FrozenClock) -> LoginGuard:
    return LoginGuard("10/min", clock, sm)


async def test_hit_allows_limit_and_raises_on_limit_plus_one(
    guard: LoginGuard, clock: FrozenClock
) -> None:
    for _ in range(10):
        await guard.hit("1.1.1.1", "A@x.pl")
    with pytest.raises(RateLimited) as exc:
        await guard.hit("1.1.1.1", "a@x.pl")
    assert exc.value.message == _MSG_TOO_MANY


async def test_hit_key_is_ip_plus_lowercased_email(
    guard: LoginGuard, sm: async_sessionmaker[AsyncSession]
) -> None:
    for _ in range(10):
        await guard.hit("1.1.1.1", "A@x.pl")
    # Inny IP → osobny licznik, ta sama skrzynka nie gra roli.
    await guard.hit("2.2.2.2", "a@x.pl")
    # Inny e-mail → osobny licznik.
    await guard.hit("1.1.1.1", "b@x.pl")
    # Ten sam klucz (e-mail lowercase) → 11. próba rzuca.
    with pytest.raises(RateLimited):
        await guard.hit("1.1.1.1", "A@X.PL")
    # Wpis odrzuconej 11. próby też jest utrwalony (insert przed commitem, raise po).
    assert await _count(sm) == _EXPECTED_ROWS_AFTER_REJECTED


async def test_hit_window_slides(guard: LoginGuard, clock: FrozenClock) -> None:
    for _ in range(10):
        await guard.hit("1.1.1.1", "a@x.pl")
    clock.advance(60_001)
    await guard.hit("1.1.1.1", "a@x.pl")  # okno minęło → licznik od zera


async def test_lockout_after_threshold_failures(guard: LoginGuard, clock: FrozenClock) -> None:
    for _ in range(9):
        await guard.record_failure("a@x.pl")
    assert await guard.is_locked("a@x.pl") is False
    await guard.record_failure("a@x.pl")
    # E-mail case-insensitive.
    assert await guard.is_locked("A@X.PL") is True


async def test_lockout_expires_after_lockout_window(guard: LoginGuard, clock: FrozenClock) -> None:
    for _ in range(10):
        await guard.record_failure("a@x.pl")
    clock.advance(900_001)
    assert await guard.is_locked("a@x.pl") is False


async def test_record_success_clears_failures(guard: LoginGuard, clock: FrozenClock) -> None:
    for _ in range(9):
        await guard.record_failure("a@x.pl")
    await guard.record_success("a@x.pl")
    await guard.record_failure("a@x.pl")
    assert await guard.is_locked("a@x.pl") is False


async def test_failures_older_than_window_do_not_count(
    guard: LoginGuard, clock: FrozenClock
) -> None:
    for _ in range(5):
        await guard.record_failure("a@x.pl")
    clock.advance(900_001)
    for _ in range(5):
        await guard.record_failure("a@x.pl")
    assert await guard.is_locked("a@x.pl") is False


async def test_is_locked_unknown_email_is_false(guard: LoginGuard) -> None:
    assert await guard.is_locked("nobody@x.pl") is False


async def test_state_is_shared_between_instances(
    sm: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> None:
    """Dowód „spójne między procesami/restartem": druga instancja widzi próby pierwszej."""
    first = LoginGuard("10/min", clock, sm)
    second = LoginGuard("10/min", clock, sm)
    for _ in range(10):
        await first.hit("1.1.1.1", "a@x.pl")
    with pytest.raises(RateLimited):
        await second.hit("1.1.1.1", "a@x.pl")


async def test_hit_purges_entries_older_than_lockout_window(
    guard: LoginGuard, clock: FrozenClock, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`hit` czyści wpisy starsze niż 900 000 ms (retencja) — zostaje tylko bieżący."""
    for _ in range(10):
        await guard.record_failure("a@x.pl")
    assert await _count(sm) == _EXPECTED_ROWS_AFTER_FAILURES
    clock.advance(900_001)
    await guard.hit("1.1.1.1", "a@x.pl")
    assert await _count(sm) == 1


async def test_long_email_is_clamped_not_error(
    guard: LoginGuard, sm: async_sessionmaker[AsyncSession]
) -> None:
    """E-mail > 320 znaków: `hit`/`record_failure` obcinają klucz, nie rzucają DataError."""
    long_email = "a" * 400 + "@x.pl"
    await guard.hit("1.1.1.1", long_email)
    await guard.record_failure(long_email)
    assert await guard.is_locked(long_email) is False
    assert await _count(sm) == _EXPECTED_ROWS_AFTER_ONE_ATTEMPT_AND_FAILURE
