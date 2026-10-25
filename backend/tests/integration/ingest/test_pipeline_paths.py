"""Testy integracyjne run_parse — ścieżki brzegowe (brief T7): digest, re-parse,
anulowanie, wzbogacanie, błędy modeli, tabela wektorów, 0 chunków."""

import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import task_lookup
from app.db.uow import transaction
from app.parsing.errors import EmptyDocument
from app.services import ingest_pipeline
from app.services.ingest_pipeline import run_parse
from app.worker.context import TaskContext
from app.worker.errors import PermanentError, TaskCancelled
from app.worker.queue import TaskRow
from tests.integration.ingest.conftest import DEFAULT_PARSER_CONFIG, seed_dataset
from tests.integration.ingest.pipeline_helpers import (
    WORKER_ID,
    claim_context,
    make_container,
    make_source,
    worker_queue,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

_TXT = (
    "Umowa najmu lokalu mieszkalnego. Lokator płaci czynsz piątego dnia miesiąca.\n" * 4
).encode()


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path, modele fake zarejestrowane."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


async def _upload(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    content: bytes = _TXT,
    filename: str = "notatka.txt",
    **seed: object,
) -> tuple[object, object]:
    """Dataset + upload pliku (domyślnie _TXT); seed przekazywany do seed_dataset."""
    ds = await seed_dataset(sm, **seed)  # type: ignore[arg-type]
    doc = await container.ingest.upload(
        ds.id, make_source(content, filename), created_by=ds.tenant_id
    )
    return ds, doc


async def _internal_id(sm: async_sessionmaker[AsyncSession], public_id: str) -> int:
    """Wewnętrzne BIGINT id zadania (asercje testowe)."""
    async with transaction(sm) as session:
        found = await task_lookup.internal_id(session, public_id)
    assert found is not None
    return found


async def _committed_chunks(
    sm: async_sessionmaker[AsyncSession], document_id: str
) -> list[tuple[str, int]]:
    """(id, task_id) chunków committed=1 w kolejności ordinal (asercje testowe)."""
    async with transaction(sm) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, task_id FROM chunks WHERE document_id = :d"
                    " AND committed = 1 ORDER BY ordinal"
                ),
                {"d": document_id},
            )
        ).all()
    return [(str(row[0]), int(row[1])) for row in rows]


async def _table_exists(sm: async_sessionmaker[AsyncSession], name: str) -> bool:
    """Czy tabela istnieje w bieżącej bazie (information_schema, brief T7)."""
    async with transaction(sm) as session:
        count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables"
                    " WHERE table_schema = DATABASE() AND table_name = :t"
                ),
                {"t": name},
            )
        ).scalar_one()
    return int(count) == 1


async def test_empty_txt_raises_empty_document(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Pusty TXT (same spacje) → ConversionFailed "No text could be extracted", 0 chunków."""
    _, doc = await _upload(container, sm, content=b"   ", filename="pusty.txt")
    ctx = await claim_context(container, doc.id)

    with pytest.raises(EmptyDocument, match="No text could be extracted"):
        await run_parse(container, ctx.task, ctx, executor=None)

    assert await _committed_chunks(sm, doc.id) == []


async def test_zero_chunks_rule(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reguła 0 chunków: chunker bez draftów → EmptyDocument (atrapa chunk_blocks)."""

    def no_chunks(blocks: object, preset: object, cfg: object) -> list[object]:
        return []

    monkeypatch.setattr(ingest_pipeline, "chunk_blocks", no_chunks)
    _, doc = await _upload(container, sm)
    ctx = await claim_context(container, doc.id)

    with pytest.raises(EmptyDocument, match="No text could be extracted"):
        await run_parse(container, ctx.task, ctx, executor=None)

    assert await _committed_chunks(sm, doc.id) == []


async def test_reparse_keeps_old_chunks_until_commit(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-parse (clear_existing): w trakcie stare committed=1 są; po — tylko nowe (brief T7)."""
    _, doc = await _upload(container, sm)
    first = await claim_context(container, doc.id)
    await run_parse(container, first.task, first, executor=None)
    await worker_queue(container).complete(first.task.id, WORKER_ID)
    old = await _committed_chunks(sm, doc.id)
    assert old

    second = await claim_context(container, doc.id, clear_existing=True)
    second_pk = await _internal_id(sm, second.task.id)
    snapshots: list[int] = []
    real_embed = ingest_pipeline.embed_texts

    async def spy(*args: object, **kwargs: object) -> object:
        async with transaction(sm) as session:
            snapshots.append(await chunks_repo.count(session, doc.id, committed=True))
        return await real_embed(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest_pipeline, "embed_texts", spy)
    await run_parse(container, second.task, second, executor=None)

    assert snapshots  # embed_texts wołany (tytuł + treści chunków)
    new = await _committed_chunks(sm, doc.id)
    assert len(new) == len(old)
    assert {chunk_id for chunk_id, _ in new}.isdisjoint({chunk_id for chunk_id, _ in old})
    assert all(task_id == second_pk for _, task_id in new)


async def test_digest_reuse_skips_embedding(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Digest bez clear: DONE bez parsowania, 0 wywołań embed, te same chunki (brief T7)."""
    _, doc = await _upload(container, sm)
    first = await claim_context(container, doc.id)
    await run_parse(container, first.task, first, executor=None)
    await worker_queue(container).complete(first.task.id, WORKER_ID)
    before = await _committed_chunks(sm, doc.id)
    assert container.llm is not None
    real_embed = container.llm.embed
    embed_calls: list[list[str]] = []

    async def counting(model: object, texts: object) -> object:
        embed_calls.append(list(texts))  # type: ignore[arg-type]
        return await real_embed(model, texts)  # type: ignore[arg-type]

    monkeypatch.setattr(container.llm, "embed", counting)
    second = await claim_context(container, doc.id)
    await run_parse(container, second.task, second, executor=None)

    assert embed_calls == []
    assert await _committed_chunks(sm, doc.id) == before


async def test_cancel_requested_raises_task_cancelled(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """request_cancel po claim → TaskCancelled, brak chunków w bazie (brief T7)."""
    _, doc = await _upload(container, sm)
    ctx = await claim_context(container, doc.id)
    await worker_queue(container).request_cancel(document_ids=[doc.id])

    with pytest.raises(TaskCancelled):
        await run_parse(container, ctx.task, ctx, executor=None)

    assert await _committed_chunks(sm, doc.id) == []


async def test_auto_keywords_and_questions(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """auto_keywords/auto_questions → keywords, important_ft, question_ft, embed_source."""
    ds = await seed_dataset(
        sm,
        parser_config={**DEFAULT_PARSER_CONFIG, "auto_keywords": 3, "auto_questions": 2},
    )
    doc = await container.ingest.upload(
        ds.id, make_source(_TXT, "notatka.txt"), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)

    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT keywords, questions, important_ft, question_ft, embed_source"
                        " FROM chunks WHERE document_id = :d AND committed = 1"
                    ),
                    {"d": doc.id},
                )
            )
            .mappings()
            .all()
        )
    assert rows
    for row in rows:
        keywords = json.loads(str(row["keywords"]))
        questions = json.loads(str(row["questions"]))
        assert keywords and questions
        assert str(row["important_ft"]) and str(row["question_ft"])
        assert row["embed_source"] == "questions"


async def test_unknown_embedding_model(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieznany embedding_model datasetu → PermanentError (brief T7)."""
    _, doc = await _upload(container, sm, embedding_model="no-such-model")
    ctx = await claim_context(container, doc.id)

    with pytest.raises(PermanentError, match="embedding model not found"):
        await run_parse(container, ctx.task, ctx, executor=None)


async def test_embedding_dim_mismatch(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """embedding_dim=1536 przy modelu 1024 → PermanentError o niezgodnym wymiarze."""
    _, doc = await _upload(container, sm, embedding_dim=1536)
    ctx = await claim_context(container, doc.id)

    with pytest.raises(PermanentError, match="does not match dataset embedding_dim"):
        await run_parse(container, ctx.task, ctx, executor=None)


async def test_chunk_vec_table_created_on_first_done(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """chunk_vec_d1024 tworzona ścieżką CREATE TABLE IF NOT EXISTS przy pierwszym DONE."""
    _, doc = await _upload(container, sm)
    assert not await _table_exists(sm, "chunk_vec_d1024")

    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)

    assert await _table_exists(sm, "chunk_vec_d1024")


def _dummy_task(document_id: str) -> TaskRow:
    """TaskRow bez bazy (kontener bez start() nie dochodzi do kolejki)."""
    return TaskRow(
        id="0" * 32,
        task_type="parse_document",
        payload={},
        document_id=document_id,
        dataset_id=None,
        priority=0,
        status="running",
        attempts=0,
        max_attempts=3,
        cancel_requested=False,
        progress=0.0,
        progress_msg="",
        digest=None,
        error=None,
        locked_by=None,
    )


async def test_unstarted_container_raises_runtime_error(
    migrated_db: Settings, tmp_path: Path
) -> None:
    """Kontener bez start() → RuntimeError zamiast I/O (C7)."""
    container = Container(migrated_db.model_copy(update={"storage_root": str(tmp_path)}))
    task = _dummy_task("d" * 32)
    ctx = TaskContext(
        task, WORKER_ID, container, logging.LoggerAdapter(logging.getLogger("test"), {}), None
    )

    with pytest.raises(RuntimeError, match="container not started"):
        await run_parse(container, task, ctx, executor=None)


async def test_layout_vision_model_missing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """layout_recognize wskazuje nieznany model image2text → PermanentError (C7)."""
    ds = await seed_dataset(
        sm, parser_config={**DEFAULT_PARSER_CONFIG, "layout_recognize": "brak-modelu"}
    )
    doc = await container.ingest.upload(
        ds.id, make_source(_TXT, "notatka.txt"), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id)

    with pytest.raises(PermanentError, match="image2text model not found"):
        await run_parse(container, ctx.task, ctx, executor=None)


async def test_chat_model_missing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """llm_id wskazuje nieznany model czatu → PermanentError (C7)."""
    ds = await seed_dataset(
        sm, parser_config={**DEFAULT_PARSER_CONFIG, "llm_id": "brak-czatu", "auto_keywords": 3}
    )
    doc = await container.ingest.upload(
        ds.id, make_source(_TXT, "notatka.txt"), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id)

    with pytest.raises(PermanentError, match="chat model not found"):
        await run_parse(container, ctx.task, ctx, executor=None)


async def test_auto_keywords_only(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """auto_keywords bez pytań: keywords niepuste, embed_source="content" (C7)."""
    ds = await seed_dataset(sm, parser_config={**DEFAULT_PARSER_CONFIG, "auto_keywords": 3})
    doc = await container.ingest.upload(
        ds.id, make_source(_TXT, "notatka.txt"), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)

    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT keywords, embed_source FROM chunks"
                        " WHERE document_id = :d AND committed = 1"
                    ),
                    {"d": doc.id},
                )
            )
            .mappings()
            .all()
        )
    assert rows
    for row in rows:
        assert json.loads(str(row["keywords"]))
        assert row["embed_source"] == "content"


async def test_ocr_engine_vlm_without_model_continues(
    migrated_db: Settings, tmp_path: Path, sm: async_sessionmaker[AsyncSession]
) -> None:
    """ocr_engine="vlm" bez modelu image2text → brak wizji, pipeline działa dalej (C7)."""
    container = await make_container(migrated_db, tmp_path, ocr_engine="vlm")
    try:
        _, doc = await _upload(container, sm)
        ctx = await claim_context(container, doc.id)
        await run_parse(container, ctx.task, ctx, executor=None)
        assert await _committed_chunks(sm, doc.id)
    finally:
        await container.aclose()
