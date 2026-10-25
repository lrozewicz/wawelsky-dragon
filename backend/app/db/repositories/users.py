"""Repozytorium tabeli `users` (kontrakt C5) — Core `text()`, bez commit/rollback."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

# Kolumny dozwolone w update_fields (C5); nazwa spoza zbioru → ValueError.
USER_COLUMNS_UPDATABLE = frozenset(
    {
        "nickname",
        "password_hash",
        "auth_source",
        "oidc_sub",
        "is_superuser",
        "is_active",
        "language",
        "timezone",
        "avatar",
        "last_login_time",
    }
)

_SELECT = (
    "SELECT id, email, nickname, password_hash, auth_source, oidc_sub, is_superuser,"
    " is_active, is_service, language, timezone, avatar, last_login_time, token_version,"
    " create_time, update_time FROM users"
)


@dataclass(frozen=True)
class UserRow:
    """Wiersz `users`; flagi TINYINT(1) konwertowane jawnie na bool (C5)."""

    id: str
    email: str
    nickname: str
    password_hash: str | None
    auth_source: str
    oidc_sub: str | None
    is_superuser: bool
    is_active: bool
    is_service: bool
    language: str
    timezone: str | None
    avatar: str | None
    last_login_time: int | None
    token_version: int
    create_time: int
    update_time: int


def _row(row: RowMapping) -> UserRow:
    """RowMapping → UserRow; TINYINT(1) konwertowane jawnie na bool."""
    return UserRow(
        id=row["id"],
        email=row["email"],
        nickname=row["nickname"],
        password_hash=row["password_hash"],
        auth_source=row["auth_source"],
        oidc_sub=row["oidc_sub"],
        is_superuser=bool(row["is_superuser"]),
        is_active=bool(row["is_active"]),
        is_service=bool(row["is_service"]),
        language=row["language"],
        timezone=row["timezone"],
        avatar=row["avatar"],
        last_login_time=row["last_login_time"],
        token_version=row["token_version"],
        create_time=row["create_time"],
        update_time=row["update_time"],
    )


async def get_by_id(session: AsyncSession, user_id: str) -> UserRow | None:
    """Użytkownik po identyfikatorze; None gdy brak."""
    result = await session.execute(text(f"{_SELECT} WHERE id = :user_id"), {"user_id": user_id})
    found = result.mappings().first()
    return _row(found) if found is not None else None


async def get_by_email(session: AsyncSession, email: str) -> UserRow | None:
    """Użytkownik po e-mailu; lookup zawsze lowercase (zapis też w lowercase, C5)."""
    result = await session.execute(
        text(f"{_SELECT} WHERE email = :email"), {"email": email.lower()}
    )
    found = result.mappings().first()
    return _row(found) if found is not None else None


async def list_all(session: AsyncSession) -> list[UserRow]:
    """Wszyscy użytkownicy (także `is_service`) w kolejności create_time, id (C4)."""
    result = await session.execute(text(f"{_SELECT} ORDER BY create_time, id"))
    return [_row(row) for row in result.mappings().all()]


def _like_pattern(value: str) -> str:
    """Wzorzec LIKE ``%value%`` z escapowaniem ``\\``, ``%`` i ``_`` (kontrakt E3-6a §4)."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def list_page(
    session: AsyncSession,
    *,
    q: str | None,
    email: str | None,
    limit: int,
    offset: int,
) -> tuple[list[UserRow], int]:
    """Strona kont bez `is_service` wg filtrów `q` (LIKE e-mail/nickname) i `email` (C4).

    Zwraca ``(wiersze bieżącej strony, łączna liczba dopasowań)``; kolejność ``create_time, id``.
    """
    conditions = ["is_service = 0"]
    params: dict[str, object] = {}
    if email:
        conditions.append("LOWER(email) = LOWER(:email)")
        params["email"] = email
    if q:
        conditions.append(r"(email LIKE :q ESCAPE '\\' OR nickname LIKE :q ESCAPE '\\')")
        params["q"] = _like_pattern(q)
    where = " AND ".join(conditions)
    total_result = await session.execute(
        text(f"SELECT COUNT(*) FROM users WHERE {where}"),  # noqa: S608
        params,
    )
    total = cast(int, total_result.scalar_one())
    result = await session.execute(
        text(f"{_SELECT} WHERE {where} ORDER BY create_time, id LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    )
    return [_row(row) for row in result.mappings().all()], total


async def get_by_oidc_sub(session: AsyncSession, sub: str) -> UserRow | None:
    """Użytkownik po identyfikatorze OIDC (uq_users_oidc_sub); None gdy brak."""
    result = await session.execute(text(f"{_SELECT} WHERE oidc_sub = :sub"), {"sub": sub})
    found = result.mappings().first()
    return _row(found) if found is not None else None


async def insert(  # noqa: PLR0913 — sygnatura z kontraktu C5
    session: AsyncSession,
    *,
    user_id: str,
    email: str,
    nickname: str,
    password_hash: str | None,
    auth_source: str,
    oidc_sub: str | None,
    is_superuser: bool,
    is_service: bool,
    now_ms: int,
) -> None:
    """Wstawia użytkownika; email zapisywany lowercase; create_time = update_time = now_ms."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(
            "INSERT INTO users (id, email, nickname, password_hash, auth_source, oidc_sub,"
            " is_superuser, is_service, create_time, create_date, update_time, update_date)"
            " VALUES (:id, :email, :nickname, :password_hash, :auth_source, :oidc_sub,"
            " :is_superuser, :is_service, :now_ms, :date, :now_ms, :date)"
        ),
        {
            "id": user_id,
            "email": email.lower(),
            "nickname": nickname,
            "password_hash": password_hash,
            "auth_source": auth_source,
            "oidc_sub": oidc_sub,
            "is_superuser": is_superuser,
            "is_service": is_service,
            "now_ms": now_ms,
            "date": date,
        },
    )


async def update_fields(
    session: AsyncSession, user_id: str, fields: Mapping[str, object], now_ms: int
) -> None:
    """Aktualizuje kolumny z USER_COLUMNS_UPDATABLE + update_time/update_date (C5)."""
    for name in fields:
        if name not in USER_COLUMNS_UPDATABLE:
            raise ValueError(f"column not updatable: {name}")
    date = from_ms(now_ms).replace(tzinfo=None)
    # Nazwy kolumn pochodzą z USER_COLUMNS_UPDATABLE (sprawdzone wyżej), wartości wiązane.
    assignments = ", ".join(f"{column} = :{column}" for column in fields)
    await session.execute(
        text(
            f"UPDATE users SET {assignments + ', ' if assignments else ''}"  # noqa: S608
            "update_time = :now_ms, update_date = :date WHERE id = :user_id"
        ),
        {"user_id": user_id, "now_ms": now_ms, "date": date, **fields},
    )


async def bump_token_version(session: AsyncSession, user_id: str, now_ms: int) -> None:
    """Zwiększa token_version o 1 (unieważnienie tokenów JWT); ustawia update_time/date."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(
            "UPDATE users SET token_version = token_version + 1,"
            " update_time = :now_ms, update_date = :date WHERE id = :user_id"
        ),
        {"user_id": user_id, "now_ms": now_ms, "date": date},
    )


async def count_active_superusers(session: AsyncSession) -> int:
    """Liczba aktywnych superuserów (straż „ostatni admin” w usługach, C6)."""
    result = await session.execute(
        text("SELECT COUNT(*) FROM users WHERE is_superuser = 1 AND is_active = 1")
    )
    return cast(int, result.scalar_one())


async def find_transfer_target(session: AsyncSession, exclude_user_id: str) -> UserRow | None:
    """Cel transferu zasobów (C4): najpierw konto serwisowe, dalej najstarszy admin.

    Kolejność `create_time, id`; usuwane konto `exclude_user_id` jest pomijane.
    """
    for condition in ("is_active = 1 AND is_service = 1", "is_active = 1 AND is_superuser = 1"):
        result = await session.execute(
            text(
                f"{_SELECT} WHERE id != :exclude AND {condition} ORDER BY create_time, id LIMIT 1"
            ),
            {"exclude": exclude_user_id},
        )
        found = result.mappings().first()
        if found is not None:
            return _row(found)
    return None


async def delete(session: AsyncSession, user_id: str) -> None:
    """Usuwa konto; klucze API i sesje odświeżania znikają przez FK CASCADE (C4)."""
    await session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
