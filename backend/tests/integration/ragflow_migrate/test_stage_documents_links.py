"""Testy fazy `file2document` etapu `documents` (brief T4c, kontrakt §5) — wymagają MariaDB."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from app.tools.ragflow_migrate.stages.doc_links import run_links
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb, source_writer

pytestmark = pytest.mark.db

#: Etapy poprzedzające `documents` w biegu (kolejność `ORDER`).
STAGES = ["users", "models", "datasets", "documents"]

FILE_F01 = "0a1b2c3d4e5f60718293a4b5c6d7e803"  # raport.pdf (widok kb1)
FILE_F02 = "0a1b2c3d4e5f60718293a4b5c6d7e804"  # umowa.docx (widok kb1)
FILE_F05 = "0a1b2c3d4e5f60718293a4b5c6d7e807"  # notatki.txt (widok kb3)
FILE_F06 = "0a1b2c3d4e5f60718293a4b5c6d7e809"  # zalacznik.txt (plik lokalny z dokumentem)
DOC_F01 = "f1a2b3c4d5e60718293a4b5c6d7e8f01"
DOC_F02 = "f1a2b3c4d5e60718293a4b5c6d7e8f02"
DOC_F05 = "f1a2b3c4d5e60718293a4b5c6d7e8f05"
DOC_F06 = "f1a2b3c4d5e60718293a4b5c6d7e8f06"

#: Pary `(id linku, file_id, document_id)` z fixture'u źródła (data.sql).
LINKS = (
    ("9a8b7c6d5e4f30218293a4b5c6d7e801", FILE_F01, DOC_F01),
    ("9a8b7c6d5e4f30218293a4b5c6d7e802", FILE_F02, DOC_F02),
    ("9a8b7c6d5e4f30218293a4b5c6d7e807", FILE_F05, DOC_F05),
    ("9a8b7c6d5e4f30218293a4b5c6d7e808", FILE_F06, DOC_F06),
)
SOURCE_LINKS = len(LINKS)
#: Id linku dokładanego w teście duplikatu (para `file_id`/`document_id` jak pierwszy link).
DUPLICATE_LINK = "9a8b7c6d5e4f30218293a4b5c6d7e899"

LINK_SKIPPED = "link_skipped"
LINK_DUPLICATE = "link_duplicate"

LINK_COLUMNS = ("id", "file_id", "document_id")

INSERT_DUPLICATE = (
    "INSERT INTO `file2document` (`id`,`create_time`,`create_date`,`update_time`,`update_date`,"
    "`file_id`,`document_id`) VALUES (%s,1759306020000,'2025-10-01 08:07:00',1759306020000,"
    "'2025-10-01 08:07:00',%s,%s)"
)


def _by_stage(results: list[StageResult], stage: str) -> StageResult:
    """Wynik etapu o podanej nazwie."""
    return next(result for result in results if result.stage == stage)


async def _scalar(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> Any:
    """Pojedyncza wartość z bazy WD (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return result.scalar_one()


async def _link_count(sm: async_sessionmaker[AsyncSession]) -> int:
    """Liczba wierszy `file2document`."""
    return int(await _scalar(sm, "SELECT COUNT(*) FROM file2document"))


async def _links(sm: async_sessionmaker[AsyncSession]) -> dict[str, tuple[str, str]]:
    """Mapa `id` → `(file_id, document_id)` wierszy `file2document` celu."""
    columns = ", ".join(LINK_COLUMNS)
    async with sm() as session:
        rows = (
            await session.execute(
                text(f"SELECT {columns} FROM file2document")  # noqa: S608
            )
        ).mappings()
        return {str(row["id"]): (str(row["file_id"]), str(row["document_id"])) for row in rows}


async def _migrate(
    source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any
) -> list[StageResult]:
    """Bieg do etapu `documents` włącznie (kolejność `ORDER`)."""
    return await run_all(source, wd_db.sm, ctx, only=STAGES, **kwargs)


def _issues(result: StageResult, code: str) -> list[Any]:
    """Uwagi etapu o podanym kodzie."""
    return [issue for issue in result.issues if issue.code == code]


async def test_first_run_creates_link_rows(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Pierwszy bieg: 4 wiersze `file2document` o id źródła i zachowanych parach."""
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert _issues(result, LINK_SKIPPED) == []
    assert _issues(result, LINK_DUPLICATE) == []
    assert await _link_count(wd_db.sm) == SOURCE_LINKS
    assert await _links(wd_db.sm) == {
        link_id: (file_id, document_id) for link_id, file_id, document_id in LINKS
    }


async def test_missing_document_skips_link(
    source: Source, wd_db: WdDb, run_ctx: RunContext, ragflow_src: SourceDb
) -> None:
    """(b) Dokumentu nie ma w źródle → `warning link_skipped`, 3 wiersze, brak wiersza f01."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM `document` WHERE id = %s", (DOC_F01,))
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    skipped = _issues(result, LINK_SKIPPED)
    assert len(skipped) == 1
    assert skipped[0].severity == "warning"
    assert skipped[0].ids == [LINKS[0][0]]
    assert await _link_count(wd_db.sm) == SOURCE_LINKS - 1
    assert LINKS[0][0] not in await _links(wd_db.sm)


async def test_duplicate_pair_is_skipped(
    source: Source, wd_db: WdDb, run_ctx: RunContext, ragflow_src: SourceDb
) -> None:
    """(c) Druga para `(file_id, document_id)` innego `id` → `warning link_duplicate`."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(INSERT_DUPLICATE, (DUPLICATE_LINK, FILE_F01, DOC_F01))
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    duplicates = _issues(result, LINK_DUPLICATE)
    assert len(duplicates) == 1
    assert duplicates[0].severity == "warning"
    assert duplicates[0].ids == [DUPLICATE_LINK]
    assert await _link_count(wd_db.sm) == SOURCE_LINKS


async def test_second_run_skips_all_links(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(d) Drugi bieg fazy: `skipped == 4`, nic nowego ani zmienionego."""
    await _migrate(source, wd_db, run_ctx)
    async with wd_db.sm() as session:
        phase = await run_links(
            source.rows("file2document"), session, run_ctx, run_ctx.clock.now_ms()
        )
    assert (phase.created, phase.updated, phase.skipped) == (0, 0, SOURCE_LINKS)
    assert phase.target_count == SOURCE_LINKS
    assert phase.issues == []
