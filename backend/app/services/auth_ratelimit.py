"""Limiter logowania: okno przesuwne w tabeli `login_attempts` (CONTRACT E5-2a §4).

Źródłem prawdy jest baza — limiter jest spójny między procesami i po restarcie.
Semantyka bez zmian wobec wersji in-memory: limit prób per IP+e-mail z
`settings.rate_limit_login` (`"10/min"`, K8) i blokada konta po 10 porażkach w 15 min
(e-mail lowercase). Okno retencji i blokady = 900 000 ms.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import RateLimited
from app.core.timeutil import Clock
from app.db.repositories import login_attempts as attempts_repo
from app.db.uow import transaction

_PERIODS_MS = {"s": 1_000, "min": 60_000, "h": 3_600_000}

# `ip VARCHAR(64)` i `email_key VARCHAR(320)` — obcinamy do rozmiaru kolumn (CONTRACT E5-2a §4).
# E-mail bez clampu wysypywał INSERT (DataError → HTTP 500) dla >320 znaków.
_IP_MAX_LEN = 64
_EMAIL_MAX_LEN = 320


def parse_rate(spec: str) -> tuple[int, int]:
    """`"10/min"` → `(10, 60_000)`; `"5/s"`; `"100/h"`; inny format → `ValueError`."""
    count, sep, unit = spec.partition("/")
    if not sep or not count.isdigit() or unit not in _PERIODS_MS:
        raise ValueError(f"invalid rate spec: {spec}")
    return int(count), _PERIODS_MS[unit]


class LoginGuard:
    """Limit prób logowania per IP + e-mail i blokada konta po serii porażek (DB)."""

    def __init__(
        self,
        rate_spec: str,
        clock: Clock,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        lockout_threshold: int = 10,
        lockout_window_ms: int = 900_000,
    ) -> None:
        self._limit, self._window_ms = parse_rate(rate_spec)
        self._clock = clock
        self._sessionmaker = sessionmaker
        self._lockout_threshold = lockout_threshold
        self._lockout_window_ms = lockout_window_ms

    async def hit(self, ip: str, email: str) -> None:
        """Rejestruje próbę (także udaną); próba nr limit+1 w oknie → `RateLimited`.

        W jednej transakcji: retencja (900 000 ms), wpis próby i licznik okna.
        `RateLimited` rzucane PO commicie, żeby rollback nie skasował wpisu.
        """
        now = self._clock.now_ms()
        ip_key = ip[:_IP_MAX_LEN]
        email_key = email.lower()[:_EMAIL_MAX_LEN]
        async with transaction(self._sessionmaker) as session:
            await attempts_repo.purge_before(session, now - self._lockout_window_ms)
            await attempts_repo.insert(
                session, kind="a", ip=ip_key, email_key=email_key, now_ms=now
            )
            count = await attempts_repo.count_attempts(
                session, ip=ip_key, email_key=email_key, since_ms=now - self._window_ms
            )
        if count > self._limit:
            raise RateLimited("Too many login attempts, please try again later.")

    async def is_locked(self, email: str) -> bool:
        """Blokada po `lockout_threshold` porażkach w `lockout_window_ms` (e-mail lowercase)."""
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            count = await attempts_repo.count_failures(
                session,
                email_key=email.lower()[:_EMAIL_MAX_LEN],
                since_ms=now - self._lockout_window_ms,
            )
        return count >= self._lockout_threshold

    async def record_failure(self, email: str) -> None:
        """Znacznik porażki logowania dla e-maila (lowercase)."""
        now = self._clock.now_ms()
        async with transaction(self._sessionmaker) as session:
            await attempts_repo.insert(
                session, kind="f", ip="", email_key=email.lower()[:_EMAIL_MAX_LEN], now_ms=now
            )

    async def record_success(self, email: str) -> None:
        """Sukces logowania czyści licznik porażek (i tym samym blokadę)."""
        async with transaction(self._sessionmaker) as session:
            await attempts_repo.delete_failures(session, email_key=email.lower()[:_EMAIL_MAX_LEN])
