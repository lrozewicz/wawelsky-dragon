"""Testy T2 importu bazy wiedzy: dataset + dokumenty + bloby i sprzątanie po nieudanym imporcie.

Kontrakt: K19 §2/§5, `work/wp/E7-1b/CONTRACT.md` §2. Paczki buduje ``PackageWriter`` i przechodzą
``validate_package`` (round-trip jak w testach E7-1f), więc testy ćwiczą realny czytnik paczki.
Rozstrzygnięcia pól spoza briefu (content_hash, dokument bez pliku): DEC-331.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
import xxhash
from sqlalchemy import text

from alembic import command
from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import users as users_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.services.kb_import_write import (
    ImportPlan,
    create_dataset_with_documents,
    remove_partial_import,
)
from app.services.kb_package import format as fmt
from app.services.kb_package.validate import ValidatedPackage, validate_package
from app.services.kb_package.writer import PackageWriter
from app.storage.keys import StorageKey, chunk_image_key, document_key
from app.worker.errors import TaskCancelled
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIMENSION = 1024  # fake-embed-1024
TIME_MS = 1790157600000
FILE_DATA = b"umowa najmu " * 256  # ~3 KB plik dokumentu z paczki
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path (wzór: tests/integration/datasets)."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    yield instance
    await instance.aclose()


class FakeProgress:
    """Fake ``ImportProgress``: zapisuje etapy i potrafi przerwać na N-tym ``check_cancel``."""

    def __init__(self, *, cancel_on_check: int | None = None) -> None:
        self.stages: list[tuple[str, int, int]] = []
        self.checks = 0
        self._cancel_on_check = cancel_on_check

    async def stage(self, stage: str, done: int, total: int) -> None:
        """Zapisuje wywołanie etapu postępu."""
        self.stages.append((stage, done, total))

    async def check_cancel(self) -> None:
        """Liczy wywołania; przy ``cancel_on_check`` rzuca ``TaskCancelled`` (jak handler T7)."""
        self.checks += 1
        if self._cancel_on_check is not None and self.checks >= self._cancel_on_check:
            raise TaskCancelled("task-test")


def _manifest(*, documents: int) -> fmt.Manifest:
    """Manifest paczki testowej (bez wektorów: ``included=false``, ``chunks=0``)."""
    return fmt.Manifest.model_validate(
        {
            "format": fmt.FORMAT_NAME,
            "schema_version": fmt.SCHEMA_VERSION,
            "wd_version": "0.9.0",
            "created_at": "2026-10-12T21:00:00Z",
            "source_instance_id": "0123456789abcdef0123456789abcdef",
            "dataset": {
                "name": "Baza źródłowa",
                "description": "opis źródła",
                "language": "Polish",
                "chunk_method": "naive",
                "parser_config": PARSER_CONFIG,
                "similarity_threshold": 0.35,
                "vector_similarity_weight": 0.45,
                "pagerank": 2,
            },
            "embedding": {"model_name": "bge-m3", "dimension": DIMENSION, "included": False},
            "counts": {"documents": documents, "chunks": 0, "vectors": 0},
            "entries": [],
        }
    )


def _document(ref: str, *, file_sha256: str | None, size: int) -> dict[str, Any]:
    """Linia ``documents.jsonl`` wg K19 §2."""
    return {
        "ref": ref,
        "name": f"umowa-{ref}.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": size,
        "file_sha256": file_sha256,
        "chunk_method": "naive",
        "parser_config": PARSER_CONFIG,
        "meta_fields": {"tag": ref},
        "run": "3",  # DONE — run surowe (K19 §2)
        "progress_msg": "gotowe",
        "token_num": 10,
        "chunk_num": 1,
    }


def _jsonl(rows: Sequence[dict[str, Any]]) -> bytes:
    """Wpis JSONL z linii dokumentów."""
    return b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows)


def _package(
    path: Path, *, documents: Sequence[dict[str, Any]], blobs: dict[str, bytes]
) -> ValidatedPackage:
    """Buduje paczkę przez ``PackageWriter`` i waliduje ją ``validate_package`` (round-trip)."""
    writer = PackageWriter(path, max_bytes=MAX_BYTES)
    writer.add_bytes(fmt.DOCUMENTS_PATH, _jsonl(documents))
    writer.add_bytes(fmt.CHUNKS_PATH, b"")
    for sha, data in blobs.items():
        writer.add_bytes(f"{fmt.FILES_PREFIX}{sha}", data)
    writer.finish(_manifest(documents=len(documents)))
    validated = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(validated, ValidatedPackage), validated  # paczka testowa musi być poprawna
    return validated


def _plan(dataset_id: str, actor_id: str, *, name: str = "Import 1") -> ImportPlan:
    """Plan importu: id ustala wołający (handler T7), model/wymiar docelowy."""
    return ImportPlan(
        dataset_id=dataset_id,
        actor_id=actor_id,
        name=name,
        embedding_model="fake-embed-1024",
        embedding_dim=DIMENSION,
        reembed=False,
        task_public_id="a" * 32,
    )


async def _actor(container: Container) -> str:
    """Wstawia użytkownika-aktora (FK ``datasets.tenant_id`` → ``users``)."""
    user_id = uuid.uuid4().hex
    async with transaction(container.sessionmaker) as session:
        await users_repo.insert(
            session,
            user_id=user_id,
            email=f"{user_id[:12]}@example.com",
            nickname="Importer",
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=False,
            is_service=False,
            now_ms=TIME_MS,
        )
    return user_id


async def _record(container: Container, dataset_id: str) -> datasets_repo.DatasetRecord | None:
    """Rekord datasetu (odczyt testowy w osobnej transakcji)."""
    async with transaction(container.sessionmaker) as session:
        return await datasets_repo.get_record(session, dataset_id)


async def _documents(container: Container, dataset_id: str) -> list[DocumentRow]:
    """Wiersze dokumentów datasetu w kolejności ``create_time, id``."""
    async with transaction(container.sessionmaker) as session:
        ids = await datasets_repo.list_document_ids(session, dataset_id)
        return await documents_repo.get_many(session, ids)


async def _tables(container: Container) -> set[str]:
    """Nazwy tabel bieżącej bazy testowej."""
    async with transaction(container.sessionmaker) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT TABLE_NAME FROM information_schema.TABLES"
                    " WHERE TABLE_SCHEMA = DATABASE()"
                )
            )
        ).scalars()
    return {str(row) for row in rows}


async def _read_blob(container: Container, key: StorageKey) -> bytes:
    """Treść bloba ze storage (odczyt testowy)."""
    return b"".join([chunk async for chunk in container.storage.open(key)])


async def test_import_creates_dataset_documents_and_blobs(
    container: Container, tmp_path: Path
) -> None:
    """Paczka z 2 dokumentami (jeden z plikiem, drugi bez) → dataset, 2 wiersze, bloby, postęp."""
    actor = await _actor(container)
    sha = hashlib.sha256(FILE_DATA).hexdigest()
    documents = [
        _document("d1", file_sha256=sha, size=len(FILE_DATA)),
        _document("d2", file_sha256=None, size=0),
    ]
    pkg = _package(tmp_path / "p.wdkb.zip", documents=documents, blobs={sha: FILE_DATA})
    plan = _plan(uuid.uuid4().hex, actor)
    progress = FakeProgress()

    ids = await create_dataset_with_documents(container, pkg=pkg, plan=plan, progress=progress)

    assert set(ids) == {"d1", "d2"}
    source = pkg.manifest.dataset
    record = await _record(container, plan.dataset_id)
    assert record is not None
    assert (record.id, record.tenant_id, record.created_by) == (plan.dataset_id, actor, actor)
    assert record.name == plan.name
    assert (record.embedding_model, record.embedding_dim) == ("fake-embed-1024", DIMENSION)
    assert record.description == source.description
    assert record.language == source.language
    assert record.chunk_method == source.chunk_method
    assert record.parser_config == source.parser_config
    assert record.similarity_threshold == source.similarity_threshold
    assert record.vector_similarity_weight == source.vector_similarity_weight
    assert record.pagerank == source.pagerank

    rows = await _documents(container, plan.dataset_id)
    assert [row.name for row in rows] == ["umowa-d1.pdf", "umowa-d2.pdf"]
    by_name = {row.name: row for row in rows}
    with_file, without_file = by_name["umowa-d1.pdf"], by_name["umowa-d2.pdf"]
    assert (with_file.dataset_id, with_file.created_by) == (plan.dataset_id, actor)
    assert with_file.run == "1"  # „w toku" — DONE ustawia handler (T7)
    assert with_file.enabled is True
    assert with_file.chunk_count == 0 and with_file.token_count == 0
    assert with_file.size == len(FILE_DATA)
    assert with_file.content_hash == xxhash.xxh128(FILE_DATA).hexdigest()  # xxh128 bloba (DEC-331)
    key = document_key(plan.dataset_id, ids["d1"], "pdf")
    assert with_file.location == str(key)
    assert await _read_blob(container, key) == FILE_DATA
    # Dokument bez pliku: wiersz bez bloba (location = planowany klucz WD, DEC-331)
    assert without_file.run == "1"
    assert without_file.size == 0
    assert without_file.content_hash == ""
    assert without_file.location == str(document_key(plan.dataset_id, ids["d2"], "pdf"))
    assert not await container.storage.exists(StorageKey(without_file.location))

    # Tabela wektorów docelowego wymiaru powstaje w etapie tworzenia datasetu (K19 §5)
    assert f"chunk_vec_d{DIMENSION}" in await _tables(container)

    stages = [stage for stage, _done, _total in progress.stages]
    assert "files" in stages and "documents" in stages
    assert ("files", 1, 1) in progress.stages
    assert ("documents", 2, 2) in progress.stages


async def test_import_copies_shared_blob_to_every_document(
    container: Container, tmp_path: Path
) -> None:
    """Dwa dokumenty o tym samym ``file_sha256`` → każdy dostaje własny klucz w storage."""
    actor = await _actor(container)
    sha = hashlib.sha256(FILE_DATA).hexdigest()
    documents = [
        _document("d1", file_sha256=sha, size=len(FILE_DATA)),
        _document("d2", file_sha256=sha, size=len(FILE_DATA)),
    ]
    pkg = _package(tmp_path / "p.wdkb.zip", documents=documents, blobs={sha: FILE_DATA})
    plan = _plan(uuid.uuid4().hex, actor)

    ids = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )

    assert ids["d1"] != ids["d2"]
    for ref in ("d1", "d2"):
        key = document_key(plan.dataset_id, ids[ref], "pdf")
        assert await _read_blob(container, key) == FILE_DATA


async def test_cancel_during_files_leaves_partial_state_for_cleanup(
    container: Container, tmp_path: Path
) -> None:
    """``TaskCancelled`` przy 2. pliku → wyjątek propaguje, a sprzątanie usuwa wszystko."""
    actor = await _actor(container)
    first, second = b"pierwszy plik", b"drugi plik"
    sha_first = hashlib.sha256(first).hexdigest()
    sha_second = hashlib.sha256(second).hexdigest()
    documents = [
        _document("d1", file_sha256=sha_first, size=len(first)),
        _document("d2", file_sha256=sha_second, size=len(second)),
    ]
    pkg = _package(
        tmp_path / "p.wdkb.zip",
        documents=documents,
        blobs={sha_first: first, sha_second: second},
    )
    plan = _plan(uuid.uuid4().hex, actor)
    progress = FakeProgress(cancel_on_check=2)

    with pytest.raises(TaskCancelled):
        await create_dataset_with_documents(container, pkg=pkg, plan=plan, progress=progress)

    # Ślad po przerwaniu: dataset istnieje, pierwszy blob leży w storage, dokumentów jeszcze nie ma
    assert await _record(container, plan.dataset_id) is not None
    assert (tmp_path / "files" / plan.dataset_id).is_dir()
    assert await _documents(container, plan.dataset_id) == []

    await remove_partial_import(container, dataset_id=plan.dataset_id)

    assert await _record(container, plan.dataset_id) is None
    assert not (tmp_path / "files" / plan.dataset_id).exists()
    await remove_partial_import(container, dataset_id=plan.dataset_id)  # drugie wywołanie = no-op


async def test_remove_partial_import_without_dataset_row_removes_blobs(
    container: Container, tmp_path: Path
) -> None:
    """Bloby ``files/`` i ``images/`` bez wiersza datasetu (przerwanie po „files") → no-op."""
    dataset_id = uuid.uuid4().hex
    key = document_key(dataset_id, uuid.uuid4().hex, "pdf")
    await container.storage.put(key, FILE_DATA)
    assert await container.storage.exists(key)
    image = chunk_image_key(dataset_id, uuid.uuid4().hex)
    await container.storage.put(image, b"png")
    assert await container.storage.exists(image)

    await remove_partial_import(container, dataset_id=dataset_id)

    assert not (tmp_path / "files" / dataset_id).exists()
    assert not (tmp_path / "images" / dataset_id).exists()
    await remove_partial_import(container, dataset_id=dataset_id)  # powtórka = no-op


async def test_retry_after_partial_import_leaves_exactly_one_dataset(
    container: Container, tmp_path: Path
) -> None:
    """Ponowienie zadania (T7: sprzątanie → create) → jeden dataset, dwa dokumenty."""
    actor = await _actor(container)
    sha = hashlib.sha256(FILE_DATA).hexdigest()
    documents = [
        _document("d1", file_sha256=sha, size=len(FILE_DATA)),
        _document("d2", file_sha256=None, size=0),
    ]
    pkg = _package(tmp_path / "p.wdkb.zip", documents=documents, blobs={sha: FILE_DATA})
    plan = _plan(uuid.uuid4().hex, actor)

    first = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )
    await remove_partial_import(container, dataset_id=plan.dataset_id)
    assert await _record(container, plan.dataset_id) is None
    assert await _documents(container, plan.dataset_id) == []

    second = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )

    assert set(second) == {"d1", "d2"}
    assert set(second.values()).isdisjoint(first.values())  # nowe id przy nowej próbie (K19 §2)
    rows = await _documents(container, plan.dataset_id)
    assert len(rows) == len(documents)
    blobs = sorted(p.name for p in (tmp_path / "files" / plan.dataset_id).rglob("original.pdf"))
    assert len(blobs) == 1  # tylko blob dokumentu z plikiem — bez śladu poprzedniej próby
