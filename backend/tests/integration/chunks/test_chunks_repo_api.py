"""Testy repozytorium chunków dla API na prawdziwej MariaDB (brief T3a, kontrakt C3.1)."""

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import chunk_vectors as chunk_vectors_repo
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.chunks import ChunkInsert
from app.db.repositories.datasets import DatasetRow
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME_MS, _chunk, _insert_document, seed_dataset

pytestmark = pytest.mark.db

NOW_MS = TIME_MS + 1000  # czas „późniejszy” niż seed — dla update_* i recount
TEST_DIM = 1024  # migracja tworzy tylko d1536/d3072; d1024 tworzy test przez ensure_table


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head (wzór: tests/integration/ingest/conftest.py)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose (wzór: ingest conftest)."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


def _task_chunks(document_id: str, dataset_id: str, task_id: int, ordinals: list[int]) -> list:
    """ChunkInsert-y jednego zadania w podanych porządkach."""
    return [_chunk(document_id, dataset_id, task_id, o) for o in ordinals]


async def _seed_doc_chunks(
    sm: async_sessionmaker[AsyncSession], *, uncommitted: bool = True
) -> tuple[DatasetRow, DocumentRow, list[ChunkInsert], list[ChunkInsert]]:
    """Dataset + dokument + 3 chunki committed (ordinal 0,1,2) [+1 niezacommitowany (3)].

    Chunk ordinal 0: puste keywords i NULL positions; ordinal 1: treść „smok…”.
    """
    ds = await seed_dataset(sm)
    doc = await _insert_document(sm, ds, name="umowa.txt")
    committed = _task_chunks(doc.id, ds.id, 501, [0, 1, 2])
    committed[0] = replace(committed[0], keywords=(), positions=())
    committed[1] = replace(committed[1], content="smok wawelski")
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, committed, now_ms=TIME_MS)
        await chunks_repo.commit_task(session, doc.id, 501, now_ms=TIME_MS)
    extra = _task_chunks(doc.id, ds.id, 502, [3])
    if uncommitted:
        async with transaction(sm) as session:
            await chunks_repo.insert_many(session, extra, now_ms=TIME_MS)
    return ds, doc, committed, extra


async def test_list_pagination_document_name_and_null_positions(sm) -> None:
    """limit=2 → ordinal 0,1; total=3; document_name z JOIN; NULL positions → [] (brief T3a)."""
    _, doc, _, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        records, total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=None, offset=0, limit=2
        )
    assert total == 3  # noqa: PLR2004 — 3 committed chunki z seeda
    assert [r.ordinal for r in records] == [0, 1]
    assert all(r.document_name == "umowa.txt" for r in records)
    assert records[0].positions == []
    assert records[1].positions == [[0, 1, 1, 2, 3]]


async def test_list_offset_page(sm) -> None:
    """offset=2, limit=30 → 1 rekord (ordinal 2), total=3 (brief T3a)."""
    _, doc, _, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        records, total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=None, offset=2, limit=30
        )
    assert total == 3  # noqa: PLR2004 — 3 committed chunki z seeda
    assert [r.ordinal for r in records] == [2]


async def test_list_keywords_filter(sm) -> None:
    """keywords='smok' → 1 rekord (treść ordinal 1), total=1 (brief T3a)."""
    _, doc, committed, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        records, total = await chunks_repo.list_for_document(
            session, doc.id, keywords="smok", chunk_id=None, offset=0, limit=30
        )
    assert total == 1
    assert [r.id for r in records] == [committed[1].id]


async def test_list_chunk_id_filter(sm) -> None:
    """chunk_id=<id2> → 1 rekord o tym identyfikatorze (brief T3a)."""
    _, doc, committed, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        records, total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=committed[2].id, offset=0, limit=30
        )
    assert total == 1
    assert [r.id for r in records] == [committed[2].id]


async def test_list_without_available_filter_returns_all(sm) -> None:
    """available=None → wszystkie 3 committed (także wyłączony) — brak zmiany zachowania (C2)."""
    _, doc, committed, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        await chunks_repo.set_available(session, doc.id, [committed[2].id], False, now_ms=NOW_MS)
    async with transaction(sm) as session:
        records, total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=None, available=None, offset=0, limit=30
        )
    assert total == 3  # noqa: PLR2004 — 3 committed chunki z seeda
    assert [r.ordinal for r in records] == [0, 1, 2]


async def test_list_available_filter(sm) -> None:
    """Wszystkie 3 domyślnie dostępne: available=True → 3, available=False → 0 (C2)."""
    _, doc, _, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        enabled, enabled_total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=None, available=True, offset=0, limit=30
        )
        disabled, disabled_total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=None, available=False, offset=0, limit=30
        )
    assert enabled_total == 3  # noqa: PLR2004 — 3 committed chunki z seeda
    assert [r.ordinal for r in enabled] == [0, 1, 2]
    assert (disabled, disabled_total) == ([], 0)


async def test_list_available_filter_with_pagination(sm) -> None:
    """Jeden wyłączony: total z filtrem (2), strona limit=1 → 1 rekord (C2)."""
    _, doc, committed, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        await chunks_repo.set_available(session, doc.id, [committed[2].id], False, now_ms=NOW_MS)
    async with transaction(sm) as session:
        records, total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=None, available=True, offset=0, limit=1
        )
        off_records, off_total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=None, available=False, offset=0, limit=30
        )
    assert total == 2  # noqa: PLR2004 — jeden z trzech wyłączony
    assert [r.ordinal for r in records] == [0]
    assert off_total == 1
    assert [r.id for r in off_records] == [committed[2].id]


async def test_list_zero_limit_counts_total(sm) -> None:
    """limit=0 → ([], 3) (brief T3a)."""
    _, doc, _, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        records, total = await chunks_repo.list_for_document(
            session, doc.id, keywords=None, chunk_id=None, offset=0, limit=0
        )
    assert (records, total) == ([], 3)


async def test_get_record_skips_uncommitted(sm) -> None:
    """get_record(niezacommitowany) → None; committed → available=True, keywords=[] (brief T3a)."""
    _, _, committed, extra = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        assert await chunks_repo.get_record(session, extra[0].id) is None
        record = await chunks_repo.get_record(session, committed[0].id)
    assert record is not None
    assert record.available is True
    assert record.keywords == []


async def test_max_ordinal_counts_uncommitted_too(sm) -> None:
    """3 committed → 2; po dodaniu niezacommitowanego ordinal 3 → 3 (brief T3a)."""
    _, doc, _, extra = await _seed_doc_chunks(sm, uncommitted=False)
    async with transaction(sm) as session:
        assert await chunks_repo.max_ordinal(session, doc.id) == 2  # noqa: PLR2004 — ordinały 0..2
        await chunks_repo.insert_many(session, extra, now_ms=TIME_MS)
        assert await chunks_repo.max_ordinal(session, doc.id) == 3  # noqa: PLR2004 — ordinal 3
        await chunks_repo.delete_uncommitted_by_task(session, 502)


async def test_max_ordinal_empty_document(sm) -> None:
    """max_ordinal dokumentu bez chunków → -1 (brief T3a)."""
    ds = await seed_dataset(sm)
    doc = await _insert_document(sm, ds, name="pusty.txt")
    async with transaction(sm) as session:
        assert await chunks_repo.max_ordinal(session, doc.id) == -1


async def test_insert_manual_commits_without_task(sm) -> None:
    """insert_manual: committed=1, task_id NULL w bazie (row.task_id ignorowane) (brief T3a)."""
    ds, doc, _, _ = await _seed_doc_chunks(sm)
    row = replace(_chunk(doc.id, ds.id, 0, 5), task_id=0)
    async with transaction(sm) as session:
        await chunks_repo.insert_manual(session, row, now_ms=TIME_MS)
        record = await chunks_repo.get_record(session, row.id)
        raw = (
            await session.execute(
                text("SELECT task_id, committed FROM chunks WHERE id = :id"), {"id": row.id}
            )
        ).one()
    assert record is not None and record.ordinal == 5  # noqa: PLR2004 — ordinal 5 z briefu
    assert raw.task_id is None and raw.committed == 1


async def test_update_content_updates_allowed_fields(sm) -> None:
    """update_content: content/keywords/available; update_time = now_ms (brief T3a)."""
    _, _, committed, _ = await _seed_doc_chunks(sm)
    target = committed[0].id
    async with transaction(sm) as session:
        await chunks_repo.update_content(
            session, target, {"content": "x", "keywords": ["a"], "available": False}, now_ms=NOW_MS
        )
        record = await chunks_repo.get_record(session, target)
    assert record is not None
    assert record.content == "x" and record.keywords == ["a"] and record.available is False
    assert record.update_time == NOW_MS


async def test_update_content_empty_fields_touches_time_only(sm) -> None:
    """update_content z pustym fields → tylko update_time/update_date (wymaganie 5)."""
    _, _, committed, _ = await _seed_doc_chunks(sm)
    target = committed[0].id
    async with transaction(sm) as session:
        await chunks_repo.update_content(session, target, {}, now_ms=NOW_MS)
        record = await chunks_repo.get_record(session, target)
    assert record is not None
    assert record.content == "treść 0" and record.update_time == NOW_MS


async def test_update_content_json_and_tags_roundtrip(sm) -> None:
    """update_content: tags i positions przez json.dumps → listy po odczycie (wymaganie 5)."""
    _, _, committed, _ = await _seed_doc_chunks(sm)
    target = committed[2].id
    async with transaction(sm) as session:
        await chunks_repo.update_content(
            session, target, {"tags": ["t1"], "positions": [[1, 2, 3, 4, 5]]}, now_ms=NOW_MS
        )
        record = await chunks_repo.get_record(session, target)
    assert record is not None
    assert record.tags == ["t1"] and record.positions == [[1, 2, 3, 4, 5]]


async def test_update_content_rejects_unknown_column(sm) -> None:
    """update_content: kolumna spoza białej listy → ValueError (brief T3a)."""
    _, _, committed, _ = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        with pytest.raises(ValueError, match="column not allowed: ordinal"):
            await chunks_repo.update_content(
                session, committed[0].id, {"ordinal": 1}, now_ms=NOW_MS
            )


async def test_set_available_switches_selected(sm) -> None:
    """set_available([id0, id1], False) → 2; oba False; trzeci bez zmian; [] → 0 (brief T3a)."""
    _, doc, committed, _ = await _seed_doc_chunks(sm, uncommitted=False)
    ids = [committed[0].id, committed[1].id]
    async with transaction(sm) as session:
        changed = await chunks_repo.set_available(session, doc.id, ids, False, now_ms=NOW_MS)
        assert changed == 2  # noqa: PLR2004 — dwa chunki w ids
        assert await chunks_repo.set_available(session, doc.id, [], True, now_ms=NOW_MS) == 0
        first = await chunks_repo.get_record(session, committed[0].id)
        third = await chunks_repo.get_record(session, committed[2].id)
    assert first is not None and first.available is False
    assert third is not None and third.available is True


async def test_delete_removes_selected_all_and_vectors_cascade(sm) -> None:
    """delete([id0]) → 1 i kasuje wektor (FK CASCADE); delete(None) → reszta; [] → 0 (brief T3a)."""
    ds, doc, committed, extra = await _seed_doc_chunks(sm)
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, TEST_DIM)
    async with transaction(sm) as session:
        await chunk_vectors_repo.upsert(session, TEST_DIM, committed[0].id, ds.id, [0.1] * TEST_DIM)
    async with transaction(sm) as session:
        assert await chunks_repo.delete(session, doc.id, [committed[0].id]) == 1
        assert await chunks_repo.delete(session, doc.id, []) == 0
    async with transaction(sm) as session:
        vectors = (
            await session.execute(
                text("SELECT COUNT(*) FROM chunk_vec_d1024 WHERE chunk_id = :id"),
                {"id": committed[0].id},
            )
        ).scalar_one()
    assert vectors == 0
    async with transaction(sm) as session:
        assert await chunks_repo.delete(session, doc.id, None) == 3  # noqa: PLR2004 — reszta: 2+1
        left = (
            await session.execute(
                text("SELECT COUNT(*) FROM chunks WHERE document_id = :id"), {"id": doc.id}
            )
        ).scalar_one()
    assert left == 0 and len(extra) == 1  # niezacommitowany też usunięty (delete bez filtra)


async def test_recount_document_updates_counters_only(sm) -> None:
    """recount_document: chunk_count=2, token_count=15; run/progress bez zmian (brief T3a)."""
    ds = await seed_dataset(sm)
    doc = await _insert_document(sm, ds, name="licz.txt")
    rows = [
        replace(_chunk(doc.id, ds.id, 601, 0), token_count=10),
        replace(_chunk(doc.id, ds.id, 601, 1), token_count=5),
    ]
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, rows, now_ms=TIME_MS)
        await chunks_repo.commit_task(session, doc.id, 601, now_ms=TIME_MS)
        await chunks_repo.recount_document(session, doc.id, now_ms=NOW_MS)
        document = await documents_repo.get(session, doc.id)
    assert document is not None
    assert (document.chunk_count, document.token_count) == (2, 15)
    assert document.run == "0" and document.progress == 0.0 and document.update_time == NOW_MS


async def test_upsert_is_idempotent(sm) -> None:
    """upsert dwa razy (drugie [0.2]*dim) → 1 wiersz w chunk_vec_d1024 (brief T3a)."""
    ds, _, committed, _ = await _seed_doc_chunks(sm, uncommitted=False)
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, TEST_DIM)
    async with transaction(sm) as session:
        await chunk_vectors_repo.upsert(session, TEST_DIM, committed[0].id, ds.id, [0.1] * TEST_DIM)
        await chunk_vectors_repo.upsert(session, TEST_DIM, committed[0].id, ds.id, [0.2] * TEST_DIM)
        count = (
            await session.execute(
                text("SELECT COUNT(*) FROM chunk_vec_d1024 WHERE chunk_id = :id"),
                {"id": committed[0].id},
            )
        ).scalar_one()
    assert count == 1
