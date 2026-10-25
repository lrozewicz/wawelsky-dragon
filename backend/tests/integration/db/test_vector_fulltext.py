"""Testy VECTOR i FULLTEXT na prawdziwej MariaDB (brief T2, K2 §4).

Fixture `migrated` (sync) robi `upgrade head` i zwraca `fresh_db`; dane wspólnym helperem.
"""

import json

import pymysql
import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from app.core.config import Settings
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

USER_ID = "u" * 32
DATASET_ID = "d" * 32
DOCUMENT_ID = "o" * 32
CHUNK_ID = "c000000000000001"
CONTENT_FT = "źródło finansowania projektu"
CONTENT_STEM = "źródł finans projekt"
TIME = "2026-09-27 00:00:00.000"
TIME_COLS = (1, TIME, 1, TIME)  # create_time, create_date, update_time, update_date


def _seed(settings: Settings) -> None:
    """Wstawia user → dataset → document → chunk; commit — FULLTEXT nie widzi niezatwierdzonych."""
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
                (USER_ID, "seed@example.com", "seed", *TIME_COLS),
            )
            cursor.execute(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    DATASET_ID,
                    USER_ID,
                    USER_ID,
                    "korpus",
                    "openai/text-embedding-3-large",
                    3072,
                    *TIME_COLS,
                ),
            )
            cursor.execute(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type,"
                " location, content_hash, chunk_method, parser_config, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    DOCUMENT_ID,
                    DATASET_ID,
                    USER_ID,
                    "test.txt",
                    "txt",
                    "txt",
                    "korpus/test.txt",
                    "0" * 32,
                    "naive",
                    "{}",
                    *TIME_COLS,
                ),
            )
            cursor.execute(
                "INSERT INTO chunks (id, document_id, dataset_id, ordinal, content, content_ft,"
                " content_stem, committed, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    CHUNK_ID,
                    DOCUMENT_ID,
                    DATASET_ID,
                    0,
                    CONTENT_FT,
                    CONTENT_FT,
                    CONTENT_STEM,
                    1,
                    *TIME_COLS,
                ),
            )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def migrated(fresh_db: Settings) -> Settings:
    """Schemat po `upgrade head` + dane testowe; zwraca `fresh_db`."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    _seed(fresh_db)
    return fresh_db


async def test_vector_cosine(migrated: Settings, db_engine: AsyncEngine) -> None:
    vec = json.dumps([1.0] + [0.0] * 3071)
    query_vec = json.dumps([1.0, 1.0] + [0.0] * 3070)
    async with db_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO chunk_vec_d3072 (chunk_id, dataset_id, embedding)"
                " VALUES (:id, :ds, VEC_FromText(:v))"
            ),
            {"id": CHUNK_ID, "ds": DATASET_ID, "v": vec},
        )
        await conn.execute(text("SET @qv = VEC_FromText(:q)"), {"q": query_vec})
        rows = (
            await conn.execute(
                text(
                    "SELECT chunk_id, 1 - VEC_DISTANCE_COSINE(embedding, @qv) AS s"
                    " FROM chunk_vec_d3072 WHERE dataset_id IN :ids"
                    " ORDER BY VEC_DISTANCE_COSINE(embedding, @qv) + 0.0 LIMIT 5"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": [DATASET_ID]},
            )
        ).all()
        await conn.commit()
    assert len(rows) == 1
    assert rows[0][0] == CHUNK_ID
    assert rows[0][1] == pytest.approx(0.7071068, abs=1e-4)


async def test_vector_rejects_wrong_dim(migrated: Settings, db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(
                text(
                    "INSERT INTO chunk_vec_d3072 (chunk_id, dataset_id, embedding)"
                    " VALUES (:id, :ds, VEC_FromText(:v))"
                ),
                {"id": CHUNK_ID, "ds": DATASET_ID, "v": json.dumps([1.0, 2.0, 3.0])},
            )


async def test_fulltext_content_plain_query(migrated: Settings, db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id FROM chunks WHERE MATCH(content_ft) AGAINST(:q IN BOOLEAN MODE)"),
                {"q": "zrodlo"},
            )
        ).all()
    assert [row[0] for row in rows] == [CHUNK_ID]


async def test_fulltext_content_diacritics(migrated: Settings, db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id FROM chunks WHERE MATCH(content_ft) AGAINST(:q IN BOOLEAN MODE)"),
                {"q": "źródło"},
            )
        ).all()
    assert [row[0] for row in rows] == [CHUNK_ID]


async def test_fulltext_stem(migrated: Settings, db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id FROM chunks WHERE MATCH(content_stem) AGAINST(:q IN BOOLEAN MODE)"),
                {"q": "finans"},
            )
        ).all()
    assert [row[0] for row in rows] == [CHUNK_ID]


async def test_cascade_delete_dataset(migrated: Settings, db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO chunk_vec_d3072 (chunk_id, dataset_id, embedding)"
                " VALUES (:id, :ds, VEC_FromText(:v))"
            ),
            {"id": CHUNK_ID, "ds": DATASET_ID, "v": json.dumps([1.0] + [0.0] * 3071)},
        )
        await conn.execute(text("DELETE FROM datasets WHERE id = :id"), {"id": DATASET_ID})
    async with db_engine.connect() as conn:
        chunks = (await conn.execute(text("SELECT COUNT(*) FROM chunks"))).scalar_one()
        vectors = (await conn.execute(text("SELECT COUNT(*) FROM chunk_vec_d3072"))).scalar_one()
    assert chunks == 0
    assert vectors == 0
