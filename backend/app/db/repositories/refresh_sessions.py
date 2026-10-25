"""Repozytorium tabeli `refresh_sessions` (kontrakt C5) — Core `text()`, bez commit/rollback."""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_SELECT = "SELECT id, user_id, token_hash, family_id, expires_at, revoked_at FROM refresh_sessions"


@dataclass(frozen=True)
class RefreshSessionRow:
    """Wiersz `refresh_sessions` (dane sesji; user_agent/ip tylko w bazie, C5)."""

    id: str
    user_id: str
    token_hash: str
    family_id: str
    expires_at: int
    revoked_at: int | None


def _row(row: RowMapping) -> RefreshSessionRow:
    """RowMapping → RefreshSessionRow."""
    return RefreshSessionRow(
        id=row["id"],
        user_id=row["user_id"],
        token_hash=row["token_hash"],
        family_id=row["family_id"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
    )


async def insert(  # noqa: PLR0913 — sygnatura z kontraktu C5
    session: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    token_hash: str,
    family_id: str,
    expires_at: int,
    user_agent: str | None,
    ip: str | None,
    now_ms: int,
) -> None:
    """Wstawia sesję; user_agent przycięty do 255, ip do 45 znaków (LIMIT kolumn)."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(
            "INSERT INTO refresh_sessions (id, user_id, token_hash, family_id, expires_at,"
            " user_agent, ip, create_time, create_date, update_time, update_date)"
            " VALUES (:id, :user_id, :token_hash, :family_id, :expires_at,"
            " :user_agent, :ip, :now_ms, :date, :now_ms, :date)"
        ),
        {
            "id": session_id,
            "user_id": user_id,
            "token_hash": token_hash,
            "family_id": family_id,
            "expires_at": expires_at,
            "user_agent": user_agent[:255] if user_agent is not None else None,
            "ip": ip[:45] if ip is not None else None,
            "now_ms": now_ms,
            "date": date,
        },
    )


async def get_by_hash(session: AsyncSession, token_hash: str) -> RefreshSessionRow | None:
    """Sesja po hashu tokenu (uq_refresh_sessions_token_hash); None gdy brak."""
    result = await session.execute(
        text(f"{_SELECT} WHERE token_hash = :token_hash"), {"token_hash": token_hash}
    )
    found = result.mappings().first()
    return _row(found) if found is not None else None


async def revoke(session: AsyncSession, session_id: str, now_ms: int) -> int:
    """Unieważnia sesję tylko gdy aktywna; zwraca liczbę zmienionych wierszy
    (0 = już unieważniona / brak)."""
    date = from_ms(now_ms).replace(tzinfo=None)
    result = await session.execute(
        text(
            "UPDATE refresh_sessions SET revoked_at = :now_ms,"
            " update_time = :now_ms, update_date = :date"
            " WHERE id = :id AND revoked_at IS NULL"
        ),
        {"id": session_id, "now_ms": now_ms, "date": date},
    )
    return cast("CursorResult[Any]", result).rowcount


async def revoke_family(session: AsyncSession, family_id: str, now_ms: int) -> int:
    """Unieważnia wszystkie aktywne sesje rodziny; zwraca liczbę zmienionych."""
    date = from_ms(now_ms).replace(tzinfo=None)
    result = await session.execute(
        text(
            "UPDATE refresh_sessions SET revoked_at = :now_ms,"
            " update_time = :now_ms, update_date = :date"
            " WHERE family_id = :family_id AND revoked_at IS NULL"
        ),
        {"family_id": family_id, "now_ms": now_ms, "date": date},
    )
    return cast("CursorResult[Any]", result).rowcount


async def revoke_all_for_user(session: AsyncSession, user_id: str, now_ms: int) -> int:
    """Unieważnia wszystkie aktywne sesje użytkownika; zwraca liczbę zmienionych."""
    date = from_ms(now_ms).replace(tzinfo=None)
    result = await session.execute(
        text(
            "UPDATE refresh_sessions SET revoked_at = :now_ms,"
            " update_time = :now_ms, update_date = :date"
            " WHERE user_id = :user_id AND revoked_at IS NULL"
        ),
        {"user_id": user_id, "now_ms": now_ms, "date": date},
    )
    return cast("CursorResult[Any]", result).rowcount
