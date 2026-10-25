"""Test seedowania modeli przez `python -m app.tools.migrate` (brief T4, kontrakt C12).

Synchroniczne `def` i subprocess jak w test_migration.py — env.py robi `asyncio.run`.
"""

import os
import subprocess
import sys

import pymysql
import pytest

from app.core.config import Settings
from tests.integration.db.helpers import BACKEND_DIR

pytestmark = pytest.mark.db

SEED_COUNT = 4

SEED_ENV = {
    "WD_LLM_DEFAULT_CHAT": "fake-chat",
    "WD_LLM_DEFAULT_EMBEDDING": "fake-embed-3072",
    "WD_LLM_DEFAULT_RERANK": "fake-rerank",
    "WD_LLM_DEFAULT_VLM": "fake-vision",
}


def _run_migrate(fresh_db: Settings) -> subprocess.CompletedProcess[bytes]:
    """Uruchamia `python -m app.tools.migrate` na bazie testowej `fresh_db` (wzorzec T2)."""
    return subprocess.run(
        [sys.executable, "-m", "app.tools.migrate"],
        cwd=BACKEND_DIR,
        env={**os.environ, "WD_ENV": "test", "WD_DB_NAME": fresh_db.db_name, **SEED_ENV},
        check=False,
        capture_output=True,
        timeout=120,
    )


def _model_count(fresh_db: Settings) -> int:
    """Liczba wierszy w `models` na świeżym połączeniu."""
    connection = pymysql.connect(
        host=fresh_db.db_host,
        port=fresh_db.db_port,
        user=fresh_db.db_user,
        password=fresh_db.db_password.get_secret_value(),
        database=fresh_db.db_name,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM models")
            row = cursor.fetchone()
            assert row is not None
            return int(row[0])
    finally:
        connection.close()


def test_migrate_seeds_default_models(fresh_db: Settings) -> None:
    result = _run_migrate(fresh_db)
    assert result.returncode == 0, result.stderr
    assert _model_count(fresh_db) == SEED_COUNT


def test_migrate_seed_is_idempotent(fresh_db: Settings) -> None:
    assert _run_migrate(fresh_db).returncode == 0
    second = _run_migrate(fresh_db)
    assert second.returncode == 0, second.stderr
    assert _model_count(fresh_db) == SEED_COUNT
