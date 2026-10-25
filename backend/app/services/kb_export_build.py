"""Strumieniowa budowa paczki ``.wdkb.zip`` dla zadania ``export_dataset`` (CONTRACT E7-1a §3).

``build_package`` składa paczkę etapami ``files → chunks → vectors → finalize`` bez trzymania
całego datasetu w pamięci: dokumenty i chunki lecą partiami z ``kb_export_data`` do plików
tymczasowych w ``<storage_root>/tmp`` (potem wpis ZIP strumieniem), pliki i obrazy przez
``container.storage.open()`` (``kb_export_files``), wektory przez ``NpyWriter`` na pliku
tymczasowym. Dedup: ten sam plik/obraz = jeden wpis ``files/<sha>``/``images/<sha>``. Każdy
wyjątek (także ``TaskCancelled``) wywołuje ``writer.abort()`` (usuwa ``.part``) i leci dalej;
pliki tymczasowe są usuwane zawsze. Brak pliku dokumentu/obrazu → ``null`` w linii, bez
przerywania eksportu.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.timeutil import from_ms
from app.core.version import APP_VERSION
from app.db.repositories import kb_export_data as export_data
from app.db.repositories import wd_settings
from app.db.uow import transaction
from app.services import kb_export_files as files
from app.services.kb_export_link import export_file_name, export_package_path
from app.services.kb_package import format as fmt
from app.services.kb_package.format import (
    Manifest,
    ManifestCounts,
    ManifestDataset,
    ManifestEmbedding,
)
from app.services.kb_package.writer import PackageWriter

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = ["BuildResult", "ManifestTooLarge", "PackageTooLarge", "build_package"]

# Komunikat ``ValueError`` z ``PackageWriter`` przy przekroczeniu ``export_max_bytes`` (§3).
PACKAGE_TOO_LARGE = "package too large"


class ManifestTooLarge(Exception):
    """Manifest przekracza ``MANIFEST_MAX_BYTES`` — porażka trwała ``manifest_too_large``."""


class PackageTooLarge(Exception):
    """Paczka przekracza ``export_max_bytes`` — porażka trwała ``package_too_large``."""


@dataclass(frozen=True)
class BuildResult:
    """Wynik budowy paczki: rozmiar, nazwa pliku i liczniki (CONTRACT §3)."""

    size_bytes: int
    file_name: str
    documents: int
    chunks: int
    vectors: int


class ExportProgress(Protocol):
    """Postęp budowy: zapis etapu i sprawdzenie Stopu (CONTRACT §3)."""

    async def stage(self, stage: str, done: int, total: int) -> None: ...

    async def check_cancel(self) -> None: ...


async def build_package(
    container: Container,
    *,
    task_id: str,
    dataset_id: str,
    include_vectors: bool,
    progress: ExportProgress,
) -> BuildResult:
    """Buduje paczkę ``exports/<task_id>.wdkb.zip``; wyjątki → ``writer.abort()`` i dalej."""
    path = export_package_path(container.settings.storage_root, task_id)
    writer = PackageWriter(path, max_bytes=container.settings.export_max_bytes)
    tmp_paths: list[Path] = []
    try:
        return await _build(
            container,
            writer=writer,
            dataset_id=dataset_id,
            include_vectors=include_vectors,
            progress=progress,
            tmp_paths=tmp_paths,
        )
    except ValueError as exc:
        writer.abort()
        if PACKAGE_TOO_LARGE in str(exc):
            raise PackageTooLarge(str(exc)) from exc
        raise
    except BaseException:
        writer.abort()
        raise
    finally:
        files.remove_tmp(tmp_paths)


async def _build(  # noqa: PLR0913 — kontekst budowy spięty z sygnaturą publiczną
    container: Container,
    *,
    writer: PackageWriter,
    dataset_id: str,
    include_vectors: bool,
    progress: ExportProgress,
    tmp_paths: list[Path],
) -> BuildResult:
    """Etapy budowy: files → chunks → vectors → finalize (CONTRACT §3)."""
    sessionmaker = _sessionmaker(container)
    async with transaction(sessionmaker) as session:
        dataset = await export_data.dataset_manifest_row(session, dataset_id)
        if dataset is None:
            raise ValueError(f"dataset not found: {dataset_id}")
        total_documents = await export_data.count_documents(session, dataset_id)
        total_chunks = await export_data.count_chunks(session, dataset_id)
    dimension = int(dataset["embedding_dim"])
    model_name = str(dataset["embedding_model"])

    doc_refs = await _write_documents(
        container,
        writer=writer,
        sessionmaker=sessionmaker,
        dataset_id=dataset_id,
        total=total_documents,
        progress=progress,
        tmp_paths=tmp_paths,
    )
    documents = len(doc_refs)
    chunk_ids = await _write_chunks(
        container,
        writer=writer,
        sessionmaker=sessionmaker,
        dataset_id=dataset_id,
        doc_refs=doc_refs,
        total=total_chunks,
        progress=progress,
        tmp_paths=tmp_paths,
    )
    if include_vectors:
        await _write_vectors(
            container,
            writer=writer,
            sessionmaker=sessionmaker,
            dimension=dimension,
            chunk_ids=chunk_ids,
            progress=progress,
            tmp_paths=tmp_paths,
        )

    manifest = await _manifest(
        container,
        sessionmaker=sessionmaker,
        dataset=dataset,
        dimension=dimension,
        model_name=model_name,
        include_vectors=include_vectors,
        documents=documents,
        chunks=total_chunks,
    )
    if len(manifest.model_dump_json().encode("utf-8")) > fmt.MANIFEST_MAX_BYTES:
        raise ManifestTooLarge("Manifest paczki przekracza limit 1 MB")
    await progress.stage("finalize", 1, 1)
    size = writer.finish(manifest)
    return BuildResult(
        size_bytes=size,
        file_name=export_file_name(str(dataset["name"])),
        documents=documents,
        chunks=total_chunks,
        vectors=total_chunks if include_vectors else 0,
    )


async def _write_documents(  # noqa: PLR0913 — etap z pełnym kontekstem budowy
    container: Container,
    *,
    writer: PackageWriter,
    sessionmaker: async_sessionmaker[AsyncSession],
    dataset_id: str,
    total: int,
    progress: ExportProgress,
    tmp_paths: list[Path],
) -> dict[str, str]:
    """Etap ``files``: wpisy plików (dedup) i ``documents.jsonl``; zwraca mapę ``id → ref``."""
    path, fp = files.open_tmp(container, tmp_paths)
    seen: set[str] = set()
    refs: dict[str, str] = {}
    done = 0
    async with transaction(sessionmaker) as session:
        async for batch in export_data.iter_documents(session, dataset_id):
            for row in batch:
                await progress.check_cancel()
                ref = f"d{done + 1}"
                sha = await files.add_document_file(
                    container, writer, row=row, seen=seen, tmp_paths=tmp_paths
                )
                fp.write(files.jsonl(files.document_line(ref, row, sha)))
                refs[str(row["id"])] = ref
                done += 1
                await progress.stage("files", done, total)
    fp.close()
    writer.add_file(fmt.DOCUMENTS_PATH, files.read_blocks(path))
    return refs


async def _write_chunks(  # noqa: PLR0913 — etap z pełnym kontekstem budowy
    container: Container,
    *,
    writer: PackageWriter,
    sessionmaker: async_sessionmaker[AsyncSession],
    dataset_id: str,
    doc_refs: dict[str, str],
    total: int,
    progress: ExportProgress,
    tmp_paths: list[Path],
) -> list[str]:
    """Etap ``chunks``: wpisy obrazów (dedup), ``chunks.jsonl``; zwraca id-y w kolejności linii."""
    path, fp = files.open_tmp(container, tmp_paths)
    images: set[str] = set()
    chunk_refs: dict[str, str] = {}
    chunk_ids: list[str] = []
    done = 0
    async with transaction(sessionmaker) as session:
        async for batch in export_data.iter_chunks(session, dataset_id):
            await progress.check_cancel()
            for row in batch:
                chunk_id = str(row["id"])
                ref = f"c{done + 1}"
                document_ref = doc_refs.get(str(row["document_id"]))
                image_sha = await files.add_chunk_image(
                    container, writer, dataset_id=dataset_id, row=row, seen=images
                )
                parent_id = row["parent_id"]
                parent_ref = chunk_refs.get(str(parent_id)) if parent_id else None
                line = files.chunk_line(ref, row, document_ref, image_sha, parent_ref)
                fp.write(files.jsonl(line))
                chunk_refs[chunk_id] = ref
                chunk_ids.append(chunk_id)
                done += 1
            await progress.stage("chunks", done, total)
    fp.close()
    writer.add_file(fmt.CHUNKS_PATH, files.read_blocks(path))
    return chunk_ids


async def _write_vectors(  # noqa: PLR0913 — etap z pełnym kontekstem budowy
    container: Container,
    *,
    writer: PackageWriter,
    sessionmaker: async_sessionmaker[AsyncSession],
    dimension: int,
    chunk_ids: list[str],
    progress: ExportProgress,
    tmp_paths: list[Path],
) -> None:
    """Etap ``vectors``: ``vectors/%06d.npy`` po ``VECTOR_PART_ROWS`` wierszy, kolejność chunków."""
    total = len(chunk_ids)
    batch_size = export_data.CHUNKS_BATCH
    part_index = 0
    rows_in_part = 0
    path, fp = files.open_tmp(container, tmp_paths)
    npy = fmt.NpyWriter(fp, dimension)
    done = 0
    async with transaction(sessionmaker) as session:
        for start in range(0, total, batch_size):
            await progress.check_cancel()
            batch = chunk_ids[start : start + batch_size]
            vectors = await export_data.fetch_vectors(session, dimension, batch)
            for chunk_id in batch:
                # Brak wektora w tabeli: wiersz zerowy trzyma spójność counts.vectors == chunks
                # (walidator paczki wymaga 1:1); zapisane wektory są zawsze w tej tabeli.
                npy.write_rows([vectors.get(chunk_id) or [0.0] * dimension])
                rows_in_part += 1
                done += 1
                if rows_in_part >= fmt.VECTOR_PART_ROWS:
                    part_index, rows_in_part = _finish_vector_part(
                        writer, npy=npy, fp=fp, path=path, part_index=part_index
                    )
                    path, fp = files.open_tmp(container, tmp_paths)
                    npy = fmt.NpyWriter(fp, dimension)
            await progress.stage("vectors", done, total)
    if rows_in_part > 0:
        _finish_vector_part(writer, npy=npy, fp=fp, path=path, part_index=part_index)
    else:
        npy.close()
        fp.close()


def _finish_vector_part(
    writer: PackageWriter, *, npy: fmt.NpyWriter, fp: BinaryIO, path: Path, part_index: int
) -> tuple[int, int]:
    """Zamyka ``NpyWriter``, dokłada część wektorów do ZIP; zwraca (numer części, 0 wierszy)."""
    npy.close()
    fp.close()
    writer.add_file(fmt.vector_part_path(part_index), files.read_blocks(path))
    return part_index + 1, 0


async def _manifest(  # noqa: PLR0913 — wszystkie pola manifestu z kontekstu budowy
    container: Container,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    dataset: RowMapping,
    dimension: int,
    model_name: str,
    include_vectors: bool,
    documents: int,
    chunks: int,
) -> Manifest:
    """Manifest paczki (K19 §2): dataset, embedding, liczniki, ``source_instance_id``."""
    now_ms = container.clock.now_ms()
    async with transaction(sessionmaker) as session:
        instance_id = await wd_settings.get_or_create_instance_id(
            session, new_id=uuid.uuid4().hex, now_ms=now_ms
        )
    return Manifest(
        format=fmt.FORMAT_NAME,
        schema_version=fmt.SCHEMA_VERSION,
        wd_version=APP_VERSION,
        created_at=from_ms(now_ms).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_instance_id=instance_id,
        dataset=ManifestDataset(
            name=str(dataset["name"]),
            description=dataset["description"],
            language=str(dataset["language"]),
            chunk_method=str(dataset["chunk_method"]),
            parser_config=files.json_value(dataset["parser_config"]),
            similarity_threshold=float(dataset["similarity_threshold"]),
            vector_similarity_weight=float(dataset["vector_similarity_weight"]),
            pagerank=int(dataset["pagerank"]),
        ),
        embedding=ManifestEmbedding(
            model_name=model_name, dimension=dimension, included=include_vectors
        ),
        counts=ManifestCounts(
            documents=documents, chunks=chunks, vectors=chunks if include_vectors else 0
        ),
        entries=[],
    )


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → ``RuntimeError``."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker
