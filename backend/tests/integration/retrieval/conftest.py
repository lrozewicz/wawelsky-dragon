"""Fixture'y i pomocniki testów repozytorium retrievalu (brief T3, kontrakt M7)."""

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.container import Container
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import chunk_vectors as chunk_vectors_repo
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import models as models_repo
from app.db.repositories.chunks import ChunkInsert, chunk_id
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from app.domain.policy.principal import Principal
from app.services.ingest_pipeline import run_parse
from app.text.fulltext import ft_text, stem_text
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME_MS, make_document_row
from tests.integration.ingest.pipeline_helpers import claim_context, make_container, make_source


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


async def insert_document(
    sm: async_sessionmaker[AsyncSession],
    dataset: DatasetRow,
    *,
    name: str = "dok.txt",
    enabled: bool = True,
    meta: dict[str, Any] | None = None,
) -> str:
    """Wstawia dokument (documents.insert); gdy trzeba — nadpisuje enabled/meta_fields."""
    row = make_document_row(dataset, name=name)
    async with transaction(sm) as session:
        await documents_repo.insert(session, row)
        if not enabled or meta is not None:
            await session.execute(
                sa_text("UPDATE documents SET enabled = :e, meta_fields = :m WHERE id = :id"),
                {
                    "id": row.id,
                    "e": int(enabled),
                    "m": json.dumps(meta if meta is not None else {}, ensure_ascii=False),
                },
            )
    return row.id


async def insert_chunk(  # noqa: PLR0913 — kształt pomocnika z briefu T3
    sm: async_sessionmaker[AsyncSession],
    dataset_id: str,
    document_id: str,
    *,
    ordinal: int,
    text: str,
    title: str = "",
    keywords: Sequence[str] = (),
    questions: Sequence[str] = (),
    committed: bool = True,
    available: bool = True,
    vector: Sequence[float] | None = None,
    dim: int = 4,
) -> str:
    """Wstawia chunk z kolumnami FT policzonymi jak w ingesii (app.text.fulltext).

    Gdy podano vector — najpierw ensure_table (DDL → niejawny COMMIT), potem chunk
    i wektor w tej samej transakcji. FULLTEXT widzi wiersz dopiero po COMMIT —
    zapytania testowe wykonuj w OSOBNEJ, późniejszej transakcji.
    """
    cid = chunk_id(document_id, "t" * 32, ordinal)
    row = ChunkInsert(
        id=cid,
        document_id=document_id,
        dataset_id=dataset_id,
        task_id=1,
        ordinal=ordinal,
        chunk_type="text",
        content=text,
        content_llm=None,
        content_ft=ft_text(text),
        content_stem=stem_text(ft_text(text)),
        title_ft=ft_text(title),
        keywords=tuple(keywords),
        questions=tuple(questions),
        important_ft=ft_text(" ".join(keywords)),
        question_ft=ft_text("\n".join(questions)),
        positions=(),
        page_from=None,
        page_to=None,
        token_count=5,
        embed_source="content",
    )
    async with transaction(sm) as session:
        if vector is not None:
            await chunk_vectors_repo.ensure_table(session, dim)
        await chunks_repo.insert_many(session, [row], now_ms=TIME_MS)
        await session.execute(
            sa_text("UPDATE chunks SET committed = :c, available = :a WHERE id = :id"),
            {"id": cid, "c": int(committed), "a": int(available)},
        )
        if vector is not None:
            await chunk_vectors_repo.insert_many(session, dim, [(cid, dataset_id, vector)])
    return cid


# --- Poniżej: fixture'y i pomocniki testow uslugi retrievalu (brief T5, kontrakt M6) ---


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener z progami retrievalu wg briefu T5; storage w tmp_path, modele fake."""
    settings = migrated_db.model_copy(
        update={
            "min_vector_sim": 0.25,
            "min_rerank_score": 0.1,
            "retrieval_fusion": "weighted",
        }
    )
    instance = await make_container(settings, tmp_path)
    yield instance
    await instance.aclose()


async def ingest_text(container: Container, dataset: DatasetRow, name: str, text: str) -> str:
    """Ingestia tekstu przez realny pipeline (upload → claim → run_parse); id dokumentu."""
    doc = await container.ingest.upload(
        dataset.id, make_source(text.encode(), name), created_by=dataset.tenant_id
    )
    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)
    return doc.id


def principal_for(user_id: str, *, superuser: bool = False) -> Principal:
    """Principal JWT dla user_id (brief T5)."""
    return Principal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        is_superuser=superuser,
        is_service=False,
        auth_kind="jwt",
    )


async def register_rerank(sm: async_sessionmaker[AsyncSession]) -> None:
    """Rejestruje model fake-rerank (brief T5)."""
    async with transaction(sm) as session:
        await models_repo.insert(
            session,
            id="r" * 32,
            name="fake-rerank",
            model_type="rerank",
            is_default=False,
            now_ms=TIME_MS,
        )
