"""Etap `integrations` po etapie `documents`: mappings dostają `document_id` (brief T4c, §8).

Bez etapu `documents` (bieg testów T7) dokumentów nie ma jeszcze w celu, więc mappingi dostają
`document_id = NULL` i `warning` `mapping_document_missing`. Po dołożeniu etapu `documents` do
biegu mappingi wskazują dokumenty celu o id z `ragflow_document_id` źródła.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from tests.integration.ragflow_migrate.conftest import WdDb

pytestmark = pytest.mark.db

#: Etapy biegu z dołożonym `documents` (kolejność `ORDER`).
STAGES = ["users", "models", "datasets", "documents", "integrations"]

INTEGRATION_ID = 1
DOC_F01 = "f1a2b3c4d5e60718293a4b5c6d7e8f01"  # `ragflow_document_id` pierwszego mappingu
DOC_F02 = "f1a2b3c4d5e60718293a4b5c6d7e8f02"  # `ragflow_document_id` drugiego mappingu
MAPPINGS = 2
MAPPING_DOCUMENT_MISSING = "mapping_document_missing"


def _by_stage(results: list[StageResult], stage: str) -> StageResult:
    """Wynik etapu o podanej nazwie."""
    return next(result for result in results if result.stage == stage)


async def _document_ids(sm: async_sessionmaker[AsyncSession]) -> list[str]:
    """`document_id` mappingów celu w kolejności `item_id`."""
    async with sm() as session:
        rows = (
            await session.execute(
                text("SELECT document_id FROM integration_item_mappings ORDER BY item_id")
            )
        ).scalars()
        return [str(value) for value in rows]


async def _ids(sm: async_sessionmaker[AsyncSession], sql: str) -> set[str]:
    """Zbiór wartości pierwszej kolumny zapytania (SQL dosłowny z tego pliku)."""
    async with sm() as session:
        return {str(value) for value in (await session.execute(text(sql))).scalars()}


async def test_mappings_point_to_migrated_documents(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Bieg z etapem `documents`: `document_id` mappingu = `ragflow_document_id` źródła."""
    assert await _document_ids(wd_db.sm) == []

    results = await run_all(source, wd_db.sm, run_ctx, only=STAGES)
    integrations = _by_stage(results, "integrations")
    missing = [issue for issue in integrations.issues if issue.code == MAPPING_DOCUMENT_MISSING]
    assert missing == []

    mapping_rows = source.rows(
        "ai_hub_integration_file_mappings",
        where="integration_id = %s",
        params=(INTEGRATION_ID,),
    )
    source_ids = sorted(str(row["ragflow_document_id"]) for row in mapping_rows)
    assert source_ids == [DOC_F01, DOC_F02]
    assert await _document_ids(wd_db.sm) == source_ids
    assert len(await _document_ids(wd_db.sm)) == MAPPINGS
    assert set(await _document_ids(wd_db.sm)) <= await _ids(wd_db.sm, "SELECT id FROM documents")
