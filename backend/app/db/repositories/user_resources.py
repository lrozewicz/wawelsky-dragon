"""Repozytorium zasobów użytkownika (kontrakt C4) — Core `text()`, bez commit/rollback.

Transfer i kasowanie obejmują wyłącznie zasoby, których właścicielem (`tenant_id`) jest
konto. Bloby w storage nie są tu usuwane (znane ograniczenie E2-4).
"""

from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict

# Tabele zasobów z kolumną tenant_id; kolejność kluczy wyniku `moved` z kontraktu C4.
_RESOURCE_TABLES = ("datasets", "chats", "files")
# Kasowanie w kolejności zgodnej z FK: czaty (zwalniają chat_datasets), potem datasety,
# na końcu pliki (file2document znika przez CASCADE z dokumentami).
_DELETE_ORDER = ("chats", "datasets", "files")
_DUPLICATE_ENTRY = 1062


async def transfer(session: AsyncSession, from_id: str, to_id: str) -> dict[str, int]:
    """Przepisuje zasoby konta na inne konto; kolizja nazwy u celu → Conflict (C4)."""
    moved: dict[str, int] = {}
    try:
        for table in _RESOURCE_TABLES:
            # Nazwa tabeli z _RESOURCE_TABLES (literały w tym pliku), id wiązane.
            result = await session.execute(
                text(f"UPDATE {table} SET tenant_id = :to_id WHERE tenant_id = :from_id"),  # noqa: S608
                {"to_id": to_id, "from_id": from_id},
            )
            moved[table] = cast(CursorResult[Any], result).rowcount
    except IntegrityError as exc:
        if exc.orig is not None and exc.orig.args[0] == _DUPLICATE_ENTRY:
            raise Conflict("Cannot transfer resources: name conflict with target account") from exc
        raise
    return moved


async def delete_all(session: AsyncSession, user_id: str) -> dict[str, int]:
    """Kasuje zasoby konta w kolejności zależności FK; zwraca liczby wierszy (C4)."""
    deleted: dict[str, int] = {}
    for table in _DELETE_ORDER:
        # Nazwa tabeli z _DELETE_ORDER (literały w tym pliku), id wiązane.
        result = await session.execute(
            text(f"DELETE FROM {table} WHERE tenant_id = :user_id"),  # noqa: S608
            {"user_id": user_id},
        )
        deleted[table] = cast(CursorResult[Any], result).rowcount
    return deleted
