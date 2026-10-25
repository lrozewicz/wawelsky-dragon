"""Testy e2e workera: handler parse_document na prawdziwym Workerze (brief T8).

Marker db + fakellm (fake-llm z verify.sh); ``create_worker`` + pula procesów
(``ProcessPoolExecutor``) + MariaDB; stany końcowe DONE / FAIL / CANCEL / dead.
"""

import asyncio
import contextlib
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import chunk_vectors
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.llm.errors import LLMUnavailable
from app.services.documents import DocumentService
from app.storage.keys import document_prefix
from app.worker import queue as queue_module
from app.worker.main import create_worker, make_parse_pool
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_pdf_bytes, make_source, register_models

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

POLL_S = 0.05  # szybki poll kolejki (jak w tests/integration/queue/test_worker.py)
WAIT_TIMEOUT_S = 60.0  # limit z briefu T8


@contextlib.asynccontextmanager
async def _worker(
    migrated_db: Settings,
    tmp_path: Path,
    *,
    with_pool: bool = False,
) -> AsyncIterator[Container]:
    """Prawdziwy Worker z create_worker; pula procesów opcjonalna (brief T8)."""
    settings = migrated_db.model_copy(
        update={"storage_root": str(tmp_path), "ocr_engine": "none", "worker_poll_s": POLL_S}
    )
    pool = make_parse_pool(settings) if with_pool else None
    container, worker = create_worker(settings, executor=pool)
    await container.start()
    await register_models(container.sessionmaker)
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    try:
        yield container
    finally:
        stop.set()
        await asyncio.wait_for(run_task, timeout=15)
        await container.aclose()
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


def _gated_embed(
    entered: asyncio.Event, release: asyncio.Event, dim: int
) -> Callable[[object, object], Awaitable[list[list[float]]]]:
    """Atrapa embed: sygnalizuje wejście i czeka na zwolnienie (brief T8)."""

    async def gated(model: object, texts: object) -> list[list[float]]:
        entered.set()
        await release.wait()
        return [[0.1] * dim for _ in texts]  # type: ignore[union-attr]

    return gated


async def _wait_final(
    sm: async_sessionmaker[AsyncSession], document_id: str, *, timeout_s: float = WAIT_TIMEOUT_S
) -> None:
    """Czeka na stan końcowy dokumentu: ``run`` ∈ {'2','3','4'} bez zadań w toku albo ``dead``.

    Sam ``run`` nie wystarcza — dokument bywa już w stanie końcowym, gdy jego zadanie jest
    jeszcze ``running`` (wynik zapisywany dopiero po handlerze). Dlatego wymagamy, by żadne
    zadanie dokumentu nie było w stanie nieterminalnym — statusy terminalne to ``done``,
    ``failed``, ``cancelled`` i ``dead`` (05-ingestion §3.1), a nieterminalne tylko ``queued``
    (także ponowienie po backoffie) i ``running``. Dodatkowo wymagamy, by zadanie już istniało
    (``total >= 1``) — to chroni przed wyścigiem, w którym dokument ma ``run``, a wiersz zadania
    jeszcze nie powstał.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        async with sm() as session:
            run = (
                await session.execute(
                    text("SELECT run FROM documents WHERE id = :i"), {"i": document_id}
                )
            ).scalar_one()
            counts = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total,"
                        " COALESCE(SUM(status NOT IN ('done', 'failed', 'cancelled', 'dead')), 0)"
                        " AS pending,"
                        " COALESCE(SUM(status = 'dead'), 0) AS dead"
                        " FROM tasks WHERE document_id = :i"
                    ),
                    {"i": document_id},
                )
            ).one()
        finished = (
            str(run) in ("2", "3", "4") and int(counts.total) >= 1 and int(counts.pending) == 0
        )
        if finished or int(counts.dead) > 0:
            return
        await asyncio.sleep(0.2)
    raise AssertionError(f"dokument {document_id} nie osiągnął stanu końcowego w {timeout_s} s")


async def _document(sm: async_sessionmaker[AsyncSession], document_id: str) -> DocumentRow | None:
    """Świeży wiersz dokumentu."""
    async with transaction(sm) as session:
        return await documents_repo.get(session, document_id)


async def _task_statuses(sm: async_sessionmaker[AsyncSession], document_id: str) -> list[str]:
    """Statusy zadań dokumentu (kolejność wg id)."""
    async with sm() as session:
        rows = (
            await session.execute(
                text("SELECT status FROM tasks WHERE document_id = :i ORDER BY id"),
                {"i": document_id},
            )
        ).scalars()
        return [str(status) for status in rows]


async def _chunk_ids(sm: async_sessionmaker[AsyncSession], document_id: str) -> set[str]:
    """Identyfikatory wszystkich chunków dokumentu."""
    async with sm() as session:
        rows = (
            await session.execute(
                text("SELECT id FROM chunks WHERE document_id = :i"), {"i": document_id}
            )
        ).scalars()
        return {str(row) for row in rows}


async def _committed(sm: async_sessionmaker[AsyncSession], document_id: str) -> int:
    """Liczba chunków committed=1."""
    async with transaction(sm) as session:
        return await chunks_repo.count(session, document_id, committed=True)


async def test_pdf_done_via_process_pool(
    migrated_db: Settings, tmp_path: Path, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PDF → upload(parse=True) → worker z pulą: run='3', chunki i wektory, task done (brief)."""
    async with _worker(migrated_db, tmp_path, with_pool=True) as container:
        ds = await seed_dataset(sm)
        doc = await container.ingest.upload(
            ds.id, make_source(make_pdf_bytes(), "umowa.pdf"), created_by=ds.tenant_id, parse=True
        )

        await _wait_final(sm, doc.id)

        row = await _document(sm, doc.id)
        assert row is not None and row.run == "3"
        committed = await _committed(sm, doc.id)
        assert committed > 0
        assert row.chunk_count == committed
        async with transaction(sm) as session:
            vectors = await chunk_vectors.count_by_document(session, ds.embedding_dim, doc.id)
        assert vectors == committed
        assert await _task_statuses(sm, doc.id) == ["done"]


async def test_empty_txt_fails_with_error_line(
    migrated_db: Settings, tmp_path: Path, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Pusty TXT → run='4', error „No text could be extracted", ostatnia linia [ERROR] (brief)."""
    async with _worker(migrated_db, tmp_path) as container:
        ds = await seed_dataset(sm)
        doc = await container.ingest.upload(
            ds.id, make_source(b"   ", "pusty.txt"), created_by=ds.tenant_id, parse=True
        )

        await _wait_final(sm, doc.id)

        row = await _document(sm, doc.id)
        assert row is not None and row.run == "4"
        assert "No text could be extracted" in (row.error or "")
        last_line = row.progress_msg.split("\n")[-1]
        assert re.match(r"^\d\d:\d\d:\d\d \[ERROR\] ", last_line)


async def test_wrong_content_pdf_fails(
    migrated_db: Settings, tmp_path: Path, sm: async_sessionmaker[AsyncSession]
) -> None:
    """x.pdf z bajtami nie-PDF → run='4', error niepusty, tasks.status='failed' (brief)."""
    async with _worker(migrated_db, tmp_path) as container:
        ds = await seed_dataset(sm)
        doc = await container.ingest.upload(
            ds.id,
            make_source(b"to nie jest pdf", "x.pdf"),
            created_by=ds.tenant_id,
            parse=True,
        )

        await _wait_final(sm, doc.id)

        row = await _document(sm, doc.id)
        assert row is not None and row.run == "4"
        assert row.error
        assert await _task_statuses(sm, doc.id) == ["failed"]


async def test_transient_embed_error_goes_dead(
    migrated_db: Settings,
    tmp_path: Path,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMUnavailable z embed → próby wg max_attempts=3, potem dead i run='4' (brief)."""
    monkeypatch.setattr(queue_module, "backoff_ms", lambda attempts, jitter_ms: 200)

    async def unavailable(model: object, texts: object) -> list[list[float]]:
        raise LLMUnavailable("fake 503")

    async with _worker(migrated_db, tmp_path) as container:
        ds = await seed_dataset(sm)
        assert container.llm is not None
        monkeypatch.setattr(container.llm, "embed", unavailable)
        doc = await container.ingest.upload(
            ds.id,
            make_source(b"Lorem ipsum dolor sit amet. " * 50, "notatka.txt"),
            created_by=ds.tenant_id,
            parse=True,
        )

        await _wait_final(sm, doc.id)

        row = await _document(sm, doc.id)
        assert row is not None and row.run == "4"
        assert "LLMUnavailable" in (row.error or "")
        statuses = await _task_statuses(sm, doc.id)
        assert statuses == ["dead"]
        assert await _committed(sm, doc.id) == 0


async def test_cancel_during_embedding(
    migrated_db: Settings,
    tmp_path: Path,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anulowanie w trakcie embeddingu → run='2', linia cancelled, 0 chunków (brief)."""
    async with _worker(migrated_db, tmp_path) as container:
        ds = await seed_dataset(sm)
        assert container.llm is not None
        entered, release = asyncio.Event(), asyncio.Event()
        monkeypatch.setattr(
            container.llm, "embed", _gated_embed(entered, release, ds.embedding_dim)
        )
        doc = await container.ingest.upload(
            ds.id,
            make_source(b"Lorem ipsum dolor sit amet. " * 50, "notatka.txt"),
            created_by=ds.tenant_id,
            parse=True,
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=WAIT_TIMEOUT_S)
            assert await container.ingest.cancel([doc.id]) == 1
        finally:
            release.set()

        await _wait_final(sm, doc.id)

        row = await _document(sm, doc.id)
        assert row is not None and row.run == "2"
        last_line = row.progress_msg.split("\n")[-1]
        assert last_line.split(" ", 1)[1] == "Task has been cancelled."
        async with transaction(sm) as session:
            assert await chunks_repo.count(session, doc.id, committed=None) == 0


async def test_reparse_replaces_chunks(
    migrated_db: Settings,
    tmp_path: Path,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-parse (clear_existing): w trakcie stare chunki nietknięte, po DONE tylko nowe (brief)."""
    async with _worker(migrated_db, tmp_path) as container:
        ds = await seed_dataset(sm)
        doc = await container.ingest.upload(
            ds.id,
            make_source(b"Lorem ipsum dolor sit amet. " * 50, "notatka.txt"),
            created_by=ds.tenant_id,
            parse=True,
        )
        await _wait_final(sm, doc.id)
        row = await _document(sm, doc.id)
        assert row is not None and row.run == "3"
        n = row.chunk_count
        assert n > 0
        old_ids = await _chunk_ids(sm, doc.id)
        assert len(old_ids) == n

        assert container.llm is not None
        entered, release = asyncio.Event(), asyncio.Event()
        monkeypatch.setattr(
            container.llm, "embed", _gated_embed(entered, release, ds.embedding_dim)
        )
        [public_id] = await container.ingest.enqueue_parse([doc.id], clear_existing=True)
        try:
            await asyncio.wait_for(entered.wait(), timeout=WAIT_TIMEOUT_S)
            async with transaction(sm) as session:
                assert await chunks_repo.count(session, doc.id, committed=True) == n
                assert await chunks_repo.count(session, doc.id, committed=None) == n
        finally:
            release.set()
        assert public_id

        await _wait_final(sm, doc.id)

        row2 = await _document(sm, doc.id)
        assert row2 is not None and row2.run == "3"
        new_ids = await _chunk_ids(sm, doc.id)
        assert new_ids.isdisjoint(old_ids)
        assert len(new_ids) == row2.chunk_count
        assert await _committed(sm, doc.id) == row2.chunk_count


async def test_service_parse_rerun_single_copy(
    migrated_db: Settings, tmp_path: Path, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Reparse przez ``DocumentService.parse`` (POST .../chunks) na DONE: bez duplikatów (brief T4).

    Pierwszy przebieg workera (fake-llm) domyka dokument w ``run='3'``; drugie zlecenie idzie
    ścieżką usługi (DONE → ``clear_existing=True``) i po dokończeniu liczba wierszy ``chunks``
    oraz wektorów jest równa pierwszej (nie dwukrotność), ``chunk_count``/``token_count``
    zgodne z wierszami, brak osieroconych wektorów.
    """
    async with _worker(migrated_db, tmp_path) as container:
        ds = await seed_dataset(sm)
        doc = await container.ingest.upload(
            ds.id,
            make_source(b"Lorem ipsum dolor sit amet. " * 50, "notatka.txt"),
            created_by=ds.tenant_id,
            parse=True,
        )
        await _wait_final(sm, doc.id)

        first = await _document(sm, doc.id)
        assert first is not None and first.run == "3"
        n = first.chunk_count
        assert n > 0
        old_ids = await _chunk_ids(sm, doc.id)
        assert len(old_ids) == n
        async with transaction(sm) as session:
            first_vectors = await chunk_vectors.count_by_document(session, ds.embedding_dim, doc.id)
        assert first_vectors == n

        principal = Principal(
            user_id=ds.tenant_id,
            email=f"{ds.tenant_id}@example.com",
            is_superuser=False,
            is_service=False,
            auth_kind="jwt",
        )
        assert await DocumentService(container).parse(principal, ds.id, [doc.id]) == (1, [])

        await _wait_final(sm, doc.id)

        second = await _document(sm, doc.id)
        assert second is not None and second.run == "3"
        new_ids = await _chunk_ids(sm, doc.id)
        assert len(new_ids) == n  # liczba wierszy bez zmian (nie dwukrotność)
        assert new_ids.isdisjoint(old_ids)  # stara porcja zniknęła po commicie
        assert second.chunk_count == await _committed(sm, doc.id) == n
        vec_table = chunk_vectors.table_name(ds.embedding_dim)
        async with transaction(sm) as session:
            tokens = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(token_count), 0) FROM chunks"
                        " WHERE document_id = :i AND committed = 1"
                    ),
                    {"i": doc.id},
                )
            ).scalar_one()
            vectors = await chunk_vectors.count_by_document(session, ds.embedding_dim, doc.id)
            raw = (
                await session.execute(text(f"SELECT COUNT(*) FROM {vec_table}"))  # noqa: S608
            ).scalar_one()
        assert second.token_count == tokens
        assert vectors == raw == n  # brak osieroconych wektorów (każdy wiersz ma chunk)
        assert await _task_statuses(sm, doc.id) == ["done", "done"]


async def test_delete_documents_after_done(
    migrated_db: Settings, tmp_path: Path, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete_documents po DONE: 0 chunków/wektorów, katalog usunięty, licznik datasetu (brief)."""
    async with _worker(migrated_db, tmp_path) as container:
        ds = await seed_dataset(sm)
        doc = await container.ingest.upload(
            ds.id,
            make_source(b"Lorem ipsum dolor sit amet. " * 50, "notatka.txt"),
            created_by=ds.tenant_id,
            parse=True,
        )
        await _wait_final(sm, doc.id)
        row = await _document(sm, doc.id)
        assert row is not None and row.run == "3"

        assert await container.ingest.delete_documents([doc.id]) == 1

        async with transaction(sm) as session:
            assert await chunks_repo.count(session, doc.id, committed=None) == 0
            assert await chunk_vectors.count_by_document(session, ds.embedding_dim, doc.id) == 0
            dataset = await datasets_repo.get(session, ds.id)
        assert dataset is not None and dataset.document_count == 0
        assert await _document(sm, doc.id) is None
        assert not (tmp_path / document_prefix(ds.id, doc.id)).exists()
