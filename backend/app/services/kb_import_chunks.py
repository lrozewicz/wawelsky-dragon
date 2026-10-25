"""Zapis chunków, obrazów i wektorów importu bazy wiedzy (K19 §2/§5, CONTRACT E7-1b §2).

Etap ``chunks`` (i ``vectors``, gdy paczka je niesie): czyta ``chunks.jsonl`` strumieniowo,
partiami ≤ 1000 w jednej transakcji, i zapisuje wiersze 1:1 — bez ponownego embeddingu (T5).
Kolumny pochodne liczy ``app/text/fulltext.py`` tak samo jak ingestia (DEC-328). Chunki wchodzą
od razu ``committed=1`` i ``available`` z paczki (dataset jest „w toku" do finalizacji T7).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import chunk_vectors, chunks_import
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories.chunks import chunk_id
from app.db.repositories.chunks_import import ChunkImportRow
from app.db.uow import transaction
from app.services.kb_import_write import ImportPlan, ImportProgress
from app.services.kb_package.format import IMAGES_PREFIX
from app.services.kb_package.reader import PackageReader
from app.storage.keys import image_key
from app.text.fulltext import ft_text, stem_text
from app.worker.errors import PermanentError

if TYPE_CHECKING:
    from app.core.container import Container
    from app.services.kb_package.format import ChunkLine
    from app.services.kb_package.validate import ValidatedPackage

__all__ = ["write_chunks"]

CHUNK_BATCH = 1000  # partie chunków/wektorów w jednej transakcji (K19 §2)
COPY_CHUNK_SIZE = 1 << 20  # kawałek strumienia przy kopiowaniu obrazu z paczki
DEFAULT_EMBED_SOURCE = "content"  # DB ENUM NOT NULL — gdy paczka niesie null
MISSING_VECTOR = "Paczka nie ma wektora dla każdego chunka"
EXTRA_VECTOR = "Paczka ma więcej wektorów niż chunków"
_SENTINEL = object()


async def write_chunks(  # noqa: PLR0913 — sygnatura z CONTRACT E7-1b §2
    container: Container,
    *,
    pkg: ValidatedPackage,
    plan: ImportPlan,
    doc_ids: dict[str, str],
    progress: ImportProgress,
    with_vectors: bool,
) -> dict[str, str]:
    """Zapisuje chunki paczki i zwraca mapę ``chunk_ref → new_chunk_id``.

    ``with_vectors=True``: wektory z ``reader.vectors()`` w kolejności ``chunks.jsonl`` wchodzą
    w tej samej transakcji co partia chunków (liczba ≠ liczba chunków → ``PermanentError``).
    ``with_vectors=False`` (reembed): tylko chunki, wektory dopisze T5. Obrazy ``images/<sha>``
    trafiają do storage pod ``image_key(dataset_id, sha)`` (deduplikacja po sha), a
    ``chunks.image_id`` przyjmuje ``{dataset_id}-{sha}`` — format trasy ``/documents/images/{id}``.
    """
    reader = PackageReader(pkg)
    names = {line.ref: line.name for line in reader.documents()}
    total = pkg.manifest.counts.chunks
    vectors = reader.vectors() if with_vectors else None
    ref_to_id: dict[str, str] = {}
    deferred_parents: dict[str, str] = {}  # chunk_id → parent_ref (rodzic jeszcze nieznany)
    copied_images: set[str] = set()
    done = 0
    batch: list[ChunkImportRow] = []
    vec_rows: list[tuple[str, str, list[float]]] = []
    for line in reader.chunks():
        document_id = doc_ids[line.document_ref]
        new_id = chunk_id(document_id, plan.task_public_id, line.ordinal)
        image_id = None
        if line.image_sha256:
            image_id = await _ensure_image(
                container, reader, plan.dataset_id, line.image_sha256, copied_images
            )
        parent_id = ref_to_id.get(line.parent_ref) if line.parent_ref else None
        if line.parent_ref and parent_id is None:
            deferred_parents[new_id] = line.parent_ref
        batch.append(
            _row(line, plan, document_id, new_id, names[line.document_ref], image_id, parent_id)
        )
        ref_to_id[line.ref] = new_id
        if vectors is not None:
            vec_rows.append((new_id, plan.dataset_id, _pull_vector(vectors)))
        if len(batch) >= CHUNK_BATCH:
            done = await _flush(
                container, plan, batch, vec_rows, progress, done, total, with_vectors
            )
            batch, vec_rows = [], []
    if batch:
        done = await _flush(container, plan, batch, vec_rows, progress, done, total, with_vectors)
    if vectors is not None and next(vectors, _SENTINEL) is not _SENTINEL:
        raise PermanentError(EXTRA_VECTOR)
    await _finalize(container, plan, doc_ids, ref_to_id, deferred_parents)
    return ref_to_id


def _row(  # noqa: PLR0913, PLR0917 — pola wiersza z linii paczki i kontekstu importu
    line: ChunkLine,
    plan: ImportPlan,
    document_id: str,
    new_id: str,
    name: str,
    image_id: str | None,
    parent_id: str | None,
) -> ChunkImportRow:
    """``ChunkLine`` + pola pochodne → ``ChunkImportRow`` (kolumny liczone jak ingestia)."""
    keywords = line.keywords
    questions = line.questions
    return ChunkImportRow(
        id=new_id,
        document_id=document_id,
        dataset_id=plan.dataset_id,
        ordinal=line.ordinal,
        chunk_type=line.chunk_type,
        content=line.content,
        content_llm=line.content_llm,
        content_ft=ft_text(line.content),
        content_stem=stem_text(line.content),
        title_ft=ft_text(Path(name).stem),
        keywords=keywords,
        questions=questions,
        important_ft=ft_text(" ".join(keywords)),
        question_ft=ft_text("\n".join(questions)),
        tags=line.tags,
        positions=line.positions,
        page_from=line.page_from,
        page_to=line.page_to,
        image_id=image_id,
        parent_id=parent_id,
        available=line.available,
        token_count=line.token_count,
        embed_source=line.embed_source or DEFAULT_EMBED_SOURCE,
    )


async def _flush(  # noqa: PLR0913, PLR0917 — partia, wektory i stan postępu z pętli zapisu
    container: Container,
    plan: ImportPlan,
    batch: list[ChunkImportRow],
    vec_rows: list[tuple[str, str, list[float]]],
    progress: ImportProgress,
    done: int,
    total: int,
    with_vectors: bool,
) -> int:
    """Zapisuje partię (chunki + wektory) w jednej transakcji i raportuje postęp."""
    await progress.check_cancel()
    now_ms = container.clock.now_ms()
    async with transaction(_sessionmaker(container)) as session:
        await chunks_import.insert_many(session, batch, now_ms=now_ms)
        if with_vectors:
            await chunk_vectors.insert_many(session, plan.embedding_dim, vec_rows)
    done += len(batch)
    await progress.stage("chunks", done, total)
    if with_vectors:
        await progress.stage("vectors", done, total)
    return done


async def _finalize(
    container: Container,
    plan: ImportPlan,
    doc_ids: dict[str, str],
    ref_to_id: dict[str, str],
    deferred_parents: dict[str, str],
) -> None:
    """Drugi przebieg ``parent_id`` + przeliczenie liczników dokumentów i datasetu (T3 p. 6).

    Walidator paczki gwarantuje, że każdy ``parent_ref`` istnieje w ``ref``-ach chunków, więc brak
    wpisu w ``ref_to_id`` to błąd programistyczny (``KeyError``), nie cichy NULL (E7-1z §3).
    """
    now_ms = container.clock.now_ms()
    parents = {cid: ref_to_id[ref] for cid, ref in deferred_parents.items()}
    async with transaction(_sessionmaker(container)) as session:
        await chunks_import.set_parent_ids(session, parents, now_ms=now_ms)
        for document_id in doc_ids.values():
            await chunks_repo.recount_document(session, document_id, now_ms=now_ms)
        await datasets_repo.recount(session, plan.dataset_id, now_ms=now_ms)


async def _ensure_image(
    container: Container,
    reader: PackageReader,
    dataset_id: str,
    sha: str,
    copied: set[str],
) -> str:
    """Kopiuje obraz ``images/<sha>`` raz na dataset; zwraca ``chunks.image_id`` (``{ds}-{sha}``).

    ID obrazu = ``{dataset_id}-{sha}`` (``documents_files.image`` dzieli je po pierwszym myślniku).
    """
    if sha not in copied:
        key = image_key(dataset_id, sha)
        with reader.open_entry(f"{IMAGES_PREFIX}{sha}") as fp:
            await container.storage.put(key, _stream(fp))
        copied.add(sha)
    return f"{dataset_id}-{sha}"


async def _stream(fp: BinaryIO) -> AsyncIterator[bytes]:
    """Kawałki otwartego wpisu paczki; ``Storage.put`` przyjmuje async iterator (C3)."""
    while True:
        chunk = await asyncio.to_thread(fp.read, COPY_CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


def _pull_vector(vectors: Iterator[list[float]]) -> list[float]:
    """Kolejny wektor paczki; brak → ``PermanentError`` (liczba ≠ liczba chunków)."""
    try:
        return next(vectors)
    except StopIteration as exc:
        raise PermanentError(MISSING_VECTOR) from exc


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker
