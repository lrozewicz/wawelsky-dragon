"""Testy fazy `documents` etapu `documents` (brief T4b, kontrakt §5 i §6) — wymagają MariaDB."""

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest
import xxhash
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.keys import document_key, filemanager_key
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from tests.integration.ragflow_migrate.conftest import FIXTURES_DIR, SourceDb, WdDb, source_writer

pytestmark = pytest.mark.db

#: Etapy poprzedzające `documents` w biegu (kolejność `ORDER`).
STAGES = ["users", "models", "datasets", "documents"]

KB1_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f01"
KB2_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f02"
KB3_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f03"
DOC_F01 = "f1a2b3c4d5e60718293a4b5c6d7e8f01"  # raport.pdf (kb1)
DOC_F02 = "f1a2b3c4d5e60718293a4b5c6d7e8f02"  # umowa.docx (kb1)
DOC_F03 = "f1a2b3c4d5e60718293a4b5c6d7e8f03"  # faq.html (kb2, zły rozmiar)
DOC_F04 = "f1a2b3c4d5e60718293a4b5c6d7e8f04"  # ankieta.csv (kb2, brak bloba)
DOC_F05 = "f1a2b3c4d5e60718293a4b5c6d7e8f05"  # notatki.txt (kb3)
DOC_F06 = "f1a2b3c4d5e60718293a4b5c6d7e8f06"  # stare.md (kb3, zlinkowany z plikiem 809)
FILE_F06 = "0a1b2c3d4e5f60718293a4b5c6d7e809"  # zalacznik.txt (plik lokalny z dokumentem)
FOLDER_MOJE = "0a1b2c3d4e5f60718293a4b5c6d7e808"
CREATED_BY = "b0a1c2d3e4f5061728394a5b6c7d8e91"  # admin
CREATED_BY_ALICE = "b0a1c2d3e4f5061728394a5b6c7d8e92"  # alice (dokumenty kb3)

SOURCE_DOCUMENTS = 6
SOURCE_FILES = 10
#: Wiersze fazy `file2document` (T4c) — etap `documents` sumuje fazy (kontrakt §5 i §12).
SOURCE_LINKS = 4
#: Łączna liczba wierszy źródłowych etapu = `files` + `documents` + `file2document`.
STAGE_ROWS = SOURCE_FILES + SOURCE_DOCUMENTS + SOURCE_LINKS
MISMATCH_DECLARED = 2048
MISMATCH_ACTUAL = 17
MISSING_FILE_ERROR = "migration: blob missing"

#: Oczekiwania per dokument: (kb_id, location-bucket, location, chunk_method, size, suffix, type).
#: Rozmiary f01/f02 to rzeczywiste bajty plików z `make_binaries.py` (te same w `data.sql`).
EXPECTED = {
    DOC_F01: (KB1_ID, "raport.pdf", "naive", 1578, "pdf", "pdf", "raport.pdf"),
    DOC_F02: (KB1_ID, "umowa.docx", "naive", 36808, "docx", "docx", "umowa.docx"),
    DOC_F03: (KB2_ID, "faq.html", "qa", 2048, "html", "html", "faq.html"),
    DOC_F04: (KB2_ID, "ankieta.csv", "qa", 777, "csv", "csv", "ankieta.csv"),
    DOC_F05: (KB3_ID, "notatki.txt", "book", 20, "txt", "txt", "notatki.txt"),
    DOC_F06: (KB3_ID, "stare.md", "book", 22, "md", "md", "stare.md"),
}

DOC_COLUMNS = (
    "id",
    "dataset_id",
    "created_by",
    "name",
    "suffix",
    "type",
    "size",
    "location",
    "content_hash",
    "source_type",
    "source_ref",
    "chunk_method",
    "parser_config",
    "run",
    "progress",
    "progress_msg",
    "error",
    "process_begin_at",
    "process_duration",
    "chunk_count",
    "token_count",
    "enabled",
    "meta_fields",
    "thumbnail",
)

FILE_COLUMNS = ("id", "name", "location")


def _by_stage(results: list[StageResult], stage: str) -> StageResult:
    """Wynik etapu o podanej nazwie."""
    return next(result for result in results if result.stage == stage)


def _doc_key(document_id: str) -> str:
    """Klucz storage dokumentu (dla f06 współdzielony z plikiem 809, suffix pliku `txt`)."""
    if document_id == DOC_F06:
        return str(filemanager_key(FILE_F06, "txt"))
    bucket, _location, _method, _size, suffix, _type, _name = EXPECTED[document_id]
    return str(document_key(bucket, document_id, suffix))


async def _scalar(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> Any:
    """Pojedyncza wartość z bazy WD (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return result.scalar_one()


async def _document_count(sm: async_sessionmaker[AsyncSession]) -> int:
    """Liczba wierszy `documents`."""
    return int(await _scalar(sm, "SELECT COUNT(*) FROM documents"))


async def _document(sm: async_sessionmaker[AsyncSession], document_id: str) -> dict[str, Any]:
    """Wiersz `documents` o podanym id (kolumny fazy `documents`); brak wiersza → pusta mapa."""
    columns = ", ".join(DOC_COLUMNS)
    async with sm() as session:
        row = (
            (
                await session.execute(
                    text(f"SELECT {columns} FROM documents WHERE id = :id"),  # noqa: S608
                    {"id": document_id},
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row is not None else {}


async def _file(sm: async_sessionmaker[AsyncSession], file_id: str) -> dict[str, Any]:
    """Wiersz `files` o podanym id (id/nazwa/klucz) — dla reguły współdzielenia bloba."""
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


def _issues(result: StageResult, code: str) -> list[Any]:
    """Uwagi etapu o podanym kodzie."""
    return [issue for issue in result.issues if issue.code == code]


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


def _xxh128(path: Path) -> str:
    """xxh128 zawartości pliku (algorytm `content_hash` celu, policzony niezależnie)."""
    return xxhash.xxh128(path.read_bytes()).hexdigest()


def _storage_files(root: Path) -> list[Path]:
    """Pliki w katalogu storage (brak katalogu → pusta lista)."""
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def _source_blob(run_ctx: RunContext, bucket: str, location: str) -> Path:
    """Plik fixture'u w katalogu źródłowym biegu."""
    assert run_ctx.src_files_dir is not None
    return run_ctx.src_files_dir / bucket / location


async def test_first_run_creates_document_rows(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Pierwszy bieg: 6 wierszy `documents` o id źródła, mapowanie kolumn z kontraktu."""
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert result.source_count == STAGE_ROWS
    assert (result.created, result.updated, result.skipped) == (STAGE_ROWS, 0, 0)
    assert result.target_count == STAGE_ROWS
    assert await _document_count(wd_db.sm) == SOURCE_DOCUMENTS

    for document_id, (kb_id, _loc, chunk_method, size, suffix, type_, name) in EXPECTED.items():
        row = await _document(wd_db.sm, document_id)
        assert row["dataset_id"] == kb_id
        assert row["location"] == _doc_key(document_id)
        assert row["run"] == "0"
        assert row["progress"] == 0
        assert row["chunk_count"] == 0
        assert row["token_count"] == 0
        assert row["chunk_method"] == chunk_method
        assert row["type"] == type_
        assert row["size"] == size
        assert row["suffix"] == suffix
        assert row["name"] == name
        assert row["created_by"] == (CREATED_BY_ALICE if kb_id == KB3_ID else CREATED_BY)
        # Dokumenty z mapowań SharePoint dostają `source_ref` (CONTRACT §7 pkt 1, WP E4-6c);
        # ich wartości sprawdza `test_debts_e4_6c.py` — tu tylko reszta dokumentów.
        if document_id not in (DOC_F01, DOC_F02):
            assert row["source_ref"] is None
    assert (await _document(wd_db.sm, DOC_F06))["enabled"] == 0
    assert (await _document(wd_db.sm, DOC_F01))["enabled"] == 1


async def test_first_run_copies_document_blobs(
    source: Source, wd_db: WdDb, run_ctx: RunContext, expectations: dict[str, Any]
) -> None:
    """(b) Bloby dokumentów (f01, f02, f05, f06) skopiowane i zweryfikowane SHA-256."""
    await _migrate(source, wd_db, run_ctx)

    ok = {
        DOC_F01: (KB1_ID, "raport.pdf"),
        DOC_F02: (KB1_ID, "umowa.docx"),
        DOC_F05: (KB3_ID, "notatki.txt"),
        DOC_F06: (FOLDER_MOJE, "zalacznik.txt"),
    }
    for document_id, (bucket, location) in ok.items():
        row = await _document(wd_db.sm, document_id)
        assert row["error"] is None
        assert row["content_hash"] == _xxh128(_source_blob(run_ctx, bucket, location))
        stored = _storage_path(run_ctx, row["location"])
        assert stored.is_file()
        assert hashlib.sha256(stored.read_bytes()).hexdigest() == _blob_sha256(
            expectations, bucket, location
        )
    assert (await _file(wd_db.sm, FILE_F06))["location"] == _doc_key(DOC_F06)


async def test_size_mismatch_marks_row_without_blob(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) f03: zły rozmiar → `content_hash=''`, `error`, brak bloba, `blob_size_mismatch`."""
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    row = await _document(wd_db.sm, DOC_F03)
    assert row["content_hash"] == ""
    assert str(row["error"]).startswith(
        f"migration: blob size mismatch (declared {MISMATCH_DECLARED}, actual "
    )
    assert str(MISMATCH_ACTUAL) in str(row["error"])
    assert not _storage_path(run_ctx, _doc_key(DOC_F03)).exists()
    issues = _issues(result, "blob_size_mismatch")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].ids == [DOC_F03]


async def test_missing_blob_marks_row(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(d) f04: brak bloba → `content_hash=''`, `error`, `blob_missing` z ids dokumentu."""
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    row = await _document(wd_db.sm, DOC_F04)
    assert row["content_hash"] == ""
    assert row["error"] == MISSING_FILE_ERROR
    assert not _storage_path(run_ctx, _doc_key(DOC_F04)).exists()
    issues = _issues(result, "blob_missing")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].ids == [DOC_F04]


async def test_blob_counters_by_entries(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(e) Liczniki blobów po wpisach planu: pierwszy bieg i drugi (`unchanged`)."""
    await _migrate(source, wd_db, run_ctx)
    assert run_ctx.shared["documents_blobs"] == {
        "copied": 5,
        "unchanged": 0,
        "missing": 1,
        "size_mismatch": 1,
    }
    await _migrate(source, wd_db, run_ctx)
    assert run_ctx.shared["documents_blobs"] == {
        "copied": 0,
        "unchanged": 5,
        "missing": 1,
        "size_mismatch": 1,
    }


async def test_second_run_is_idempotent(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """(f) Drugi bieg: `created == updated == 0`, `skipped` = suma faz, storage bez zmian."""
    await _migrate(source, wd_db, run_ctx)
    before = {path: path.stat().st_mtime_ns for path in _storage_files(tmp_path / "wd-storage")}
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert (result.created, result.updated, result.skipped) == (0, 0, STAGE_ROWS)
    assert result.target_count == STAGE_ROWS
    after = {path: path.stat().st_mtime_ns for path in _storage_files(tmp_path / "wd-storage")}
    assert before == after


async def test_document_without_dataset_is_skipped(
    source: Source, wd_db: WdDb, run_ctx: RunContext, ragflow_src: SourceDb
) -> None:
    """(g) Brak datasetu w źródle → dokumenty pominięte z `document_dataset_missing`."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM `knowledgebase` WHERE id = %s", (KB3_ID,))
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    issues = _issues(result, "document_dataset_missing")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].ids == [DOC_F05, DOC_F06]
    assert await _document_count(wd_db.sm) == SOURCE_DOCUMENTS - 2
    assert await _document(wd_db.sm, DOC_F05) == {}
    assert await _document(wd_db.sm, DOC_F06) == {}


async def test_unknown_parser_id_falls_back_to_dataset(
    source: Source, wd_db: WdDb, run_ctx: RunContext, ragflow_src: SourceDb
) -> None:
    """(h) Nieznany `parser_id` → `chunk_method` datasetu celu + `chunk_method_fallback`."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE `document` SET parser_id = %s WHERE id = %s", ("zzz", DOC_F01))
    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert (await _document(wd_db.sm, DOC_F01))["chunk_method"] == "naive"
    issues = _issues(result, "chunk_method_fallback")
    assert len(issues) == 1
    assert issues[0].severity == "info"
    assert issues[0].ids == [DOC_F01]


async def test_changed_blob_updates_single_row(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """(i) Zmiana treści bloba źródłowego → drugi bieg: `updated == 1`, nowy hash, `copied == 1`."""
    src_files = tmp_path / "src-files"
    shutil.copytree(FIXTURES_DIR / "files", src_files)
    run_ctx.src_files_dir = src_files
    await _migrate(source, wd_db, run_ctx)

    blob = src_files / KB1_ID / "raport.pdf"
    # Ten sam rozmiar co blob fixture'u (etap `documents` porównuje rozmiar), inna treść.
    new_content = bytes(EXPECTED[DOC_F01][3])
    assert len(new_content) == EXPECTED[DOC_F01][3]
    blob.write_bytes(new_content)

    result = _by_stage(await _migrate(source, wd_db, run_ctx), "documents")
    assert result.updated == 1
    assert result.created == 0
    row = await _document(wd_db.sm, DOC_F01)
    assert row["content_hash"] == xxhash.xxh128(new_content).hexdigest()
    assert row["error"] is None
    assert _storage_path(run_ctx, row["location"]).read_bytes() == new_content
    assert "blobs" in _issue_codes(result)
    assert run_ctx.shared["documents_blobs"] == {
        "copied": 1,
        "unchanged": 4,
        "missing": 1,
        "size_mismatch": 1,
    }
