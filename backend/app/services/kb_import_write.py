"""Zapis importu bazy wiedzy: dataset, bloby dokumentów i wiersze ``documents`` (K19 §2/§5).

Moduł robi wyłącznie „write" importu — etapy ``files`` i ``documents`` z ``CONTRACT E7-1b`` §2.
Chunki, obrazy i wektory dokłada ``kb_import_chunks`` (T3), a liczniki dokumentów przelicza etap
finalny (T7). Wołający (handler T7) sprząta poprzednią próbę przez ``remove_partial_import``,
dzięki czemu ponowienie zadania kończy się dokładnie jednym datasetem (K19 §5).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.timeutil import from_ms
from app.db.repositories import chunk_vectors
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.services.datasets import DatasetService
from app.services.kb_package.format import FILES_PREFIX
from app.services.kb_package.reader import PackageReader
from app.storage.keys import dataset_prefix, document_key, validate_key

if TYPE_CHECKING:
    from app.core.container import Container
    from app.services.kb_package.format import DocumentLine, Manifest
    from app.services.kb_package.validate import ValidatedPackage

__all__ = [
    "ImportPlan",
    "ImportProgress",
    "create_dataset_with_documents",
    "remove_partial_import",
]

RUN_RUNNING = "1"  # RUN_CODES["RUNNING"] — „w toku" do czasu finalizacji (T7)
SOURCE_TYPE_LOCAL = "local"  # jak upload dokumentu (C4); K19 §2 nie przenosi źródeł integracji
PERMISSION_ME = "me"  # import nie przenosi uprawnień zespołowych (K19 §2)
COPY_CHUNK_SIZE = 1 << 20  # kawałek strumienia przy przepisywaniu bloba z paczki
NO_BLOB_HASH = ""  # znacznik „brak bloba" w documents.content_hash (DEC-331, DEC-133 p. 1)


class ImportProgress(Protocol):
    """Postęp zadania importu — implementuje handler (T7), w testach fake."""

    async def stage(self, stage: str, done: int, total: int) -> None:
        """Zapisuje ``stage``/``done``/``total`` w payloadzie zadania i raportuje heartbeat."""
        ...

    async def check_cancel(self) -> None:
        """Rzuca ``TaskCancelled``, gdy zadanie ma zaplanowane anulowanie."""
        ...


@dataclass(frozen=True)
class ImportPlan:
    """Plan importu: docelowy dataset, aktor i model ustalone przez ``start`` (T4/T6).

    Paczka nie decyduje o id ani o właścicielu: ``dataset_id`` nadaje ``start`` (stałe przy
    ponowieniu), a ``tenant_id`` datasetu to ``actor_id`` (K19 §3, Uprawnienia 6-10).
    """

    dataset_id: str
    actor_id: str
    name: str
    embedding_model: str
    embedding_dim: int
    reembed: bool
    task_public_id: str


async def create_dataset_with_documents(
    container: Container,
    *,
    pkg: ValidatedPackage,
    plan: ImportPlan,
    progress: ImportProgress,
) -> dict[str, str]:
    """Tworzy dataset planu, przepisuje bloby i wstawia wiersze dokumentów z paczki.

    Zwraca mapę ``document_ref → new_document_id``; ``ref`` służy tylko do powiązań wewnątrz
    paczki (K19 §2), a nowe id nadajemy PRZED etapem ``files``, bo klucz bloba zależy od
    ``document_key(dataset_id, document_id, suffix)``. Dokumenty startują w stanie „w toku";
    status końcowy i liczniki ustawia handler po zapisaniu chunków (T7).
    """
    reader = PackageReader(pkg)
    lines = list(reader.documents())
    ids = {line.ref: container.id_gen.new_id() for line in lines}
    await _insert_dataset(container, manifest=pkg.manifest, plan=plan)
    await _ensure_vector_table(container, plan.embedding_dim)
    hashes = await _write_files(container, reader, plan.dataset_id, lines, ids, progress)
    await _insert_documents(
        container, plan=plan, lines=lines, ids=ids, hashes=hashes, progress=progress
    )
    return ids


async def remove_partial_import(container: Container, *, dataset_id: str) -> None:
    """Idempotentnie usuwa ślady importu: dataset, dokumenty i prefiksy storage (K19 §5).

    Wołane przed każdą próbą zadania i po Stopie/porażce. Brak wiersza datasetu nie zwalnia
    z usunięcia blobów — przerwanie po etapie ``files`` zostawia ``files/<dataset_id>/…`` bez
    wiersza w bazie. Powtórne wywołanie (także na nieistniejącym id) jest no-opem.
    """
    async with transaction(_sessionmaker(container)) as session:
        record = await datasets_repo.get_record(session, dataset_id)
    if record is not None:
        await DatasetService(container).purge(record)
        return
    await _delete_prefixes(container, dataset_id)


async def _delete_prefixes(container: Container, dataset_id: str) -> None:
    """Prefiksy storage datasetu: oryginały dokumentów i obrazy chunków (C1.2)."""
    await container.storage.delete_prefix(dataset_prefix(dataset_id))
    await container.storage.delete_prefix(validate_key(f"images/{dataset_id}"))


async def _insert_dataset(container: Container, *, manifest: Manifest, plan: ImportPlan) -> None:
    """Wiersz ``datasets``: nazwa i model docelowy z planu, reszta pól z ``manifest.dataset``."""
    source = manifest.dataset
    now = container.clock.now_ms()
    async with transaction(_sessionmaker(container)) as session:
        await datasets_repo.insert(
            session,
            id=plan.dataset_id,
            tenant_id=plan.actor_id,
            created_by=plan.actor_id,
            name=plan.name,
            description=source.description,
            avatar=None,
            language=source.language,
            embedding_model=plan.embedding_model,
            embedding_dim=plan.embedding_dim,
            permission=PERMISSION_ME,
            chunk_method=source.chunk_method,
            parser_config=source.parser_config,
            now_ms=now,
        )
        # Progi retrievalu nie wchodzą do INSERT-u datasetu (kontrakt C1.1) — dokładamy je osobno.
        await datasets_repo.update_fields(
            session,
            plan.dataset_id,
            {
                "similarity_threshold": source.similarity_threshold,
                "vector_similarity_weight": source.vector_similarity_weight,
                "pagerank": source.pagerank,
            },
            now_ms=now,
        )


async def _ensure_vector_table(container: Container, dim: int) -> None:
    """Tabela ``chunk_vec_d<dim>`` w OSOBNEJ transakcji — DDL w MariaDB robi niejawny COMMIT."""
    async with transaction(_sessionmaker(container)) as session:
        await chunk_vectors.ensure_table(session, dim)


async def _write_files(  # noqa: PLR0913, PLR0917 — wewnętrzna: czytnik, id, plan i postęp
    container: Container,
    reader: PackageReader,
    dataset_id: str,
    lines: list[DocumentLine],
    ids: dict[str, str],
    progress: ImportProgress,
) -> dict[str, str]:
    """Etap ``files``: ``files/<sha256>`` → ``document_key(...)`` każdego dokumentu z plikiem.

    Blob współdzielony przez kilka dokumentów dostaje osobny klucz przy każdym z nich —
    deduplikacja paczki nie tworzy współdzielenia blobów w WD. Zwraca mapę
    ``document_id → content_hash`` (xxh128 zapisanego bloba, DEC-331); dokumenty bez pliku
    nie mają tam wpisu.
    """
    targets: list[tuple[DocumentLine, str, str]] = []
    for line in lines:
        sha = line.file_sha256
        if sha is not None:
            targets.append((line, ids[line.ref], sha))
    hashes: dict[str, str] = {}
    for done, (line, document_id, sha) in enumerate(targets, start=1):
        await progress.check_cancel()
        key = document_key(dataset_id, document_id, line.suffix)
        with reader.open_entry(f"{FILES_PREFIX}{sha}") as fp:
            stored = await container.storage.put(key, _stream(fp))
        hashes[document_id] = stored.content_hash
        await progress.stage("files", done, len(targets))
    return hashes


async def _stream(fp: BinaryIO) -> AsyncIterator[bytes]:
    """Kawałki otwartego wpisu paczki; ``Storage.put`` przyjmuje async iterator (C3)."""
    while True:
        chunk = await asyncio.to_thread(fp.read, COPY_CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


async def _insert_documents(  # noqa: PLR0913 — wiersz dokumentu bierze udział z paczki i planu
    container: Container,
    *,
    plan: ImportPlan,
    lines: list[DocumentLine],
    ids: dict[str, str],
    hashes: dict[str, str],
    progress: ImportProgress,
) -> None:
    """Etap ``documents``: wiersze ``documents`` z linii ``documents.jsonl`` (DEC-331)."""
    now = container.clock.now_ms()
    total = len(lines)
    async with transaction(_sessionmaker(container)) as session:
        for done, line in enumerate(lines, start=1):
            document_id = ids[line.ref]
            await documents_repo.insert(
                session,
                DocumentRow(
                    id=document_id,
                    dataset_id=plan.dataset_id,
                    created_by=plan.actor_id,
                    name=line.name,
                    suffix=line.suffix,
                    type=line.type,
                    size=line.size,
                    # Klucz planowany także bez bloba (DEC-133 p. 1); content_hash „" = brak pliku.
                    location=document_key(plan.dataset_id, document_id, line.suffix),
                    content_hash=hashes.get(document_id, NO_BLOB_HASH),
                    source_type=SOURCE_TYPE_LOCAL,
                    source_ref=None,
                    chunk_method=line.chunk_method,
                    parser_config=line.parser_config,
                    run=RUN_RUNNING,
                    progress=0.0,
                    progress_msg="",
                    error=None,
                    process_begin_at=None,
                    process_duration=0.0,
                    chunk_count=0,
                    token_count=0,
                    enabled=True,
                    meta_fields=line.meta_fields,
                    thumbnail=None,
                    create_time=now,
                    create_date=from_ms(now),
                    update_time=now,
                    update_date=from_ms(now),
                ),
            )
            await progress.stage("documents", done, total)


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker
