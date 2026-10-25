"""Zgodność głowy migracji Alembic z `SCHEMA_HEAD` (brief T2 p. 7) — bez bazy."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.schema import SCHEMA_HEAD

BACKEND = Path(__file__).resolve().parents[3]


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))


def test_head_equals_schema_head() -> None:
    assert _script_directory().get_current_head() == SCHEMA_HEAD


def test_single_head() -> None:
    assert len(_script_directory().get_heads()) == 1
