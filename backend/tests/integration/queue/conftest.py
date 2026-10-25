"""Fixture'y testów kolejki zadań (brief T2, kontrakt C12)."""

import uuid
from collections.abc import AsyncIterator

import pymysql
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from tests.integration.db.helpers import alembic_cfg

# Wartości mixin czasu dla wierszy testowych (create_time/create_date/update_time/update_date).
TIME = "2026-09-27 00:00:00.000"
TIME_MS = 1790157600000


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


def insert_document(settings: Settings) -> tuple[str, str]:
    """Wstawia users → datasets → documents przez pymysql (jak _connect w test_migration).

    Zwraca (dataset_id, document_id); spełnia FK tasks.document_id → documents(id).
    """
    user_id = uuid.uuid4().hex
    dataset_id = uuid.uuid4().hex
    document_id = uuid.uuid4().hex
    connection = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        database=settings.db_name,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, f"{user_id}@example.com", "seed", TIME_MS, TIME, TIME_MS, TIME),
            )
            cursor.execute(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    dataset_id,
                    user_id,
                    user_id,
                    "Kolejka",
                    "openai/text-embedding-3-large",
                    3072,
                    TIME_MS,
                    TIME,
                    TIME_MS,
                    TIME,
                ),
            )
            cursor.execute(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type,"
                " location, content_hash, chunk_method, parser_config, create_time,"
                " create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    document_id,
                    dataset_id,
                    user_id,
                    "doc.pdf",
                    "pdf",
                    "doc",
                    f"files/{dataset_id}/{document_id}/original.pdf",
                    "0" * 32,
                    "naive",
                    "{}",
                    TIME_MS,
                    TIME,
                    TIME_MS,
                    TIME,
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return dataset_id, document_id
