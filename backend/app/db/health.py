"""Sprawdzenie gotowości bazy (kontrakt C5): None = gotowa, inaczej przyczyna dla 503."""

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.schema import SCHEMA_HEAD


async def check_ready(engine: AsyncEngine) -> str | None:
    """SELECT 1 + odczyt alembic_version w jednym połączeniu, w limicie 3 s."""
    try:
        async with asyncio.timeout(3.0):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                try:
                    row = (
                        await conn.execute(text("SELECT version_num FROM alembic_version"))
                    ).first()
                except ProgrammingError:
                    # Brak tabeli alembic_version — migracje jeszcze nie przeszły.
                    return f"schema not migrated (expected {SCHEMA_HEAD})"
    except (OperationalError, InterfaceError, OSError, TimeoutError):
        return "database unavailable"
    if row is None:
        return f"schema not migrated (expected {SCHEMA_HEAD})"
    version = str(row[0])
    if version != SCHEMA_HEAD:
        return f"schema version {version} != expected {SCHEMA_HEAD}"
    return None
