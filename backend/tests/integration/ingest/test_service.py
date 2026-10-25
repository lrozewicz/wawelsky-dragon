"""Testy DocumentIngestService na prawdziwej MariaDB (brief T4, kontrakt C4)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import NotFound, OperationNotAllowed, ValidationFailed
from app.core.ids import UuidV7Generator
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import task_lookup
from app.db.uow import transaction
from app.services.ingest import UploadSource
from tests.fakes.clock import FrozenClock
from tests.integration.ingest.conftest import (
    DEFAULT_PARSER_CONFIG,
    TIME_MS,
    _chunk,
    seed_dataset,
)

pytestmark = pytest.mark.db

_CONTENT = b"Ala ma kota.\n" * 3  # 39 B — treść domyślnego pliku
_HEX_LEN = 32  # xxh128 → 32 znaki hex (digest, content_hash)


async def _aiter(*chunks: bytes) -> AsyncIterator[bytes]:
    """Pomocniczy strumień bajtów jako async generator (brief T4)."""
    for chunk in chunks:
        yield chunk


def _source(content: bytes = _CONTENT, filename: str = "notatka.txt") -> UploadSource:
    """UploadSource z domyślną treścią (39 B) i nazwą .txt."""
    return UploadSource(stream=_aiter(content), filename=filename)


async def _get_doc(
    sm: async_sessionmaker[AsyncSession], document_id: str
) -> documents_repo.DocumentRow | None:
    """Dokument w osobnej transakcji (odczyty testowe)."""
    async with transaction(sm) as session:
        return await documents_repo.get(session, document_id)


async def _count(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> int:
    """Liczba wierszy zwrócona przez SQL (odczyty testowe)."""
    async with transaction(sm) as session:
        rows = (await session.execute(text(sql), params)).scalars().all()
    return len(rows)


async def _mark_done(sm: async_sessionmaker[AsyncSession], public_id: str) -> None:
    """Oznacza zadanie jako done UPDATE-em (symulacja zakończonego parsowania)."""
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE tasks SET status = 'done' WHERE public_id = :p"), {"p": public_id}
        )


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path; po teście aclose (brief T4)."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    yield instance
    await instance.aclose()


async def test_upload_creates_row_and_file(container: Container) -> None:
    """upload: wiersz run='0' z metadanymi datasetu, plik w storage, licznik (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    row = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    assert row.run == "0"
    assert row.suffix == "txt"
    assert row.type == "doc"
    assert row.size == len(_CONTENT)
    assert len(row.content_hash) == _HEX_LEN
    assert row.location == f"files/{ds.id}/{row.id}/original.txt"
    assert await container.storage.exists(row.location) is True
    assert row.chunk_method == ds.chunk_method
    assert row.parser_config == DEFAULT_PARSER_CONFIG
    async with transaction(container.sessionmaker) as session:
        dataset = await datasets_repo.get(session, ds.id)
    assert dataset is not None and dataset.document_count == 1


async def test_upload_with_parse_enqueues_task(container: Container) -> None:
    """upload(parse=True): run='1', process_begin_at, jedno zadanie queued z payload (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    row = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id, parse=True)
    assert row.run == "1"
    assert row.process_begin_at == TIME_MS
    async with transaction(container.sessionmaker) as session:
        tasks = (
            (await session.execute(text("SELECT document_id, status, payload, digest FROM tasks")))
            .mappings()
            .all()
        )
    assert len(tasks) == 1
    task = tasks[0]
    assert task["document_id"] == row.id
    assert task["status"] == "queued"
    assert json.loads(task["payload"]) == {"clear_existing": False}
    assert len(task["digest"]) == _HEX_LEN


async def test_upload_unsupported_suffix(container: Container) -> None:
    """upload x.exe: ValidationFailed przed zapisem — 0 dokumentów, brak katalogu (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    with pytest.raises(ValidationFailed, match="file type not supported"):
        await container.ingest.upload(ds.id, _source(filename="x.exe"), created_by=ds.tenant_id)
    assert await _count(container.sessionmaker, "SELECT id FROM documents") == 0
    assert not (container.storage.root / "files" / ds.id).exists()


async def test_upload_missing_dataset(container: Container) -> None:
    """upload do nieistniejącego datasetu → NotFound (brief T4)."""
    await seed_dataset(container.sessionmaker)
    with pytest.raises(NotFound, match="dataset not found"):
        await container.ingest.upload("0" * 32, _source(), created_by="u" * 32)


async def test_upload_exceeds_limit(container: Container) -> None:
    """Strumień 2 MiB przy max_upload_mb=1 → ValidationFailed, 0 dokumentów (brief T4)."""
    container.settings = container.settings.model_copy(update={"max_upload_mb": 1})
    ds = await seed_dataset(container.sessionmaker)
    big = UploadSource(
        stream=_aiter(b"a" * 700_000, b"a" * 700_000, b"a" * 700_000), filename="big.txt"
    )
    with pytest.raises(ValidationFailed, match="exceeds limit"):
        await container.ingest.upload(ds.id, big, created_by=ds.tenant_id)
    assert await _count(container.sessionmaker, "SELECT id FROM documents") == 0


async def test_enqueue_parse_twice_rejected(container: Container) -> None:
    """Drugie enqueue_parse na dokumencie z zadaniem queued → OperationNotAllowed (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    await container.ingest.enqueue_parse([doc.id])
    with pytest.raises(OperationNotAllowed, match="currently being processed"):
        await container.ingest.enqueue_parse([doc.id])
    assert await _count(container.sessionmaker, "SELECT id FROM tasks") == 1


async def test_enqueue_parse_missing_document(container: Container) -> None:
    """enqueue_parse z brakującym id → NotFound, 0 nowych zadań, dokument bez zmian (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    with pytest.raises(NotFound, match="document not found"):
        await container.ingest.enqueue_parse([doc.id, "0" * 32])
    assert await _count(container.sessionmaker, "SELECT id FROM tasks") == 0
    fresh = await _get_doc(container.sessionmaker, doc.id)
    assert fresh is not None and fresh.run == "0" and fresh.process_begin_at is None


async def test_enqueue_parse_many_in_order(container: Container) -> None:
    """enqueue_parse([a, b]): public_id w kolejności; oba dokumenty run='1' (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    a = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    b = await container.ingest.upload(ds.id, _source(filename="drugi.txt"), created_by=ds.tenant_id)
    public_ids = await container.ingest.enqueue_parse([a.id, b.id])
    async with transaction(container.sessionmaker) as session:
        tasks = (
            (await session.execute(text("SELECT public_id, document_id FROM tasks")))
            .mappings()
            .all()
        )
    by_doc = {row["document_id"]: row["public_id"] for row in tasks}
    assert by_doc == {a.id: public_ids[0], b.id: public_ids[1]}
    for doc_id in (a.id, b.id):
        fresh = await _get_doc(container.sessionmaker, doc_id)
        assert fresh is not None
        assert (fresh.run, fresh.progress, fresh.progress_msg) == ("1", 0.0, "")


async def test_cancel_queued(container: Container) -> None:
    """cancel przy zadaniu queued: zwraca 1; dokument run='2', zadanie cancelled (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    (public_id,) = await container.ingest.enqueue_parse([doc.id])
    assert await container.ingest.cancel([doc.id]) == 1
    fresh = await _get_doc(container.sessionmaker, doc.id)
    assert fresh is not None and fresh.run == "2"
    async with transaction(container.sessionmaker) as session:
        status = (
            await session.execute(
                text("SELECT status FROM tasks WHERE public_id = :p"), {"p": public_id}
            )
        ).scalar()
    assert status == "cancelled"


async def test_replace_new_content_enqueues_clear_existing(container: Container) -> None:
    """replace innej treści (poprzednie zadanie done): ten sam id, nowe zadanie clear (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    (public_id,) = await container.ingest.enqueue_parse([doc.id])
    await _mark_done(container.sessionmaker, public_id)
    replaced = await container.ingest.replace(
        doc.id, _source(content=b"Inna tresc dokumentu.\n"), parse=True
    )
    assert replaced.id == doc.id
    assert replaced.content_hash != doc.content_hash
    async with transaction(container.sessionmaker) as session:
        payloads = (
            (await session.execute(text("SELECT payload FROM tasks WHERE status = 'queued'")))
            .scalars()
            .all()
        )
    assert [json.loads(payload) for payload in payloads] == [{"clear_existing": True}]


async def test_replace_same_content_no_new_task(container: Container) -> None:
    """replace tą samą treścią: brak nowego zadania (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    (public_id,) = await container.ingest.enqueue_parse([doc.id])
    await _mark_done(container.sessionmaker, public_id)
    replaced = await container.ingest.replace(doc.id, _source(), parse=True)
    assert replaced.content_hash == doc.content_hash
    assert await _count(container.sessionmaker, "SELECT id FROM tasks") == 1


async def test_replace_changes_suffix(container: Container) -> None:
    """replace na .md: nowy klucz original.md, stary original.txt usunięty po zapisie (brief T4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    replaced = await container.ingest.replace(
        doc.id, _source(content=b"# Tresc\n", filename="notatka.md"), parse=False
    )
    assert replaced.location.endswith("original.md")
    assert await container.storage.exists(doc.location) is False


async def test_replace_with_active_task_rejected(container: Container) -> None:
    """replace(parse=True) przy zadaniu queued: OperationNotAllowed, plik i wiersz bez zmian."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    await container.ingest.enqueue_parse([doc.id])
    with pytest.raises(OperationNotAllowed, match="currently being processed"):
        await container.ingest.replace(doc.id, _source(content=b"Inne.\n"), parse=True)
    fresh = await _get_doc(container.sessionmaker, doc.id)
    assert fresh is not None and fresh.content_hash == doc.content_hash
    assert await container.storage.exists(doc.location) is True


async def test_delete_documents_removes_row_chunks_file(container: Container) -> None:
    """delete z chunkiem: 1 usunięty; brak wiersza, chunków, pliku; liczniki przeliczone."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await container.ingest.upload(ds.id, _source(), created_by=ds.tenant_id)
    (public_id,) = await container.ingest.enqueue_parse([doc.id])
    async with transaction(container.sessionmaker) as session:
        big_id = await task_lookup.internal_id(session, public_id)
    assert big_id is not None
    async with transaction(container.sessionmaker) as session:
        await chunks_repo.insert_many(session, [_chunk(doc.id, ds.id, big_id, 0)], now_ms=TIME_MS)
    assert await container.ingest.delete_documents([doc.id]) == 1
    assert await _get_doc(container.sessionmaker, doc.id) is None
    assert await _count(container.sessionmaker, "SELECT id FROM chunks") == 0
    assert await container.storage.exists(doc.location) is False
    async with transaction(container.sessionmaker) as session:
        dataset = await datasets_repo.get(session, ds.id)
    assert dataset is not None
    assert (dataset.document_count, dataset.chunk_count) == (0, 0)


async def test_replace_missing_document(container: Container) -> None:
    """replace nieistniejącego dokumentu → NotFound (C4)."""
    await seed_dataset(container.sessionmaker)
    with pytest.raises(NotFound, match="document not found"):
        await container.ingest.replace("0" * 32, _source())


async def test_delete_missing_document(container: Container) -> None:
    """delete_documents z nieistniejącym id → NotFound (brief T4)."""
    await seed_dataset(container.sessionmaker)
    with pytest.raises(NotFound, match="document not found"):
        await container.ingest.delete_documents(["0" * 32])
