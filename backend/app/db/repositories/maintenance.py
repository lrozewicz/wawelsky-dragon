"""Repozytorium serwisowe: lista tabel i pełne czyszczenie schematu (K9 §3 p. 1).

SQL przez ``text()``, bez commit/rollback — commituje ``app.db.uow.transaction``.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_tables(session: AsyncSession) -> list[str]:
    """Nazwy tabel BASE TABLE bieżącej bazy poza ``alembic_version``, alfabetycznie (K9 §3 p. 1)."""
    result = await session.execute(
        text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
            " AND table_name <> 'alembic_version' ORDER BY table_name"
        )
    )
    return [str(row[0]) for row in result]


async def wipe_all(session: AsyncSession) -> list[str]:
    """DELETE FROM każdej tabeli schematu; zwraca listę tabel (K9 §3 p. 1).

    Commit po stronie ``transaction``; schemat i ``alembic_version`` nietknięte.
    """
    tables = await list_tables(session)
    await session.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    for table in tables:
        # Nazwa tabeli nie może być parametrem zapytania (identyfikator SQL, nie wartość);
        # pochodzi z information_schema bieżącej bazy — f-string nie wnosi iniekcji
        # (wzór: tests/integration/conftest.py::fresh_db).
        await session.execute(text(f"DELETE FROM `{table}`"))  # noqa: S608
    await session.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    return tables
