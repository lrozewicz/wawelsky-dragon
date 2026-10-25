"""Testy ``rename_document``/``set_source_meta`` na prawdziwej MariaDB (brief E4-1 T4, K12 §4).

Sprawdzają ARTEFAKT w bazie (``SELECT ... FROM documents``), nie tylko zwrócony wiersz.
"""

import dataclasses
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import NotFound, ValidationFailed
from app.core.ids import UuidV7Generator
from app.db.repositories import documents as documents_repo
from app.db.repositories import tasks as tasks_repo
from app.db.uow import transaction
from tests.fakes.clock import FrozenClock
from tests.integration.ingest.conftest import TIME_MS, make_document_row, seed_dataset

pytestmark = pytest.mark.db

# Wartości nieliczbowe dla wiersza testowego (poza białym zestawem rename/set_source_meta).
_CHUNK_COUNT = 3
_TOKEN_COUNT = 7

# Kolumny, których rename/set_source_meta nie może ruszyć (oraz te, które rusza).
_ARTIFACT_SQL = (
    "SELECT name, suffix, size, location, content_hash, run, progress, chunk_count,"
    " token_count, meta_fields, update_time FROM documents WHERE id = :id"
)


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path; po teście aclose (wzór test_service)."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    yield instance
    await instance.aclose()


async def _insert_doc(
    container: Container,
    dataset: Any,
    *,
    name: str = "a.txt",
    meta_fields: dict[str, Any] | None = None,
    **overrides: Any,
) -> documents_repo.DocumentRow:
    """Wstawia dokument (pełny wiersz) z podanymi meta_fields/nadpisaniami kolumn."""
    row = dataclasses.replace(
        make_document_row(dataset, name=name),
        meta_fields={} if meta_fields is None else meta_fields,
        **overrides,
    )
    async with transaction(container.sessionmaker) as session:
        await documents_repo.insert(session, row)
    return row


async def _artifact(sm: async_sessionmaker[AsyncSession], document_id: str) -> dict[str, Any]:
    """Surowy wiersz artefaktu z bazy (JSON sparsowany)."""
    async with transaction(sm) as session:
        row = (await session.execute(text(_ARTIFACT_SQL), {"id": document_id})).mappings().first()
    assert row is not None
    result = dict(row)
    result["meta_fields"] = json.loads(result["meta_fields"])
    return result


async def _count_tasks(sm: async_sessionmaker[AsyncSession]) -> int:
    """Liczba zadań w kolejce (SELECT COUNT(*))."""
    async with transaction(sm) as session:
        return int((await session.execute(text("SELECT COUNT(*) FROM tasks"))).scalar_one())


async def test_rename_updates_name_wd_source_and_keeps_other_meta_keys(
    container: Container,
) -> None:
    """rename z wd_source: name i wd_source w bazie, klucz "keep" zachowany (K12 §4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await _insert_doc(container, ds, name="a.txt", meta_fields={"keep": 1})
    container.clock.advance(1000)
    fresh = await container.ingest.rename_document(doc.id, "b.txt", wd_source={"item_id": "i"})
    expected = {"keep": 1, "wd_source": {"item_id": "i"}}
    assert fresh.name == "b.txt"
    assert fresh.meta_fields == expected
    assert fresh.update_time == TIME_MS + 1000
    row = await _artifact(container.sessionmaker, doc.id)
    assert row["name"] == "b.txt"
    assert row["meta_fields"] == expected
    assert row["update_time"] == TIME_MS + 1000


async def test_rename_preserves_file_run_and_chunk_fields(container: Container) -> None:
    """rename nie rusza location/content_hash/run/progress/chunk_count/token_count (K12 §4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await _insert_doc(
        container,
        ds,
        name="a.txt",
        location="files/other/original.txt",
        content_hash="a" * 32,
        size=123,
        run="3",
        progress=1.0,
        chunk_count=_CHUNK_COUNT,
        token_count=_TOKEN_COUNT,
    )
    await container.ingest.rename_document(doc.id, "b.txt")
    row = await _artifact(container.sessionmaker, doc.id)
    assert row["name"] == "b.txt"
    assert row["location"] == "files/other/original.txt"
    assert row["content_hash"] == "a" * 32
    assert row["run"] == "3"
    assert row["progress"] == 1.0
    assert row["chunk_count"] == _CHUNK_COUNT
    assert row["token_count"] == _TOKEN_COUNT


async def test_rename_creates_no_task(container: Container) -> None:
    """rename nie tworzy zadania (liczba zadań bez zmian) — mimo obecnego zadania (K12 §4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await _insert_doc(container, ds, name="a.txt")
    async with transaction(container.sessionmaker) as session:
        await tasks_repo.insert(
            session,
            public_id="t" * 32,
            task_type="parse_document",
            payload_json="{}",
            document_id=doc.id,
            dataset_id=ds.id,
            priority=0,
            max_attempts=3,
            digest=None,
            next_attempt_at=TIME_MS,
            now_ms=TIME_MS,
        )
    assert await _count_tasks(container.sessionmaker) == 1
    await container.ingest.rename_document(doc.id, "b.txt", wd_source={"item_id": "i"})
    assert await _count_tasks(container.sessionmaker) == 1


async def test_rename_extension_change_rejected(container: Container) -> None:
    """rename a.txt → a.pdf: ValidationFailed i brak jakiegokolwiek zapisu (K12 §4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await _insert_doc(container, ds, name="a.txt", meta_fields={"keep": 1})
    container.clock.advance(1000)
    with pytest.raises(ValidationFailed):
        await container.ingest.rename_document(doc.id, "a.pdf", wd_source={"item_id": "i"})
    row = await _artifact(container.sessionmaker, doc.id)
    assert row["name"] == "a.txt"
    assert row["meta_fields"] == {"keep": 1}
    assert row["update_time"] == TIME_MS


async def test_rename_without_wd_source_keeps_meta_fields(container: Container) -> None:
    """rename bez wd_source nie rusza meta_fields (K12 §4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await _insert_doc(
        container, ds, name="a.txt", meta_fields={"wd_source": {"old": 1}, "keep": 2}
    )
    fresh = await container.ingest.rename_document(doc.id, "b.txt")
    expected = {"wd_source": {"old": 1}, "keep": 2}
    assert fresh.name == "b.txt"
    assert fresh.meta_fields == expected
    row = await _artifact(container.sessionmaker, doc.id)
    assert row["meta_fields"] == expected


async def test_set_source_meta_sets_key_without_touching_update_time(
    container: Container,
) -> None:
    """set_source_meta ustawia wd_source, zachowuje inne klucze i update_time (K12 §4)."""
    ds = await seed_dataset(container.sessionmaker)
    doc = await _insert_doc(container, ds, name="a.txt", meta_fields={"keep": 1})
    container.clock.advance(5000)
    await container.ingest.set_source_meta(doc.id, {"a": 1})
    row = await _artifact(container.sessionmaker, doc.id)
    assert row["meta_fields"] == {"keep": 1, "wd_source": {"a": 1}}
    assert row["update_time"] == TIME_MS
    assert row["name"] == "a.txt"


async def test_rename_missing_document(container: Container) -> None:
    """rename nieistniejącego dokumentu → NotFound (K12 §4)."""
    await seed_dataset(container.sessionmaker)
    with pytest.raises(NotFound, match="document not found"):
        await container.ingest.rename_document("0" * 32, "b.txt")


async def test_set_source_meta_missing_document(container: Container) -> None:
    """set_source_meta nieistniejącego dokumentu → NotFound (K12 §4)."""
    await seed_dataset(container.sessionmaker)
    with pytest.raises(NotFound, match="document not found"):
        await container.ingest.set_source_meta("0" * 32, {"a": 1})
