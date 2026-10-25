"""Idempotencja, dry-run, rollback i `plan` etapu `documents` (brief T4c, kontrakt §5-§7).

Mutacja `backend/tests/mutations/e4-6b1-dry-run-leaves-blob.patch` (usunięta gałąź `dry_run`
w `blobs.copy_blob` — dry-run zapisuje blob) musi zaczerwienić ten plik — wyrocznia:
`tools/dev/mutation-check.sh backend/tests/mutations/e4-6b1-dry-run-leaves-blob.patch
tests/integration/ragflow_migrate/test_documents_idempotence.py`.
"""

from pathlib import Path
from typing import Any

import pymysql
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tools.ragflow_migrate import stages
from app.tools.ragflow_migrate.runner import plan_all, run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import (
    Issue,
    RunContext,
    StageInventory,
    StageResult,
)
from tests.integration.ragflow_migrate.conftest import WdDb

pytestmark = pytest.mark.db

#: Etapy biegu w tym zadaniu (kolejność `ORDER`).
STAGES = ["users", "models", "datasets", "documents"]

SOURCE_FILES = 10
SOURCE_DOCUMENTS = 6
SOURCE_LINKS = 4
#: Etap `documents` sumuje fazy (kontrakt §5) — łączna liczba wierszy źródłowych etapu.
STAGE_ROWS = SOURCE_FILES + SOURCE_DOCUMENTS + SOURCE_LINKS
#: W fixture żaden wiersz nie jest pomijany u źródła (sieroty/braki datasetu/linki).
SKIPPED_IN_SOURCE = 0

DOC_F03 = "f1a2b3c4d5e60718293a4b5c6d7e8f03"  # faq.html — zły rozmiar bloba
DOC_F04 = "f1a2b3c4d5e60718293a4b5c6d7e8f04"  # ankieta.csv — brak bloba
FILE_FREE = "0a1b2c3d4e5f60718293a4b5c6d7e80a"  # notatka-lokalna.txt (plik bez dokumentu)

#: Liczniki blobów etapu w biegu właściwym i w dry-runie (kontrakt §6).
BLOBS_COPIED = 5
BLOBS_MISSING = 1
BLOBS_SIZE_MISMATCH = 1

#: Tabele celu, które etap zapisuje (do sprawdzeń „nic nie zapisano”).
TABLES = ("files", "documents", "file2document")

#: Kod Issue krytycznej, którą wymusza etap-atrapa (rollback biegu).
CRITICAL_CODE = "boom"


class CriticalStage:
    """Etap-atrapa po `documents`: zwraca Issue `critical`, wymuszając rollback biegu."""

    name = "fake"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz atrapy — biegu nie interesuje."""
        return StageInventory(stage=self.name, source_counts={}, issues=[], not_migrated={})

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapisuje Issue `critical` bez dotykania bazy i storage."""
        return StageResult(
            stage=self.name,
            source_count=0,
            created=0,
            updated=0,
            skipped=0,
            target_count=0,
            issues=[Issue(severity="critical", code=CRITICAL_CODE, message="test", ids=[])],
        )


def _by_stage(results: list[StageResult], stage: str) -> StageResult:
    """Wynik etapu o podanej nazwie."""
    return next(result for result in results if result.stage == stage)


def _issue_codes(result: StageResult) -> list[str]:
    """Kody uwag etapu w kolejności."""
    return [issue.code for issue in result.issues]


async def _count(sm: async_sessionmaker[AsyncSession], table: str) -> int:
    """Liczba wierszy tabeli celu (SQL z tego pliku)."""
    async with sm() as session:
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
        return int(result.scalar_one())


async def _counts(sm: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Liczniki tabel celu etapu `documents`."""
    return {table: await _count(sm, table) for table in TABLES}


def _storage_files(root: Path) -> list[Path]:
    """Pliki w katalogu storage (brak katalogu → pusta lista)."""
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


async def _migrate(
    source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any
) -> list[StageResult]:
    """Bieg do etapu `documents` włącznie (kolejność `ORDER`)."""
    return await run_all(source, wd_db.sm, ctx, only=STAGES, **kwargs)


async def test_second_run_updates_nothing_and_copies_no_blob(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(1) Drugi bieg: `created == updated == 0`, `skipped` = wiersze źródła, `copied == 0`."""
    first = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert (first.created, first.updated, first.skipped) == (STAGE_ROWS, 0, 0)
    assert await _counts(wd_db.sm) == {
        "files": SOURCE_FILES,
        "documents": SOURCE_DOCUMENTS,
        "file2document": SOURCE_LINKS,
    }

    second = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert second.source_count == STAGE_ROWS
    assert (second.created, second.updated) == (0, 0)
    assert second.skipped == STAGE_ROWS - SKIPPED_IN_SOURCE
    assert second.target_count == STAGE_ROWS
    assert run_ctx.shared["documents_blobs"]["copied"] == 0


async def test_dry_run_writes_nothing_and_counts_like_real_run(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """(2) `dry_run=True`: zero wierszy i zero blobów, ale liczniki i uwagi jak w biegu.

    Dry-run nie może nawet założyć katalogów układu storage: `copy_blob` bez gałęzi `dry_run`
    zapisałby bloby (a runner usunąłby same pliki, zostawiając katalogi).
    """
    dry_run = _by_stage(await _migrate(source, wd_db, run_ctx, dry_run=True), "documents")
    assert dry_run.created == STAGE_ROWS
    assert await _counts(wd_db.sm) == dict.fromkeys(TABLES, 0)
    storage_root = tmp_path / "wd-storage"
    assert _storage_files(storage_root) == []
    assert not (storage_root / "files").exists()
    assert not (storage_root / "filemanager").exists()
    assert run_ctx.shared["documents_blobs"] == {
        "copied": BLOBS_COPIED,
        "unchanged": 0,
        "missing": BLOBS_MISSING,
        "size_mismatch": BLOBS_SIZE_MISMATCH,
    }

    real_run = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert _issue_codes(dry_run) == _issue_codes(real_run)
    assert run_ctx.shared["documents_blobs"]["copied"] == BLOBS_COPIED


async def test_critical_after_documents_rolls_back_rows_and_blobs(
    source: Source,
    wd_db: WdDb,
    run_ctx: RunContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(3) Issue `critical` po `documents` → rollback wierszy i usunięcie nowych blobów."""
    monkeypatch.setattr(stages, "ORDER", (*STAGES, CriticalStage.name))
    monkeypatch.setitem(stages.STAGES, CriticalStage.name, CriticalStage())
    results = await run_all(source, wd_db.sm, run_ctx, only=[*STAGES, CriticalStage.name])

    assert [issue.code for issue in results[-1].issues] == [CRITICAL_CODE]
    assert run_ctx.shared["documents_blobs"]["copied"] == BLOBS_COPIED
    assert await _counts(wd_db.sm) == dict.fromkeys(TABLES, 0)
    assert _storage_files(tmp_path / "wd-storage") == []


async def test_source_is_untouched_and_read_only(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(4) Bieg nie zmienia źródła: liczniki tabel równe, połączenie `Source` READ ONLY."""
    before = {table: source.count(table) for table in ("file", "document", "file2document")}
    await _migrate(source, wd_db, run_ctx)
    assert before == {table: source.count(table) for table in before}

    # `_conn` jest prywatne, ale to jedyny sposób, by sprawdzić blokadę zapisu źródła.
    with pytest.raises(pymysql.err.OperationalError), source._conn.cursor() as cursor:
        cursor.execute("UPDATE `file` SET name = 'x' WHERE id = %s", (FILE_FREE,))


async def test_plan_reports_blob_problems_and_writes_nothing(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """(5a) `plan` z `--src-files-dir`: inwentarz i problemy `blob_missing`/`blob_size_mismatch`."""
    inventory = plan_all(source, run_ctx, ["documents"])[0]
    assert inventory.stage == "documents"
    assert inventory.source_counts == {
        "file": SOURCE_FILES,
        "document": SOURCE_DOCUMENTS,
        "file2document": SOURCE_LINKS,
    }
    by_code = {issue.code: issue for issue in inventory.issues}
    assert sorted(by_code) == ["blob_missing", "blob_size_mismatch"]
    assert by_code["blob_missing"].severity == "warning"
    assert by_code["blob_missing"].ids == [DOC_F04]
    assert by_code["blob_size_mismatch"].severity == "warning"
    assert by_code["blob_size_mismatch"].ids == [DOC_F03]

    assert _storage_files(tmp_path / "wd-storage") == []
    assert await _counts(wd_db.sm) == dict.fromkeys(TABLES, 0)


async def test_plan_without_src_files_dir_warns(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(5b) `plan` bez `--src-files-dir`: jedno `warning` `src_files_dir_missing`."""
    run_ctx.src_files_dir = None
    inventory = plan_all(source, run_ctx, ["documents"])[0]
    assert [(issue.code, issue.severity) for issue in inventory.issues] == [
        ("src_files_dir_missing", "warning")
    ]
