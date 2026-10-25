"""Jednostka pracy — transakcja jako async context manager (kontrakt C2)."""

import contextlib
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@contextlib.asynccontextmanager
async def transaction(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Sesja w transakcji: commit przy wyjściu bez wyjątku, rollback przy wyjątku (leci dalej)."""
    async with sessionmaker() as session, session.begin():
        yield session
