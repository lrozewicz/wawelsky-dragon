"""Repozytorium tabeli `wd_settings` (CONTRACT E7-1f §5 / DEC-320).

K19 §5 zakłada tabelę `settings`, której w schemacie WD nie ma — migracja 0009 tworzy
`wd_settings`. Dziś jedyny klucz to `instance_id` (32 znaki hex): generowany przy pierwszym
użyciu, potem tylko odczytywany. SQL przez ``text()``, bez ``commit``/``rollback`` —
transakcję otwiera ``app.db.uow.transaction``.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

INSTANCE_ID_KEY = "instance_id"

# `INSERT IGNORE` + `SELECT` w jednej transakcji: równoległe pierwsze wywołania nie wywalają się
# na unikacie, a przegrany wyścigu odczytuje wiersz zwycięzcy (CONTRACT §5).
_INSERT_IGNORE_SQL = text(
    "INSERT IGNORE INTO wd_settings (name, value, update_time) VALUES (:name, :value, :now_ms)"
)

_SELECT_SQL = text("SELECT value FROM wd_settings WHERE name = :name")


async def get_or_create_instance_id(session: AsyncSession, *, new_id: str, now_ms: int) -> str:
    """Zwraca `instance_id` instancji; przy pierwszym użyciu wstawia `new_id` (§5).

    Kształt `new_id` nie jest walidowany — generuje go wołający.
    """
    await session.execute(
        _INSERT_IGNORE_SQL, {"name": INSTANCE_ID_KEY, "value": new_id, "now_ms": now_ms}
    )
    return str((await session.execute(_SELECT_SQL, {"name": INSTANCE_ID_KEY})).scalar_one())


_UPSERT_SQL = text(
    "INSERT INTO wd_settings (name, value, update_time) VALUES (:name, :value, :now_ms)"
    " ON DUPLICATE KEY UPDATE value = VALUES(value), update_time = VALUES(update_time)"
)

_DELETE_SQL = text("DELETE FROM wd_settings WHERE name = :name")


async def get_value(session: AsyncSession, name: str) -> str | None:
    """Wartość ustawienia `name` albo None."""
    return (await session.execute(_SELECT_SQL, {"name": name})).scalar_one_or_none()


async def set_value(session: AsyncSession, name: str, value: str, *, now_ms: int) -> None:
    """Zapisuje (nadpisuje) ustawienie `name`."""
    await session.execute(_UPSERT_SQL, {"name": name, "value": value, "now_ms": now_ms})


async def delete_value(session: AsyncSession, name: str) -> None:
    """Usuwa ustawienie `name` (brak wiersza nie jest błędem)."""
    await session.execute(_DELETE_SQL, {"name": name})
