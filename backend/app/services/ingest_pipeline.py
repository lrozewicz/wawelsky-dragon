"""Pipeline parsowania dokumentu: ``run_parse`` (kontrakt C7, K5 §6.5, 05 §5.2).

Kolejność kroków wiążąca (brief T7); postęp przez ``ProgressReporter``; kroki 2-12
w try/finally z flushem bufora (krok 13) - przy błędzie linie postępu trafiają do
bazy przed linią ``[ERROR]`` dopisywaną przez hook §6.3.
"""

from __future__ import annotations

import time
from concurrent.futures import Executor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.errors import NotFound
from app.db.repositories import chunk_vectors, task_lookup
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.chunks import ChunkInsert, chunk_id
from app.db.uow import transaction
from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import ChunkDraft
from app.llm.gateway import LLMGateway
from app.llm.hooks import TaskLlmHooks, install_hooks, reset_hooks
from app.llm.registry import ModelRegistry
from app.llm.types import ModelRef
from app.parsing.blocks import html_to_blocks
from app.parsing.errors import empty_document
from app.parsing.html import sanitize_html
from app.parsing.types import ConvertedDocument
from app.services import auto_metadata
from app.services.concurrency import resolve_concurrency
from app.services.embed import combine, embed_texts
from app.services.enrich import Enrichment, enrich_chunks
from app.services.ingest_commit import write_parse_result
from app.services.ingest_convert import chunk_config
from app.services.ingest_outline import finish_outline
from app.services.ingest_progress import ProgressReporter
from app.services.ingest_stage import _convert, _recognizers
from app.storage.keys import derived_key
from app.text.fulltext import ft_text, stem_text
from app.worker.errors import PermanentError

if TYPE_CHECKING:
    from app.core.container import Container
    from app.db.repositories.datasets import DatasetRow
    from app.db.repositories.documents import DocumentRow
    from app.worker.context import TaskContext
    from app.worker.queue import TaskRow

_LAYOUT_PLAIN = (None, "", "DeepDOC", "Plain Text")  # layout_recognize bez wizji (C7)


@dataclass(frozen=True)
class _Prepared:
    """Treść chunku gotowa do embeddingu i zapisu (krok 9 C7)."""

    draft: ChunkDraft
    questions: tuple[str, ...]
    keywords: tuple[str, ...]
    embed_source: str  # "content" | "questions"
    embed_text: str  # pytania złączone albo treść draftu


def _started(container: Container) -> tuple[async_sessionmaker[Any], ModelRegistry, LLMGateway]:
    """Pola kontenera wymagane przez pipeline; kontener bez start() → RuntimeError (C7)."""
    if container.sessionmaker is None or container.models is None or container.llm is None:
        raise RuntimeError("container not started")
    return container.sessionmaker, container.models, container.llm


async def _read_inputs(
    sm: async_sessionmaker[Any], task: TaskRow
) -> tuple[DocumentRow, DatasetRow, int, str | None, int]:
    """Krok 2: dokument, dataset, wewnętrzne id zadania, digest poprzedni, licznik chunków."""
    document_id = task.document_id
    async with transaction(sm) as session:
        doc = await documents_repo.get(session, document_id) if document_id is not None else None
        ds = await datasets_repo.get(session, doc.dataset_id) if doc is not None else None
        task_pk = await task_lookup.internal_id(session, task.id)
        prev: str | None = None
        committed = 0
        if doc is not None:
            prev = await task_lookup.last_done_digest(session, doc.id, exclude_public_id=task.id)
            committed = await chunks_repo.count(session, doc.id, committed=True)
    if doc is None or ds is None or task_pk is None:
        raise PermanentError(f"document not found: {document_id}")
    return doc, ds, task_pk, prev, committed


async def _resolve_embedding(models: ModelRegistry, name: str) -> ModelRef:
    """Krok 3: model embeddingu datasetu; nieznany → PermanentError (C7)."""
    try:
        return await models.resolve(name, "embedding")
    except NotFound as exc:
        raise PermanentError(f"embedding model not found: {name}") from exc


async def _finish_reused(  # noqa: PLR0913, PLR0917 — kształt kroku 4 z kontraktu C7
    container: Container,
    sm: async_sessionmaker[Any],
    rep: ProgressReporter,
    doc: DocumentRow,
    ds: DatasetRow,
    t0: float,
) -> None:
    """Krok 4: ścieżka digestu - DONE bez parsowania (BEZ commit_task: stare chunki mają
    inny task_id i zostałyby usunięte; liczniki i tak biorą pod uwagę tylko committed=1)."""
    now_ms = container.clock.now_ms()
    async with transaction(sm) as session:
        # Blokada datasetu przed zapisem (kolejność blokad; deadlock 1213 — DEC-088 p. 3).
        await datasets_repo.lock(session, ds.id)
        await documents_repo.finish_done(
            session, doc.id, duration_s=time.monotonic() - t0, now_ms=now_ms
        )
        await datasets_repo.recount(session, ds.id, now_ms=now_ms)
    await rep.report(1.0, "Reused previous chunks.")


async def _enrich(  # noqa: PLR0913, PLR0917 — kształt kroku 8 z kontraktu C7
    rep: ProgressReporter,
    llm: LLMGateway,
    models: ModelRegistry,
    pc: dict[str, Any],
    drafts: list[ChunkDraft],
    ctx: TaskContext,
) -> list[Enrichment]:
    """Krok 8: słowa kluczowe i pytania; bez włączonego wzbogacania → puste Enrichment."""
    kw = int(pc.get("auto_keywords") or 0)
    qn = int(pc.get("auto_questions") or 0)
    if kw <= 0 and qn <= 0:
        return [Enrichment()] * len(drafts)
    ref = pc.get("llm_id") or None
    try:
        chat = await models.resolve(ref, "chat")
    except NotFound as exc:
        raise PermanentError(f"chat model not found: {ref}") from exc
    if kw > 0:
        await rep.report(0.45, f"Keywords generation for {len(drafts)} chunks")
    if qn > 0:
        await rep.report(0.60, f"Question generation for {len(drafts)} chunks")
    enrichments, warnings = await enrich_chunks(
        llm,
        chat,
        [d.text for d in drafts],
        auto_keywords=kw,
        auto_questions=qn,
        check_cancel=ctx.check_cancel,
    )
    for warning in warnings[:20]:
        await rep.report(0.60, f"[WARNING] {warning}")
    return enrichments


async def _auto_metadata(  # noqa: PLR0913, PLR0917 — kształt kroku 8b z K11 §10f p.4
    rep: ProgressReporter,
    ctx: TaskContext,
    llm: LLMGateway,
    models: ModelRegistry,
    doc: DocumentRow,
    drafts: list[ChunkDraft],
) -> dict[str, Any] | None:
    """Krok 8b: auto-metadane po chunkowaniu (K11 §10f p.4); błąd modelu → log, parse trwa."""
    pc = doc.parser_config
    schema = auto_metadata.metadata_schema(pc)
    if schema is None:
        return None
    ref = pc.get("llm_id") or None
    try:
        chat = await models.resolve(ref, "chat")
    except NotFound as exc:
        raise PermanentError(f"chat model not found: {ref}") from exc
    await ctx.check_cancel()
    # Postęp nie cofa się (U6): gdy auto_questions>0, ``_prepare_chunks`` sięgnął już 0.60.
    progress = max(rep.last_progress, 0.55)
    try:
        extracted = await auto_metadata.extract_auto_metadata(
            llm, chat, schema, [d.text for d in drafts]
        )
    except auto_metadata.AutoMetadataError as exc:
        await rep.report(progress, f"Auto metadata failed: {exc}")
        return None
    merged, changed = auto_metadata.merge_metadata(doc.meta_fields, extracted, schema)
    await rep.report(progress, f"Auto metadata: {changed} fields")
    return merged if changed else None


async def _prepare_chunks(  # noqa: PLR0913, PLR0917 — kształt kroków 7-9 z kontraktu C7
    rep: ProgressReporter,
    ctx: TaskContext,
    llm: LLMGateway,
    models: ModelRegistry,
    doc: DocumentRow,
    converted: ConvertedDocument,
) -> tuple[str, list[ChunkDraft], list[_Prepared]]:
    """Kroki 7-9: chunkowanie (0 chunków → EmptyDocument), wzbogacanie, treści do embeddingu."""
    pc = doc.parser_config
    html = sanitize_html(converted.html)
    drafts = chunk_blocks(html_to_blocks(html), preset_for(doc.chunk_method), chunk_config(pc))
    if not drafts:
        raise empty_document("no chunks produced")
    await rep.report(0.45, f"Generate {len(drafts)} chunks")
    await ctx.check_cancel()
    enrichments = await _enrich(rep, llm, models, pc, drafts, ctx)
    await ctx.check_cancel()
    prepared: list[_Prepared] = []
    for i, draft in enumerate(drafts):
        questions = draft.questions + enrichments[i].questions
        prepared.append(
            _Prepared(
                draft=draft,
                questions=questions,
                keywords=enrichments[i].keywords,
                embed_source="questions" if questions else "content",
                embed_text="\n".join(questions) if questions else draft.text,
            )
        )
    return html, drafts, prepared


async def _embed_all(  # noqa: PLR0913, PLR0917 — kształt kroku 10 z kontraktu C7
    container: Container,
    rep: ProgressReporter,
    ctx: TaskContext,
    llm: LLMGateway,
    emb: ModelRef,
    ds: DatasetRow,
    pc: dict[str, Any],
    title: str,
    prepared: list[_Prepared],
    concurrency: int = 1,
) -> list[list[float]]:
    """Krok 10: wektor tytułu, embeddingi partiami równolegle (`concurrency`, raport po partii),
    mieszanie z wagą nazwy pliku (domyślnie 0.1)."""
    title_vecs = await embed_texts(llm, emb, [title], batch_size=1, expected_dim=ds.embedding_dim)
    title_vec = title_vecs[0]

    async def on_batch(done: int, total: int) -> None:
        await rep.report(0.60 + 0.35 * done / total, f"Embedding chunks ({done}/{total})")

    vecs = await embed_texts(
        llm,
        emb,
        [p.embed_text for p in prepared],
        batch_size=container.settings.embed_batch_size,
        expected_dim=ds.embedding_dim,
        concurrency=concurrency,
        on_batch=on_batch,
        check_cancel=ctx.check_cancel,
    )
    raw_weight = pc.get("filename_embd_weight")
    weight = 0.1 if raw_weight is None else float(raw_weight)
    return [combine(title_vec, vector, weight) for vector in vecs]


def _rows(  # noqa: PLR0913, PLR0917 — pola kroku 11 z kontraktu C7
    task: TaskRow,
    doc: DocumentRow,
    ds: DatasetRow,
    task_pk: int,
    title: str,
    prepared: list[_Prepared],
) -> list[ChunkInsert]:
    """Krok 11: drafty + wzbogacenie → ChunkInsert (pola wg K5 §6.1/§6.2)."""
    return [
        ChunkInsert(
            id=chunk_id(doc.id, task.id, p.draft.ordinal),
            document_id=doc.id,
            dataset_id=ds.id,
            task_id=task_pk,
            ordinal=p.draft.ordinal,
            chunk_type=str(p.draft.chunk_type),
            content=p.draft.text,
            content_llm=p.draft.html or None,
            content_ft=ft_text(p.draft.text),
            content_stem=stem_text(p.draft.text),
            title_ft=ft_text(title),
            important_ft=ft_text(" ".join(p.keywords)),
            question_ft=ft_text("\n".join(p.questions)),
            keywords=p.keywords,
            questions=p.questions,
            positions=p.draft.positions,
            page_from=p.draft.page_from,
            page_to=p.draft.page_to,
            token_count=p.draft.tokens,
            embed_source=p.embed_source,
        )
        for p in prepared
    ]


async def _save(  # noqa: PLR0913, PLR0917 — kształt kroku 11 z kontraktu C7
    container: Container,
    sm: async_sessionmaker[Any],
    ctx: TaskContext,
    doc: DocumentRow,
    ds: DatasetRow,
    task_pk: int,
    html: str,
    rows: list[ChunkInsert],
    vectors: list[list[float]],
    t0: float,
) -> None:
    """Krok 11: tabela wektorów (DDL = niejawny COMMIT, osobna transakcja) i atomowy zapis.

    Awaria przed transakcją (c) nie zostawia chunków committed=0; stare chunki widoczne
    do chwili commitu (K5 §6.2 p. 2); po commicie derived HTML.
    """
    async with transaction(sm) as session:  # (a) DDL = niejawny COMMIT - osobna transakcja
        await chunk_vectors.ensure_table(session, ds.embedding_dim)
    await ctx.check_cancel()  # (b)
    now_ms = container.clock.now_ms()
    # (c) jeden atomowy zapis (K5 §6.2 p. 2), ponawiany przy deadlocku 1213/1205 — DEC-088.
    await write_parse_result(
        sm, ds=ds, doc=doc, task_pk=task_pk, rows=rows, vectors=vectors, t0=t0, now_ms=now_ms
    )
    await container.storage.put(derived_key(ds.id, doc.id, "normalized.html"), html.encode())  # (d)


async def run_parse(
    container: Container, task: TaskRow, ctx: TaskContext, *, executor: Executor | None
) -> None:
    """Przeprowadza dokument przez konwersję → chunking → wzbogacenie → embeddingi → zapis (C7)."""
    sm, models, llm = _started(container)  # krok 3: kontener musi być wystartowany
    document_id = task.document_id
    if document_id is None:  # zadanie parse_document zawsze ma dokument; zawęża typ
        raise PermanentError(f"document not found: {document_id}")
    rep = ProgressReporter(sm, container.clock, ctx, document_id)
    t0 = time.monotonic()
    # Hooki bramki PRZED utworzeniem potoku OCR i zadań embeddingu (C1); reset w finally.
    token = install_hooks(
        TaskLlmHooks(
            log=lambda msg: rep.report(rep.last_progress, msg),
            check_cancel=ctx.check_cancel,
        )
    )
    await rep.report(0.01, "Task has been received.", force=True)  # krok 1
    try:
        doc, ds, task_pk, prev, committed = await _read_inputs(sm, task)  # krok 2
        emb = await _resolve_embedding(models, ds.embedding_model)  # krok 3
        # Walidacja równoległości embeddingu przed konwersją (kontrakt C2) — czytelny błąd
        # zamiast awarii w kroku 10; model czytany z rejestru (PATCH działa w następnym zadaniu).
        embed_concurrency = resolve_concurrency(emb, container.settings.embed_concurrency)
        pc = doc.parser_config
        layout_vision = pc.get("layout_recognize") not in _LAYOUT_PLAIN  # krok 5
        clear = bool(task.payload.get("clear_existing", False))  # krok 4
        if not clear and task.digest is not None and task.digest == prev and committed > 0:
            await _finish_reused(container, sm, rep, doc, ds, t0)
        else:
            vision, ocr, diacritics, vision_model = await _recognizers(
                container, models, llm, pc, layout_vision=layout_vision
            )  # krok 5
            converted = await _convert(
                container,
                rep,
                ctx,
                doc,
                vision,
                ocr,
                diacritics,
                layout_vision,
                vision_model,
                executor=executor,
            )  # krok 6
            html, drafts, prepared = await _prepare_chunks(
                rep, ctx, llm, models, doc, converted
            )  # kroki 7-9
            meta_fields = await _auto_metadata(rep, ctx, llm, models, doc, drafts)  # krok 8b
            title = Path(doc.name).stem
            vectors = await _embed_all(
                container,
                rep,
                ctx,
                llm,
                emb,
                ds,
                pc,
                title,
                prepared,
                embed_concurrency,
            )  # krok 10
            rows = _rows(task, doc, ds, task_pk, title, prepared)
            # krok 11c przed 11 (T12, K21 §2 p. 1): linia „Outline: …” i flush przed run='3'.
            await finish_outline(container, sm, rep, doc, html)  # krok 11c (K21 §2 p. 1)
            await rep.flush()  # linia spisu w bazie przed ustawieniem run='3'
            await _save(container, sm, ctx, doc, ds, task_pk, html, rows, vectors, t0)  # krok 11
            if meta_fields is not None:  # krok 8b: zapis po commitcie chunków (K11 §10f p.4)
                async with transaction(sm) as session:
                    await documents_repo.set_meta_fields(session, doc.id, meta_fields=meta_fields)
        done = f"Indexing done ({time.monotonic() - t0:.2f}s). Done."
        await rep.report(1.0, done, force=True)  # krok 12
        await rep.flush()
    finally:  # krok 13: bufor postępu trafia do bazy także przy błędzie
        reset_hooks(token)
        await rep.flush()
