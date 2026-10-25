"""Repozytorium tabeli `api_keys` (kontrakt C5) — Core `text()`, bez commit/rollback."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_SELECT = (
    "SELECT id, user_id, token_hash, token_enc, prefix, name, dialog_id, source,"
    " compat_profile, last_used_at, expires_at, revoked_at, create_time, update_time FROM api_keys"
)


@dataclass(frozen=True)
class ApiKeyRow:
    """Wiersz `api_keys`; token_enc jako bytes (VARBINARY)."""

    id: str
    user_id: str
    token_hash: str
    token_enc: bytes
    prefix: str
    name: str | None
    dialog_id: str | None
    source: str | None
    compat_profile: str | None
    last_used_at: int | None
    expires_at: int | None
    revoked_at: int | None
    create_time: int
    update_time: int


def _row(row: RowMapping) -> ApiKeyRow:
    """RowMapping → ApiKeyRow."""
    return ApiKeyRow(
        id=row["id"],
        user_id=row["user_id"],
        token_hash=row["token_hash"],
        token_enc=row["token_enc"],
        prefix=row["prefix"],
        name=row["name"],
        dialog_id=row["dialog_id"],
        source=row["source"],
        compat_profile=row["compat_profile"],
        last_used_at=row["last_used_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        create_time=row["create_time"],
        update_time=row["update_time"],
    )


async def insert(  # noqa: PLR0913 — sygnatura z kontraktu C5
    session: AsyncSession,
    *,
    key_id: str,
    user_id: str,
    token_hash: str,
    token_enc: bytes,
    prefix: str,
    name: str | None,
    now_ms: int,
    compat_profile: str | None = None,
    expires_at: int | None = None,
) -> None:
    """Wstawia klucz API; dialog_id/source/last_used_at/revoked_at zostają NULL.

    `compat_profile` (C5) trafia do kolumny, gdy podany; domyślnie NULL.
    `expires_at` (K14 §1) to BIGINT ms UTC albo NULL (klucz bezterminowy).
    """
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(
            "INSERT INTO api_keys (id, user_id, token_hash, token_enc, prefix, name,"
            " compat_profile, expires_at, create_time, create_date, update_time, update_date)"
            " VALUES (:id, :user_id, :token_hash, :token_enc, :prefix, :name, :compat_profile,"
            " :expires_at, :now_ms, :date, :now_ms, :date)"
        ),
        {
            "id": key_id,
            "user_id": user_id,
            "token_hash": token_hash,
            "token_enc": token_enc,
            "prefix": prefix,
            "name": name,
            "compat_profile": compat_profile,
            "expires_at": expires_at,
            "now_ms": now_ms,
            "date": date,
        },
    )


async def get_compat_profile(session: AsyncSession, key_id: str) -> str | None:
    """Profil zgodności klucza (C7); brak wiersza → None."""
    result = await session.execute(
        text("SELECT compat_profile FROM api_keys WHERE id = :id"),
        {"id": key_id},
    )
    return result.scalar_one_or_none()


async def get_active_by_hash(session: AsyncSession, token_hash: str) -> ApiKeyRow | None:
    """Aktywny klucz po hashu tokenu (revoked_at IS NULL); None gdy brak lub unieważniony."""
    result = await session.execute(
        text(f"{_SELECT} WHERE token_hash = :token_hash AND revoked_at IS NULL"),
        {"token_hash": token_hash},
    )
    found = result.mappings().first()
    return _row(found) if found is not None else None


async def list_active_for_user(session: AsyncSession, user_id: str) -> list[ApiKeyRow]:
    """Aktywne klucze użytkownika w kolejności create_time, id (C5)."""
    result = await session.execute(
        text(f"{_SELECT} WHERE user_id = :user_id AND revoked_at IS NULL ORDER BY create_time, id"),
        {"user_id": user_id},
    )
    return [_row(row) for row in result.mappings().all()]


async def find_active_for_user(
    session: AsyncSession,
    user_id: str,
    *,
    token_hash: str | None = None,
    key_id: str | None = None,
    prefix: str | None = None,
) -> list[ApiKeyRow]:
    """Aktywne klucze użytkownika po dokładnie jednym kryterium; inaczej ValueError (C5)."""
    criteria = {"token_hash": token_hash, "id": key_id, "prefix": prefix}
    given = {column: value for column, value in criteria.items() if value}
    if len(given) != 1:
        raise ValueError("exactly one criterion required")
    column, value = next(iter(given.items()))
    result = await session.execute(
        text(
            f"{_SELECT} WHERE user_id = :user_id AND revoked_at IS NULL"
            f" AND {column} = :value ORDER BY create_time, id"
        ),
        {"user_id": user_id, "value": value},
    )
    return [_row(row) for row in result.mappings().all()]


async def revoke(session: AsyncSession, key_id: str, now_ms: int) -> None:
    """Unieważnia klucz tylko gdy aktywny; ustawia update_time/update_date."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(
            "UPDATE api_keys SET revoked_at = :now_ms,"
            " update_time = :now_ms, update_date = :date"
            " WHERE id = :id AND revoked_at IS NULL"
        ),
        {"id": key_id, "now_ms": now_ms, "date": date},
    )


async def touch_last_used(session: AsyncSession, key_id: str, now_ms: int) -> None:
    """Ustawia last_used_at (bez zmiany update_time/update_date — C5/touch)."""
    await session.execute(
        text("UPDATE api_keys SET last_used_at = :now_ms WHERE id = :id"),
        {"id": key_id, "now_ms": now_ms},
    )
