"""Testy repozytoriów ingestii na prawdziwej MariaDB (brief T2, kontrakt C2)."""

import json
import re
from dataclasses import replace

import pytest
from sqlalchemy import text

from app.db.repositories import chunk_vectors as chunk_vectors_repo
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.chunks import chunk_id
from app.db.uow import transaction
from tests.integration.ingest.conftest import (
    TIME_MS,
    _chunk,
    _get_document,
    _insert_document,
    _insert_parse_task,
    seed_dataset,
)

pytestmark = pytest.mark.db

_CHUNK_ID_LEN = 16  # xxh64_hexdigest zwraca 16 znaków hex


async def test_get_missing_dataset_returns_none(sm) -> None:
    """datasets.get nieistniejącego → None (brief T2)."""
    async with transaction(sm) as session:
        assert await datasets_repo.get(session, "x" * 32) is None


async def test_recount_sums_document_counters(sm) -> None:
    """recount: document_count=2, chunk_count=7, token_num=30 (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds, name="a.txt")
    b = await _insert_document(sm, ds, name="b.txt")
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE documents SET chunk_count = 3, token_count = 10 WHERE id = :id"),
            {"id": a.id},
        )
        await session.execute(
            text("UPDATE documents SET chunk_count = 4, token_count = 20 WHERE id = :id"),
            {"id": b.id},
        )
        await datasets_repo.recount(session, ds.id, now_ms=TIME_MS)
        row = await datasets_repo.get(session, ds.id)
    assert (row.document_count, row.chunk_count, row.token_num) == (2, 7, 30)


async def test_insert_then_get_returns_same_fields(sm) -> None:
    """documents.insert → get: wszystkie pola równe, parser_config jako dict (brief T2)."""
    ds = await seed_dataset(sm)
    row = await _insert_document(sm, ds)
    got = await _get_document(sm, row.id)
    assert isinstance(got.parser_config, dict)
    assert got.parser_config == ds.parser_config
    assert got.id == row.id and got.dataset_id == ds.id and got.created_by == ds.tenant_id
    assert got.name == "umowa.txt" and got.suffix == "txt" and got.type == "doc"
    assert got.size == 10 and got.location == row.location and got.content_hash == "0" * 32  # noqa: PLR2004 — size=10 z make_document_row
    assert got.source_type == "local" and got.source_ref is None
    assert got.chunk_method == ds.chunk_method and got.run == "0"
    assert got.progress == 0.0 and got.progress_msg == "" and got.error is None
    assert got.process_begin_at is None and got.process_duration == 0.0
    assert got.chunk_count == 0 and got.token_count == 0
    assert got.enabled is True and got.meta_fields == {} and got.thumbnail is None
    assert got.create_time == TIME_MS and got.update_time == TIME_MS


async def test_get_many_skips_missing_and_handles_empty(sm) -> None:
    """get_many([a, b, "x"*32]) → 2 wiersze; [] → [] (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds, name="a.txt")
    b = await _insert_document(sm, ds, name="b.txt")
    async with transaction(sm) as session:
        rows = await documents_repo.get_many(session, [a.id, b.id, "x" * 32])
        empty = await documents_repo.get_many(session, [])
    assert {r.id for r in rows} == {a.id, b.id}
    assert empty == []


async def test_start_parse_resets_progress_and_error(sm) -> None:
    """start_parse: run='1', progress=0, msg='', error=None, process_begin_at (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    async with transaction(sm) as session:
        await documents_repo.append_progress(
            session, a.id, progress=0.5, lines="12:00:00 A", now_ms=TIME_MS
        )
        await session.execute(
            text("UPDATE documents SET error = 'boom' WHERE id = :id"), {"id": a.id}
        )
        await documents_repo.start_parse(session, [a.id], now_ms=TIME_MS + 1000)
        row = await documents_repo.get(session, a.id)
    assert row.run == "1"
    assert row.progress == 0
    assert row.progress_msg == ""
    assert row.error is None
    assert row.process_begin_at == TIME_MS + 1000


async def test_append_progress_joins_lines_with_real_newline(sm) -> None:
    """append_progress: progress z COALESCE, linie sklejone znakiem "\n" (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    async with transaction(sm) as session:
        await documents_repo.append_progress(
            session, a.id, progress=0.5, lines="12:00:00 A", now_ms=TIME_MS
        )
        await documents_repo.append_progress(
            session, a.id, progress=None, lines="12:00:01 B", now_ms=TIME_MS + 1000
        )
        row = await documents_repo.get(session, a.id)
    assert row.progress == 0.5  # noqa: PLR2004 — FLOAT
    assert row.progress_msg == "12:00:00 A\n12:00:01 B"


async def test_append_progress_truncates_from_front(sm) -> None:
    """append_progress > 65536 znaków: RIGHT zostawia 65536 z ostatnią linią (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    last = "B" * 10
    async with transaction(sm) as session:
        await documents_repo.append_progress(
            session, a.id, progress=None, lines="A" * 70000, now_ms=TIME_MS
        )
        await documents_repo.append_progress(
            session, a.id, progress=None, lines=last, now_ms=TIME_MS
        )
        row = await documents_repo.get(session, a.id)
    assert len(row.progress_msg) == 65536  # noqa: PLR2004 — limit PROGRESS_MSG_MAX
    assert row.progress_msg.endswith("\n" + last)


async def test_fail_by_task_copies_task_error(sm) -> None:
    """fail_by_task: run='4', error z zadania, linia [ERROR] jako ostatnia (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    pid = await _insert_parse_task(sm, ds, a.id)
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE tasks SET error = 'EmptyDocument: No text' WHERE public_id = :pid"),
            {"pid": pid},
        )
        await documents_repo.append_progress(
            session, a.id, progress=None, lines="12:00:00 Started", now_ms=TIME_MS
        )
        await documents_repo.fail_by_task(session, pid, now_ms=TIME_MS + 5000)
        row = await documents_repo.get(session, a.id)
    assert row.run == "4"
    assert row.error == "EmptyDocument: No text"
    last = row.progress_msg.rsplit("\n", 1)[-1]
    assert re.fullmatch(r"\d\d:\d\d:\d\d \[ERROR\] EmptyDocument: No text", last)


async def test_fail_by_task_ignores_other_task_types(sm) -> None:
    """fail_by_task dla reembed_dataset — dokument bez zmian (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    pid = await _insert_parse_task(sm, ds, a.id, task_type="reembed_dataset")
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE tasks SET error = 'boom' WHERE public_id = :pid"), {"pid": pid}
        )
        await documents_repo.fail_by_task(session, pid, now_ms=TIME_MS + 5000)
        row = await documents_repo.get(session, a.id)
    assert row.run == "0"
    assert row.error is None
    assert row.progress_msg == ""


async def test_cancel_by_task_appends_cancelled_line(sm) -> None:
    """cancel_by_task: run='2', ostatnia linia „HH:MM:SS Task has been cancelled.” (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    pid = await _insert_parse_task(sm, ds, a.id)
    async with transaction(sm) as session:
        await documents_repo.cancel_by_task(session, pid, now_ms=TIME_MS + 6000)
        row = await documents_repo.get(session, a.id)
    assert row.run == "2"
    assert re.fullmatch(r"\d\d:\d\d:\d\d Task has been cancelled\.", row.progress_msg)


async def test_cancel_queued_touches_only_documents_with_queued_task(sm) -> None:
    """cancel_queued([a, b]), tylko a ma zadanie queued → a.run='2', b bez zmian (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds, name="a.txt")
    b = await _insert_document(sm, ds, name="b.txt")
    await _insert_parse_task(sm, ds, a.id)
    async with transaction(sm) as session:
        await documents_repo.cancel_queued(session, [a.id, b.id], now_ms=TIME_MS + 7000)
        row_a = await documents_repo.get(session, a.id)
        row_b = await documents_repo.get(session, b.id)
    assert row_a.run == "2"
    assert row_b.run == "0"
    assert row_b.progress_msg == ""


async def test_update_file_replaces_metadata(sm) -> None:
    """update_file podmienia metadane pliku i update_time (C2.2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    async with transaction(sm) as session:
        await documents_repo.update_file(
            session,
            a.id,
            name="nowy.pdf",
            suffix="pdf",
            type="pdf",
            size=99,
            location=f"files/{ds.id}/{a.id}/original.pdf",
            content_hash="f" * 32,
            now_ms=TIME_MS + 2000,
        )
        row = await documents_repo.get(session, a.id)
    assert (row.name, row.suffix, row.type, row.size) == ("nowy.pdf", "pdf", "pdf", 99)
    assert row.location == f"files/{ds.id}/{a.id}/original.pdf"
    assert row.content_hash == "f" * 32 and row.update_time == TIME_MS + 2000


async def test_finish_done_counts_committed_chunks(sm) -> None:
    """finish_done: run='3', progress=1, liczniki z chunków committed=1 (C2.2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    rows = [_chunk(a.id, ds.id, 7, i) for i in range(2)]
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, rows, now_ms=TIME_MS)
        await session.execute(
            text("UPDATE chunks SET committed = 1, token_count = 4 WHERE task_id = 7")
        )
        await session.execute(
            text("UPDATE documents SET run = '1', error = 'x' WHERE id = :id"), {"id": a.id}
        )
        await documents_repo.finish_done(session, a.id, duration_s=12.5, now_ms=TIME_MS + 3000)
        row = await documents_repo.get(session, a.id)
    assert row.run == "3"
    assert row.progress == 1
    assert row.error is None
    assert row.process_duration == 12.5  # noqa: PLR2004 — FLOAT z testu
    assert row.chunk_count == 2  # noqa: PLR2004 — liczba chunków z testu
    assert row.token_count == 8  # noqa: PLR2004 — suma token_count z testu


async def test_delete_many_cascades_chunks_and_vectors(sm) -> None:
    """delete_many → 1; chunki i wektory dokumentu usunięte kaskadą FK (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    rows = [_chunk(a.id, ds.id, 7, i) for i in range(2)]
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, 1024)
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, rows, now_ms=TIME_MS)
        await chunk_vectors_repo.insert_many(
            session, 1024, [(c.id, ds.id, [0.5] * 1024) for c in rows]
        )
    async with transaction(sm) as session:
        deleted = await documents_repo.delete_many(session, [a.id])
        assert deleted == 1
        assert await chunks_repo.count(session, a.id, committed=None) == 0
        assert await chunk_vectors_repo.count_by_document(session, 1024, a.id) == 0


async def test_chunk_id_is_deterministic_hex16(sm) -> None:
    """chunk_id: 16 znaków hex, deterministyczny, różny dla ordinal 1 (brief T2)."""
    first = chunk_id("d" * 32, "t" * 32, 0)
    assert len(first) == _CHUNK_ID_LEN
    int(first, 16)
    assert first == chunk_id("d" * 32, "t" * 32, 0)
    assert first != chunk_id("d" * 32, "t" * 32, 1)


async def test_insert_many_leaves_chunks_uncommitted(sm) -> None:
    """insert_many 3 chunków task 7: committed=True → 0, None → 3 (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    rows = [_chunk(a.id, ds.id, 7, i) for i in range(2)]
    # Trzeci chunk z pustymi positions — w bazie NULL; keywords/questions bez zmian.
    rows.append(replace(rows[0], id=chunk_id(a.id, "t" * 32, 2), ordinal=2, positions=()))
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, rows, now_ms=TIME_MS)
        assert await chunks_repo.count(session, a.id, committed=True) == 0
        assert await chunks_repo.count(session, a.id, committed=None) == 3  # noqa: PLR2004 — liczba chunków z testu
        assert await chunks_repo.count(session, a.id, committed=False) == 3  # noqa: PLR2004 — liczba chunków z testu
        third = (
            (
                await session.execute(
                    text("SELECT positions, keywords, questions FROM chunks WHERE ordinal = 2")
                )
            )
            .mappings()
            .one()
        )
    assert third["positions"] is None
    assert (json.loads(third["keywords"]), json.loads(third["questions"])) == (["a"], ["q"])


async def test_commit_task_keeps_only_task_chunks_committed(sm) -> None:
    """commit_task(doc, 7): stare chunki task 5 usunięte, chunki task 7 committed=1 (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    old = [_chunk(a.id, ds.id, 5, i) for i in range(2)]
    new = [_chunk(a.id, ds.id, 7, i) for i in range(3)]
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, old + new, now_ms=TIME_MS)
        await session.execute(text("UPDATE chunks SET committed = 1 WHERE task_id = 5"))
        await chunks_repo.commit_task(session, a.id, 7, now_ms=TIME_MS + 1000)
        remaining = await chunks_repo.count(session, a.id, committed=None)
        committed = await chunks_repo.count(session, a.id, committed=True)
        task_ids = (
            (
                await session.execute(
                    text("SELECT DISTINCT task_id FROM chunks WHERE document_id = :id"),
                    {"id": a.id},
                )
            )
            .scalars()
            .all()
        )
    assert (remaining, committed) == (3, 3)
    assert task_ids == [7]


async def test_delete_uncommitted_by_task_removes_only_uncommitted(sm) -> None:
    """delete_uncommitted_by_task(7) usuwa tylko committed=0 zadania 7 (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    rows = [_chunk(a.id, ds.id, 7, i) for i in range(3)]
    rows.append(_chunk(a.id, ds.id, 8, 0))
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, rows, now_ms=TIME_MS)
        await session.execute(
            text("UPDATE chunks SET committed = 1 WHERE task_id = 7 AND ordinal IN (0, 1)")
        )
        deleted = await chunks_repo.delete_uncommitted_by_task(session, 7)
        remaining = await chunks_repo.count(session, a.id, committed=None)
    assert deleted == 1
    assert remaining == 3  # noqa: PLR2004 — liczba chunków z testu


async def test_ensure_table_is_idempotent_with_expected_ddl(sm) -> None:
    """ensure_table(1024) dwa razy (osobne transakcje); DDL z vector(1024) i FK (brief T2)."""
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, 1024)
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, 1024)
        # SHOW CREATE TABLE zwraca dwie kolumny — DDL w "Create Table".
        row = (await session.execute(text("SHOW CREATE TABLE chunk_vec_d1024"))).mappings().one()
    ddl = row["Create Table"].lower()
    assert "vector(1024)" in ddl
    assert "fk_vec1024_chunk" in ddl


async def test_insert_vectors_then_count_by_document(sm) -> None:
    """insert_many(1024, [(chunk_id, ds, [1024 floatów])]) → count_by_document = 1 (brief T2)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    c = _chunk(a.id, ds.id, 7, 0)
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, [c], now_ms=TIME_MS)
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, 1024)
    async with transaction(sm) as session:
        await chunk_vectors_repo.insert_many(session, 1024, [(c.id, ds.id, [0.25] * 1024)])
        assert await chunk_vectors_repo.count_by_document(session, 1024, a.id) == 1


async def test_insert_vectors_batches_by_vec_batch(sm) -> None:
    """201 wektorów → 2 partie (VEC_BATCH=200); insert_many([]) bez SQL (C2.4)."""
    ds = await seed_dataset(sm)
    a = await _insert_document(sm, ds)
    rows = [_chunk(a.id, ds.id, 7, i) for i in range(201)]
    async with transaction(sm) as session:
        await chunks_repo.insert_many(session, rows, now_ms=TIME_MS)
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, 1024)
    async with transaction(sm) as session:
        await chunk_vectors_repo.insert_many(
            session, 1024, [(c.id, ds.id, [0.5] * 1024) for c in rows]
        )
        await chunk_vectors_repo.insert_many(session, 1024, [])
        assert await chunk_vectors_repo.count_by_document(session, 1024, a.id) == 201  # noqa: PLR2004 — 201 = VEC_BATCH + 1


async def test_insert_vector_rejects_wrong_length(sm) -> None:
    """Wektor długości 3 dla dim 1024 → ValueError (brief T2)."""
    ds = await seed_dataset(sm)
    async with transaction(sm) as session:
        with pytest.raises(ValueError, match="dimension"):
            await chunk_vectors_repo.insert_many(
                session, 1024, [("c" * 16, ds.id, [0.1, 0.2, 0.3])]
            )
