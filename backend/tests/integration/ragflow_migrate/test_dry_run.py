"""Test `--dry-run`: po biegu w trybie wycofanym cel jest pusty (brief T7, p. 4).

Mutacja `backend/tests/mutations/e4-6a-dry-run-commits.patch` (gałąź `dry_run` w `runner.py`
commituje zamiast wycofywać) musi zaczerwienić ten plik — wyrocznia:
`tools/dev/mutation-check.sh backend/tests/mutations/e4-6a-dry-run-commits.patch
tests/integration/ragflow_migrate/test_dry_run.py`.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext
from tests.integration.ragflow_migrate.conftest import WdDb

pytestmark = pytest.mark.db

SOURCE_USERS = 3
SOURCE_TOKENS = 4


async def _count(sm: async_sessionmaker[AsyncSession], sql: str) -> int:
    """Liczba wierszy z zapytania `SELECT COUNT(*)` (SQL dosłowny z tego pliku)."""
    async with sm() as session:
        result = await session.execute(text(sql))
        return int(result.scalar_one())


async def test_dry_run_writes_nothing(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`run_all(only=["users","keys"], dry_run=True)`: raport liczy, ale wiersze są wycofane."""
    results = await run_all(source, wd_db.sm, run_ctx, only=["users", "keys"], dry_run=True)
    by_stage = {result.stage: result for result in results}
    assert by_stage["users"].created == SOURCE_USERS
    assert by_stage["keys"].created == SOURCE_TOKENS
    assert by_stage["users"].target_count == SOURCE_USERS
    assert by_stage["keys"].target_count == SOURCE_TOKENS
    assert await _count(wd_db.sm, "SELECT COUNT(*) FROM users") == 0
    assert await _count(wd_db.sm, "SELECT COUNT(*) FROM api_keys") == 0
