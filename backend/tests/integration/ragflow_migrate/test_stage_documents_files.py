"""Testy fazy `files` etapu `documents` (brief T4a, kontrakt §5 i §6) — wymagają MariaDB."""

import hashlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.keys import document_key, filemanager_key
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb, source_writer

pytestmark = pytest.mark.db

#: Etapy poprzedzające `documents` w biegu (kolejność `ORDER`).
STAGES = ["users", "models", "datasets", "documents"]

KB1_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f01"
DOC_F01_ID = "f1a2b3c4d5e60718293a4b5c6d7e8f01"  # raport.pdf (kb1)
DOC_F06_ID = "f1a2b3c4d5e60718293a4b5c6d7e8f06"  # stare.md (kb3)

ROOT_A = "0a1b2c3d4e5f60718293a4b5c6d7e801"
KB_DIR_A = "0a1b2c3d4e5f60718293a4b5c6d7e802"
FILE_F01 = "0a1b2c3d4e5f60718293a4b5c6d7e803"  # raport.pdf (widok kb1)
FILE_F02 = "0a1b2c3d4e5f60718293a4b5c6d7e804"  # umowa.docx (widok kb1)
ROOT_B = "0a1b2c3d4e5f60718293a4b5c6d7e805"
KB_DIR_B = "0a1b2c3d4e5f60718293a4b5c6d7e806"
FILE_F05 = "0a1b2c3d4e5f60718293a4b5c6d7e807"  # notatki.txt (widok kb3)
FOLDER_MOJE = "0a1b2c3d4e5f60718293a4b5c6d7e808"
FILE_F06 = "0a1b2c3d4e5f60718293a4b5c6d7e809"  # zalacznik.txt (plik lokalny z dokumentem)
FILE_FREE = "0a1b2c3d4e5f60718293a4b5c6d7e80a"  # notatka-lokalna.txt (plik bez dokumentu)

FOLDERS = (ROOT_A, KB_DIR_A, ROOT_B, KB_DIR_B, FOLDER_MOJE)
SOURCE_FILES = 10
#: Wiersze fazy `documents` (T4b); etap sumuje fazy (kontrakt §5).
SOURCE_DOCUMENTS = 6
#: Wiersze fazy `file2document` (T4c); etap sumuje fazy (kontrakt §5 i §12).
SOURCE_LINKS = 4
#: Łączna liczba wierszy źródłowych etapu `documents` = `files` + `documents` + `file2document`.
STAGE_ROWS = SOURCE_FILES + SOURCE_DOCUMENTS + SOURCE_LINKS
SOURCE_BUCKET = FOLDER_MOJE
LOCAL_BLOB_NAME = "notatka-lokalna.txt"
LOCAL_BLOB_SIZE = 28
MISMATCHED_SIZE = 999

#: Liczniki blobów etapu po pierwszym biegu (kontrakt §6): 4 dokumenty + plik bez dokumentu.
BLOBS_COPIED = 5
BLOBS_MISSING = 1
BLOBS_SIZE_MISMATCH = 1
#: Test złego rozmiaru pliku: plik `…80a` + stały zły rozmiar dokumentu f03 (faza `documents`).
FILE_FIX_SIZE_MISMATCH = BLOBS_SIZE_MISMATCH + 1
#: Kody Issues etapu w dry-runie: uwagi fazy `documents` (wiersze f03, f04) + komunikat `blobs`.
DRY_RUN_ISSUES = ["blob_size_mismatch", "blob_missing", "blobs"]

#: Rodzic spoza źródła (test sieroty).
MISSING_PARENT = "nieistniejacy000000000000000000"

FILE_COLUMNS = (
    "id",
    "tenant_id",
    "parent_id",
    "name",
    "type",
    "size",
    "location",
    "source_type",
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


async def _file_count(sm: async_sessionmaker[AsyncSession]) -> int:
    """Liczba wierszy `files`."""
    return int(await _scalar(sm, "SELECT COUNT(*) FROM files"))


async def _file(sm: async_sessionmaker[AsyncSession], file_id: str) -> dict[str, Any]:
    """Wiersz `files` o podanym id (kolumny fazy `files`); brak wiersza → pusta mapa."""
    columns = ", ".join(FILE_COLUMNS)
    async with sm() as session:
        row = (
            (
                await session.execute(
                    text(f"SELECT {columns} FROM files WHERE id = :id"),  # noqa: S608
                    {"id": file_id},
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row is not None else {}


async def _migrate(
    source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any
) -> list[StageResult]:
    """Bieg do etapu `documents` włącznie (kolejność `ORDER`)."""
    return await run_all(source, wd_db.sm, ctx, only=STAGES, **kwargs)


def _issue_codes(result: StageResult) -> list[str]:
    """Kody uwag etapu w kolejności."""
    return [issue.code for issue in result.issues]


def _storage_path(run_ctx: RunContext, key: str) -> Path:
    """Ścieżka klucza w storage testowym biegu."""
    assert run_ctx.storage is not None
    return run_ctx.storage.local_path(key)  # type: ignore[arg-type]


def _blob_sha256(expectations: dict[str, Any], bucket: str, location: str) -> str:
    """SHA-256 zawartości bloba fixture'u z `expectations['blobs']`."""
    return next(
        str(blob["sha256"])
        for blob in expectations["blobs"]
        if blob["bucket"] == bucket and blob["location"] == location
    )


def _storage_files(root: Path) -> list[Path]:
    """Pliki w katalogu storage (brak katalogu → pusta lista)."""
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


async def test_first_run_creates_file_tree(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Pierwszy bieg: 10 wierszy `files`, drzewo od korzeni, `location` i `source_type`.

    Liczniki etapu to suma faz (`files` + `documents`, kontrakt §5); faza `documents` wypełnia
    je liczbą dokumentów źródła (T4b), więc tabelę `files` sprawdzamy osobno.
    """
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert result.source_count == STAGE_ROWS
    assert (result.created, result.updated, result.skipped) == (STAGE_ROWS, 0, 0)
    assert result.target_count == STAGE_ROWS
    assert await _file_count(wd_db.sm) == SOURCE_FILES

    assert (await _file(wd_db.sm, ROOT_A))["parent_id"] is None
    assert (await _file(wd_db.sm, KB_DIR_A))["parent_id"] == ROOT_A
    assert (await _file(wd_db.sm, FILE_F01))["parent_id"] == KB_DIR_A
    assert (await _file(wd_db.sm, ROOT_B))["parent_id"] is None
    assert (await _file(wd_db.sm, FOLDER_MOJE))["parent_id"] == ROOT_B
    assert (await _file(wd_db.sm, FILE_F06))["parent_id"] == FOLDER_MOJE

    assert (await _file(wd_db.sm, FILE_F01))["location"] == str(
        document_key(KB1_ID, DOC_F01_ID, "pdf")
    )
    assert (await _file(wd_db.sm, FILE_F06))["location"] == str(filemanager_key(FILE_F06, "txt"))
    for folder_id in FOLDERS:
        assert (await _file(wd_db.sm, folder_id))["location"] is None

    assert (await _file(wd_db.sm, FILE_F01))["source_type"] == "knowledgebase"
    assert (await _file(wd_db.sm, FILE_F06))["source_type"] == "local"
    assert (await _file(wd_db.sm, ROOT_A))["name"] == "/"
    assert (await _file(wd_db.sm, FILE_FREE))["size"] == LOCAL_BLOB_SIZE


async def test_stage_copies_file_blobs_and_counts_entries(
    source: Source, wd_db: WdDb, run_ctx: RunContext, expectations: dict[str, Any]
) -> None:
    """(b) Blob pliku bez dokumentu skopiowany; liczniki blobów po wpisach planu (kontrakt §6).

    Bloby współdzielone z dokumentem kopiuje faza `documents` (T4b) — stąd w licznikach
    całego etapu także dokumenty f01/f02/f05/f06 oraz braki f04/zły rozmiar f03.
    """
    await _migrate(source, wd_db, run_ctx)

    free_path = _storage_path(run_ctx, str(filemanager_key(FILE_FREE, "txt")))
    assert free_path.is_file()
    digest = hashlib.sha256(free_path.read_bytes()).hexdigest()
    assert digest == _blob_sha256(expectations, SOURCE_BUCKET, LOCAL_BLOB_NAME)
    assert _storage_path(run_ctx, str(filemanager_key(FILE_F06, "txt"))).is_file()

    counters = run_ctx.shared["documents_blobs"]
    assert counters == {
        "copied": BLOBS_COPIED,
        "unchanged": 0,
        "missing": BLOBS_MISSING,
        "size_mismatch": BLOBS_SIZE_MISMATCH,
    }


async def test_second_run_is_idempotent(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(c) Drugi bieg: nic nowego ani zmienionego, blob już w storage (`unchanged`)."""
    first = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert first.created == STAGE_ROWS
    second = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert (second.created, second.updated, second.skipped) == (0, 0, STAGE_ROWS)
    assert second.target_count == STAGE_ROWS
    assert await _file_count(wd_db.sm) == SOURCE_FILES

    counters = run_ctx.shared["documents_blobs"]
    assert counters["unchanged"] >= 1
    assert counters["copied"] == 0


async def test_missing_src_files_dir_is_critical_and_writes_nothing(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(d) Bez `--src-files-dir` etap zwraca `critical` i nic nie pisze (rollback całego biegu)."""
    run_ctx.src_files_dir = None
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    critical = [issue for issue in result.issues if issue.code == "src_files_dir_missing"]
    assert len(critical) == 1
    assert critical[0].severity == "critical"
    assert (result.created, result.updated, result.skipped, result.target_count) == (0, 0, 0, 0)
    assert await _file_count(wd_db.sm) == 0


async def test_orphan_file_is_skipped_with_issue(
    source: Source, wd_db: WdDb, run_ctx: RunContext, ragflow_src: SourceDb
) -> None:
    """(e) Plik z rodzicem spoza źródła → `warning file_orphan` i brak wiersza w `files`."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE `file` SET parent_id = %s WHERE id = %s", (MISSING_PARENT, FILE_FREE)
        )
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    orphans = [issue for issue in result.issues if issue.code == "file_orphan"]
    assert len(orphans) == 1
    assert orphans[0].severity == "warning"
    assert orphans[0].ids == [FILE_FREE]
    assert await _file_count(wd_db.sm) == SOURCE_FILES - 1
    assert await _file(wd_db.sm, FILE_FREE) == {}


async def test_blob_size_mismatch_warns_and_keeps_row(
    source: Source, wd_db: WdDb, run_ctx: RunContext, ragflow_src: SourceDb
) -> None:
    """(f) Zły rozmiar w źródle → `warning file_blob_size_mismatch`; wiersz bez bloba w storage."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE `file` SET size = %s WHERE id = %s", (MISMATCHED_SIZE, FILE_FREE))
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    mismatches = [issue for issue in result.issues if issue.code == "file_blob_size_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0].severity == "warning"
    assert mismatches[0].ids == [FILE_FREE]
    assert (await _file(wd_db.sm, FILE_FREE))["id"] == FILE_FREE
    assert await _file_count(wd_db.sm) == SOURCE_FILES
    assert not _storage_path(run_ctx, str(filemanager_key(FILE_FREE, "txt"))).exists()
    assert run_ctx.shared["documents_blobs"]["size_mismatch"] == FILE_FIX_SIZE_MISMATCH


async def test_dry_run_writes_nothing(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """(g) `dry_run=True`: `files` puste, storage bez plików, liczniki „jakby skopiował”."""
    result = _by_stage(await _migrate(source, wd_db, run_ctx, dry_run=True), "documents")
    assert _issue_codes(result) == DRY_RUN_ISSUES
    assert result.created == STAGE_ROWS
    assert await _file_count(wd_db.sm) == 0
    assert _storage_files(tmp_path / "wd-storage") == []
    assert run_ctx.shared["documents_blobs"]["copied"] == BLOBS_COPIED
