"""Repozytorium tabeli `assistant_access` (kontrakt C2) — Core `text()`, bez commit/rollback.

E-mail jest zawsze normalizowany do lowercase wewnątrz repozytorium (kontrakt C2).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AccessRow:
    """Wiersz `assistant_access` widziany przez usługę dostępu (C2)."""

    chat_id: str
    created_by: str | None
    created_at: int


def _row(row: RowMapping) -> AccessRow:
    """RowMapping → AccessRow."""
    return AccessRow(
        chat_id=row["chat_id"], created_by=row["created_by"], created_at=int(row["created_at"])
    )


async def list_for_email(session: AsyncSession, email: str) -> list[AccessRow]:
    """Granty e-maila, kolejność `created_at, chat_id` (C2)."""
    result = await session.execute(
        text(
            "SELECT chat_id, created_by, created_at FROM assistant_access"
            " WHERE email = :email ORDER BY created_at, chat_id"
        ),
        {"email": email.lower()},
    )
    return [_row(row) for row in result.mappings()]


async def chat_ids_for_email(session: AsyncSession, email: str) -> frozenset[str]:
    """Zbiór identyfikatorów czatów przyznanych e-mailowi (C2)."""
    result = await session.execute(
        text(
            "SELECT chat_id FROM assistant_access WHERE email = :email ORDER BY created_at, chat_id"
        ),
        {"email": email.lower()},
    )
    return frozenset(result.scalars())


async def emails_for_chat(session: AsyncSession, chat_id: str) -> frozenset[str]:
    """Zbiór e-maili mających grant do czatu (C2)."""
    result = await session.execute(
        text("SELECT email FROM assistant_access WHERE chat_id = :chat_id"),
        {"chat_id": chat_id},
    )
    return frozenset(result.scalars())


async def existing_chat_ids(session: AsyncSession, chat_ids: Sequence[str]) -> frozenset[str]:
    """Podzbiór id istniejący w `chats`; pusty wejściowy → frozenset() (C2)."""
    if not chat_ids:
        return frozenset()
    stmt = text("SELECT id FROM chats WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    result = await session.execute(stmt, {"ids": list(chat_ids)})
    return frozenset(result.scalars())


async def delete_for_email(session: AsyncSession, email: str) -> int:
    """Usuwa wszystkie granty e-maila; zwraca rowcount (C2)."""
    result = await session.execute(
        text("DELETE FROM assistant_access WHERE email = :email"), {"email": email.lower()}
    )
    return cast(CursorResult[Any], result).rowcount


async def insert_many(
    session: AsyncSession,
    email: str,
    chat_ids: Sequence[str],
    created_by: str | None,
    now_ms: int,
) -> None:
    """Wstawia zwykłym INSERT-em po jednym wierszu na czat (dla `replace`, C2)."""
    if not chat_ids:
        return
    lowered = email.lower()
    await session.execute(
        text(
            "INSERT INTO assistant_access (email, chat_id, created_by, created_at)"
            " VALUES (:email, :chat_id, :created_by, :now_ms)"
        ),
        [
            {"email": lowered, "chat_id": chat_id, "created_by": created_by, "now_ms": now_ms}
            for chat_id in chat_ids
        ],
    )


async def insert_ignore(
    session: AsyncSession,
    email: str,
    chat_id: str,
    created_by: str | None,
    now_ms: int,
) -> None:
    """INSERT IGNORE — istniejący wiersz zostaje bez zmian (dla `grant`, C2)."""
    await session.execute(
        text(
            "INSERT IGNORE INTO assistant_access (email, chat_id, created_by, created_at)"
            " VALUES (:email, :chat_id, :created_by, :now_ms)"
        ),
        {
            "email": email.lower(),
            "chat_id": chat_id,
            "created_by": created_by,
            "now_ms": now_ms,
        },
    )


async def delete_one(session: AsyncSession, email: str, chat_id: str) -> int:
    """Usuwa pojedynczy grant; zwraca rowcount (C2)."""
    result = await session.execute(
        text("DELETE FROM assistant_access WHERE email = :email AND chat_id = :chat_id"),
        {"email": email.lower(), "chat_id": chat_id},
    )
    return cast(CursorResult[Any], result).rowcount
