"""Testy gotowości na prawdziwej MariaDB (kontrakt C5/C6) — tabelę alembic_version stawiamy
ręcznie, bo migracja to osobne zadanie T2."""

import pymysql
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.health import check_ready
from app.db.schema import SCHEMA_HEAD
from app.main import create_app

pytestmark = pytest.mark.db

_OK = 200
_CREATE_VERSION = "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"


async def test_check_ready_no_table(db_engine: AsyncEngine) -> None:
    """Brak tabeli alembic_version → "schema not migrated"."""
    assert await check_ready(db_engine) == f"schema not migrated (expected {SCHEMA_HEAD})"


async def test_check_ready_empty_table(db_engine: AsyncEngine) -> None:
    """Tabela jest, wierszy brak → "schema not migrated"."""
    async with db_engine.begin() as conn:
        await conn.execute(text(_CREATE_VERSION))
    assert await check_ready(db_engine) == f"schema not migrated (expected {SCHEMA_HEAD})"


async def test_check_ready_wrong_version(db_engine: AsyncEngine) -> None:
    """Wiersz '0000' → "schema version 0000 != expected <SCHEMA_HEAD>"."""
    async with db_engine.begin() as conn:
        await conn.execute(text(_CREATE_VERSION))
        await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0000')"))
    assert await check_ready(db_engine) == f"schema version 0000 != expected {SCHEMA_HEAD}"


async def test_check_ready_at_head(db_engine: AsyncEngine) -> None:
    """Wiersz == SCHEMA_HEAD → None (gotowe)."""
    async with db_engine.begin() as conn:
        await conn.execute(text(_CREATE_VERSION))
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": SCHEMA_HEAD}
        )
    assert await check_ready(db_engine) is None


def test_endpoint_ready(fresh_db: Settings) -> None:
    """Endpoint: tabela + wiersz SCHEMA_HEAD przez pymysql jako db_user → 200 {"status":"ready"}."""
    conn = pymysql.connect(
        host=fresh_db.db_host,
        port=fresh_db.db_port,
        user=fresh_db.db_user,
        password=fresh_db.db_password.get_secret_value(),
        database=fresh_db.db_name,
        autocommit=True,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_VERSION)
            cursor.execute("INSERT INTO alembic_version (version_num) VALUES (%s)", (SCHEMA_HEAD,))
    finally:
        conn.close()
    app = create_app(fresh_db)
    with TestClient(app) as client:
        resp = client.get("/health/ready")
    assert resp.status_code == _OK
    assert resp.json() == {"status": "ready"}
