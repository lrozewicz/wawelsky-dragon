"""Fixture'y i pomocniki testów repozytoriów ingestii (brief T2, kontrakt C2)."""

import fcntl
import json
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.timeutil import from_ms
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import tasks as tasks_repo
from app.db.repositories.chunks import ChunkInsert, chunk_id
from app.db.repositories.datasets import DatasetRow
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg


@pytest.fixture
def serialize_fakellm() -> Iterator[None]:
    """Serializuje testy fake-llm plikowym lockiem (stan fake-llm jest globalny, C6).

    ``max_concurrent`` fake-llm jest wspólny dla całego procesu usługi, a ``verify.sh``
    puszcza xdist z domyślnym schedulerem ``load`` — równoległe pliki dorzucają żądania
    i obserwowane maksimum przekracza własny pułap testu. Testy różnych plików
    (``test_concurrency.py``, ``test_pipeline_ocr.py``), które wołają ten fixture, biorą
    tę samą blokadę, więc ich żądania się nie nakładają. Lock trzymamy wyłącznie, gdy
    testy faktycznie biegną (jest ``WD_LLM_BASE_URL``).
    """
    if not os.environ.get("WD_LLM_BASE_URL"):
        yield
        return
    lock_path = Path(tempfile.gettempdir()) / "wd-e5-h8b-fakellm.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# Wartości mixin czasu dla wierszy testowych (jak w tests/integration/queue/conftest.py).
TIME = "2026-09-27 00:00:00.000"
TIME_MS = 1790157600000

DEFAULT_PARSER_CONFIG: dict = {
    "chunk_token_num": 128,
    "delimiter": "\n",
    "layout_recognize": "DeepDOC",
    "auto_keywords": 0,
    "auto_questions": 0,
    "html4excel": False,
    "pages": [[1, 1000000]],
}


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def seed_dataset(
    sm: async_sessionmaker[AsyncSession],
    *,
    embedding_model: str = "fake-embed-1024",
    embedding_dim: int = 1024,
    parser_config: dict | None = None,
    chunk_method: str = "naive",
) -> DatasetRow:
    """Wstawia users i datasets (text() w transakcji); zwraca datasets.get (brief T2)."""
    user_id = uuid.uuid4().hex
    dataset_id = uuid.uuid4().hex
    config = DEFAULT_PARSER_CONFIG if parser_config is None else parser_config
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :email, :nickname, :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": user_id,
                "email": f"{user_id}@example.com",
                "nickname": "seed",
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
        await session.execute(
            text(
                "INSERT INTO datasets (id, tenant_id, created_by, name, language,"
                " embedding_model, embedding_dim, chunk_method, parser_config,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, :name, 'Polish', :model, :dim,"
                " :method, :config, :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": dataset_id,
                "tenant": user_id,
                "name": "Korpus",
                "model": embedding_model,
                "dim": embedding_dim,
                "method": chunk_method,
                "config": json.dumps(config, ensure_ascii=False),
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
        return await datasets_repo.get(session, dataset_id)


def make_document_row(
    dataset: DatasetRow,
    *,
    document_id: str | None = None,
    name: str = "umowa.txt",
    now_ms: int = 1790157600000,
) -> DocumentRow:
    """Buduje pełny DocumentRow do documents.insert (brief T2)."""
    doc_id = document_id or uuid.uuid4().hex
    suffix = name.rsplit(".", 1)[-1] if "." in name else ""
    date = from_ms(now_ms)
    return DocumentRow(
        id=doc_id,
        dataset_id=dataset.id,
        created_by=dataset.tenant_id,
        name=name,
        suffix=suffix,
        type="doc",
        size=10,
        location=f"files/{dataset.id}/{doc_id}/original.{suffix}",
        content_hash="0" * 32,
        source_type="local",
        source_ref=None,
        chunk_method=dataset.chunk_method,
        parser_config=dataset.parser_config,
        run="0",
        progress=0.0,
        progress_msg="",
        error=None,
        process_begin_at=None,
        process_duration=0.0,
        chunk_count=0,
        token_count=0,
        enabled=True,
        meta_fields={},
        thumbnail=None,
        create_time=now_ms,
        create_date=date,
        update_time=now_ms,
        update_date=date,
    )


def _chunk(document_id: str, dataset_id: str, task_id: int, ordinal: int) -> ChunkInsert:
    """Pełny ChunkInsert dla testów (JSON-y i pozycje niepuste).

    Identyfikator z unikalnego „public_id” zadania (klucz po task_id) — różne
    zadania nie kolidują w PRIMARY KEY chunks, jak w realnym przepływie.
    """
    return ChunkInsert(
        id=chunk_id(document_id, str(task_id).zfill(32), ordinal),
        document_id=document_id,
        dataset_id=dataset_id,
        task_id=task_id,
        ordinal=ordinal,
        chunk_type="text",
        content=f"treść {ordinal}",
        content_llm=None,
        content_ft=f"treść {ordinal}",
        content_stem="treś",
        title_ft="tytuł",
        keywords=("a",),
        questions=("q",),
        important_ft="wazne",
        question_ft="pytanie",
        positions=((0, ordinal, 1, 2, 3),),
        page_from=1,
        page_to=2,
        token_count=5,
        embed_source="content",
    )


async def _insert_document(
    sm: async_sessionmaker[AsyncSession], dataset: DatasetRow, *, name: str = "umowa.txt"
) -> DocumentRow:
    """Wstawia dokument z make_document_row; zwraca wiersz wejściowy."""
    row = make_document_row(dataset, name=name)
    async with transaction(sm) as session:
        await documents_repo.insert(session, row)
    return row


async def _get_document(
    sm: async_sessionmaker[AsyncSession], document_id: str
) -> DocumentRow | None:
    """Odczyt dokumentu w osobnej transakcji."""
    async with transaction(sm) as session:
        return await documents_repo.get(session, document_id)


async def _insert_parse_task(
    sm: async_sessionmaker[AsyncSession],
    dataset: DatasetRow,
    document_id: str,
    *,
    task_type: str = "parse_document",
) -> str:
    """Wstawia zadanie queued dla dokumentu; zwraca public_id."""
    pid = uuid.uuid4().hex
    async with transaction(sm) as session:
        await tasks_repo.insert(
            session,
            public_id=pid,
            task_type=task_type,
            payload_json="{}",
            document_id=document_id,
            dataset_id=dataset.id,
            priority=0,
            max_attempts=3,
            digest=None,
            next_attempt_at=TIME_MS,
            now_ms=TIME_MS,
        )
    return pid
