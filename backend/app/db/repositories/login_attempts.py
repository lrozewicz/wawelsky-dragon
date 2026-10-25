"""Repozytorium tabeli `login_attempts` (CONTRACT E5-2a §4).

SQL przez ``text()`` z parametrami wiązanymi (H15), bez ``commit``/``rollback`` —
transakcję otwiera wywołująca (``app.db.uow.transaction``). ``kind``: ``'a'`` = próba
logowania, ``'f'`` = porażka (blokada konta).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PURGE_SQL = text("DELETE FROM login_attempts WHERE attempted_at < :cutoff")

_INSERT_SQL = text(
    "INSERT INTO login_attempts (kind, ip, email_key, attempted_at)"
    " VALUES (:kind, :ip, :email_key, :now_ms)"
)

_COUNT_ATTEMPTS_SQL = text(
    "SELECT COUNT(*) FROM login_attempts"
    " WHERE kind = 'a' AND ip = :ip AND email_key = :email_key AND attempted_at > :since_ms"
)

_COUNT_FAILURES_SQL = text(
    "SELECT COUNT(*) FROM login_attempts"
    " WHERE kind = 'f' AND email_key = :email_key AND attempted_at > :since_ms"
)

_DELETE_FAILURES_SQL = text(
    "DELETE FROM login_attempts WHERE kind = 'f' AND email_key = :email_key"
)


async def purge_before(session: AsyncSession, cutoff_ms: int) -> None:
    """Usuwa wszystkie wpisy starsze niż `cutoff_ms` (retencja 900 000 ms)."""
    await session.execute(_PURGE_SQL, {"cutoff": cutoff_ms})


async def insert(session: AsyncSession, *, kind: str, ip: str, email_key: str, now_ms: int) -> None:
    """Wstawia wpis próby/porażki (`kind` = `'a'`/`'f'`)."""
    await session.execute(
        _INSERT_SQL, {"kind": kind, "ip": ip, "email_key": email_key, "now_ms": now_ms}
    )


async def count_attempts(session: AsyncSession, *, ip: str, email_key: str, since_ms: int) -> int:
    """Liczba prób (`kind='a'`) dla IP+e-mail od `since_ms` (wyłącznie)."""
    result = await session.execute(
        _COUNT_ATTEMPTS_SQL, {"ip": ip, "email_key": email_key, "since_ms": since_ms}
    )
    return int(result.scalar_one())


async def count_failures(session: AsyncSession, *, email_key: str, since_ms: int) -> int:
    """Liczba porażek (`kind='f'`) dla e-maila od `since_ms` (wyłącznie)."""
    result = await session.execute(
        _COUNT_FAILURES_SQL, {"email_key": email_key, "since_ms": since_ms}
    )
    return int(result.scalar_one())


async def delete_failures(session: AsyncSession, *, email_key: str) -> None:
    """Czyści porażki e-maila (udany login znosi blokadę)."""
    await session.execute(_DELETE_FAILURES_SQL, {"email_key": email_key})
