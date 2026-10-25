"""Fixture'y testów DB — świeża baza na test (kontrakt C12; przeniesione z tests/integration/db)."""

import os
from collections.abc import AsyncIterator

import pymysql
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.engine import make_engine
from tests.integration.db.helpers import worker_db_name


def _root_connection() -> pymysql.Connection:
    """Połączenie root do zakładania i kasowania baz testowych."""
    return pymysql.connect(
        host=os.environ["WD_DB_HOST"],
        port=int(os.environ["WD_DB_PORT"]),
        user="root",
        password=os.environ.get("WD_TEST_DB_ROOT_PASSWORD", "root-test"),
        autocommit=True,
    )


@pytest.fixture
def fresh_db() -> Settings:
    """Tworzy bazę `wd_t_<8 hex>` (pod xdist `wd_t_<worker>_<8 hex>`) jako root,
    nadaje prawa 'wawelsky'; po teście DROP DATABASE."""
    name = worker_db_name("wd_t")
    conn = _root_connection()
    try:
        with conn.cursor() as cursor:
            # Nazwy bazy nie da się wiązać parametrem (to identyfikator DDL, nie wartość);
            # name pochodzi z uuid4().hex, więc f-string nie wnosi iniekcji.
            create_db = (
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci"
            )
            cursor.execute(create_db)
            grant = f"GRANT ALL PRIVILEGES ON `{name}`.* TO 'wawelsky'@'%'"
            cursor.execute(grant)
    finally:
        conn.close()
    # reszta WD_DB_* (host, port, user, hasło) — Settings czyta z env sam
    yield Settings(env="test", db_name=name)
    conn = _root_connection()
    try:
        with conn.cursor() as cursor:
            drop_db = f"DROP DATABASE IF EXISTS `{name}`"
            cursor.execute(drop_db)
    finally:
        conn.close()


@pytest.fixture
async def db_engine(fresh_db: Settings) -> AsyncIterator[AsyncEngine]:
    """Engine per test na świeżej bazie; po teście dispose."""
    engine = make_engine(fresh_db)
    yield engine
    await engine.dispose()
