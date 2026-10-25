"""Testy repozytorium ``kb_export_data`` na MariaDB: filtr ``committed=1`` (backlog E7-1a T2).

Chunki ``committed=0`` (ingestia w toku, K2) nie mogą trafić do paczki ``.wdkb.zip`` (K19 §2) —
pilnuje tego warunek w ``_CHUNKS_SQL`` oraz licznik ``_COUNT_CHUNKS_SQL``. Po usunięciu tego
warunku z któregokolwiek zapytania test czerwienieje (sprawdzone mutacją lokalną).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.timeutil import from_ms
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import documents as documents_repo
from app.db.repositories import kb_export_data
from app.db.repositories.chunks import chunk_id
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME_MS, make_document_row, seed_dataset

pytestmark = pytest.mark.db

COMMITTED_CONTENT = "chunk zacommitowany"
UNCOMMITTED_CONTENT = "chunk w toku ingestii"
COMMITTED_CHUNKS = 2
# Ziarno id chunka (xxh64 z „dokument:zadanie:porządek”); tu stałe, jak w innych seedach.
_SEED_TASK_ID = "a" * 32
# (ordinal, treść, committed) — dwa chunki w paczce i dwa poza nią.
_CHUNKS = (
    (0, COMMITTED_CONTENT, True),
    (1, COMMITTED_CONTENT, True),
    (2, UNCOMMITTED_CONTENT, False),
    (3, UNCOMMITTED_CONTENT, False),
)


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


async def _insert_chunk(  # noqa: PLR0913 — pełny wiersz chunka seedu
    sm: async_sessionmaker[AsyncSession],
    *,
    dataset_id: str,
    document_id: str,
    ordinal: int,
    content: str,
    committed: bool,
) -> None:
    """Wstawia chunk z jawnym ``committed`` (surowy SQL — ingestia trzyma ``0`` do commitu)."""
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type, content,"
                " content_ft, committed, available, create_time, create_date, update_time,"
                " update_date)"
                " VALUES (:id, :doc, :ds, :ordinal, 'text', :content, :content, :committed, 1,"
                " :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": chunk_id(document_id, _SEED_TASK_ID, ordinal),
                "doc": document_id,
                "ds": dataset_id,
                "ordinal": ordinal,
                "content": content,
                "committed": 1 if committed else 0,
                "time_ms": TIME_MS,
                "time": from_ms(TIME_MS).replace(tzinfo=None),
            },
        )


async def test_export_reads_only_committed_chunks(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """``iter_chunks`` i ``count_chunks`` widzą wyłącznie ``committed=1`` (K19 §2)."""
    dataset = await seed_dataset(sm)
    document = make_document_row(dataset)
    async with transaction(sm) as session:
        await documents_repo.insert(session, document)
    for ordinal, content, committed in _CHUNKS:
        await _insert_chunk(
            sm,
            dataset_id=dataset.id,
            document_id=document.id,
            ordinal=ordinal,
            content=content,
            committed=committed,
        )

    async with transaction(sm) as session:
        batches = [batch async for batch in kb_export_data.iter_chunks(session, dataset.id)]
        counted = await kb_export_data.count_chunks(session, dataset.id)

    # Kolejność keyset ``(document_id, ordinal)`` — tylko chunki zacommitowane.
    assert [[str(row["content"]) for row in batch] for batch in batches] == [
        [COMMITTED_CONTENT, COMMITTED_CONTENT]
    ]
    assert counted == COMMITTED_CHUNKS
