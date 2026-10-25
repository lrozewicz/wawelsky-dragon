"""Prawdziwy deadlock InnoDB (1213) i ponowienie transakcji na MariaDB (brief T6, DEC-088).

Dwie transakcje aktualizują dwa wiersze ``datasets`` w krzyżowej kolejności: każda bierze
najpierw swoją blokadę, czeka na blokadę drugiej, a potem sięga po drugi wiersz — cykl
blokad kończy się deadlockiem, InnoDB cofa jedną z nich (1213). Obie operacje są owinięte
w ``retry_lock_conflicts``: przegrana ponawia całą transakcję od początku i wygrywa.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.uow import transaction
from app.services.ingest_commit import retry_lock_conflicts
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import seed_dataset

pytestmark = pytest.mark.db

_UPDATE = text("UPDATE datasets SET chunk_count = chunk_count + 1 WHERE id = :id")
_SELECT = text("SELECT chunk_count FROM datasets WHERE id = :id")
_PER_ROW = 2  # po dwóch udanych zapisach (wygrana + ponowiona) każdy wiersz ma +2


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def _chunk_count(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> int:
    async with sm() as session:
        value = (await session.execute(_SELECT, {"id": dataset_id})).scalar_one()
    return int(value)


def _crossed_op(  # noqa: PLR0913, PLR0917 — opis kroków testu
    sm: async_sessionmaker[AsyncSession],
    own_id: str,
    other_id: str,
    own_event: asyncio.Event,
    other_event: asyncio.Event,
    attempts: list[int],
):
    """Transakcja: UPDATE ``own_id``, sygnał, czekanie na partnera, UPDATE ``other_id``."""

    async def op() -> None:
        attempts[0] += 1
        async with transaction(sm) as session:
            await session.execute(_UPDATE, {"id": own_id})
            own_event.set()
            await other_event.wait()
            await session.execute(_UPDATE, {"id": other_id})

    return op


async def test_crossed_updates_deadlock_then_retry(sm: async_sessionmaker[AsyncSession]) -> None:
    first = await seed_dataset(sm)
    second = await seed_dataset(sm)
    first_ev, second_ev = asyncio.Event(), asyncio.Event()
    attempts_first, attempts_second = [0], [0]

    await asyncio.gather(
        retry_lock_conflicts(
            _crossed_op(sm, first.id, second.id, first_ev, second_ev, attempts_first)
        ),
        retry_lock_conflicts(
            _crossed_op(sm, second.id, first.id, second_ev, first_ev, attempts_second)
        ),
    )

    # Przegrana transakcja dostała 1213 i ponowiła całość; wygrana wyszła za pierwszym razem.
    assert max(attempts_first[0], attempts_second[0]) > 1
    assert min(attempts_first[0], attempts_second[0]) == 1
    # Po jednym udanym zapisie każdej strony każdy wiersz ma dokładnie +2 (bez podwójnego zapisu).
    assert await _chunk_count(sm, first.id) == _PER_ROW
    assert await _chunk_count(sm, second.id) == _PER_ROW
