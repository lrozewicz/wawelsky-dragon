"""Testy etapu `integrations` na fixture źródła RAGFlow (brief T7, kontrakt §8 i §9) — MariaDB.

Mutacja `backend/tests/mutations/e4-6b1-secret-plaintext.patch` (zapis `secret_enc` bez
szyfrowania) musi zaczerwienić ten plik — wyrocznia:
`tools/dev/mutation-check.sh backend/tests/mutations/e4-6b1-secret-plaintext.patch
tests/integration/ragflow_migrate/test_stage_integrations.py`.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.secrets import decrypt_secret
from app.tools.ragflow_migrate import cli
from app.tools.ragflow_migrate.report import Report
from app.tools.ragflow_migrate.runner import plan_all, run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from tests.integration.ragflow_migrate.conftest import (
    FIXTURES_DIR,
    SourceDb,
    WdDb,
    source_writer,
)

pytestmark = pytest.mark.db

#: Etapy biegu w tym zadaniu: bez `documents` (powstaje równolegle w T4*).
STAGES = ("users", "models", "datasets", "integrations")

INTEGRATION_ID = 1
KB1_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f01"
U1_ID = "b0a1c2d3e4f5061728394a5b6c7d8e91"
DRIVE1 = "b!FIXTUREDRIVE0000000000000001"
DRIVE2 = "b!FIXTUREDRIVE0000000000000002"
DOC1 = "f1a2b3c4d5e60718293a4b5c6d7e8f01"
DOC2 = "f1a2b3c4d5e60718293a4b5c6d7e8f02"
DELTA1 = (
    "https://graph.microsoft.com/v1.0/drives/b!FIXTUREDRIVE0000000000000001/root/delta"
    "?token=FIXTURE-DELTA-TOKEN-1"
)

#: Liczniki etapu: suma po 6 tabelach celu (kontrakt §8, brief pkt 4a).
SOURCE_COUNT = 11
#: `2025-10-01 08:11:00` UTC w milisekundach — czas `*_at` wierszy fixture'u.
SYNC_MS = 1759306260000
#: Wartości `integrations` z fixture'u (kontrakt §8).
MAX_FILE_SIZE_BYTES = 209715200
SCAN_INTERVAL_SECONDS = 300
CLAMPED_SCAN_INTERVAL = 30
#: Liczby wierszy `sync_runs`/`sync_events` w fixture'u i plików raportu CLI (`json` + `md`).
RUN_COUNT = 2
EVENT_COUNT = 3
REPORT_FILES = 2
#: Kody wyjścia CLI (kontrakt §2).
EXIT_OK = 0


async def _count(sm: async_sessionmaker[AsyncSession], table: str) -> int:
    """Liczba wierszy tabeli celu."""
    async with sm() as session:
        return int((await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one())  # noqa: S608


async def _records(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Wiersze zapytania SQL (SQL dosłowny z tego pliku)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]


async def _record(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Pierwszy wiersz zapytania SQL albo pusty słownik."""
    rows = await _records(sm, sql, params)
    return rows[0] if rows else {}


async def _migrate(source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any) -> StageResult:
    """Bieg `users`+`models`+`datasets`+`integrations`; zwraca wynik etapu `integrations`."""
    results = await run_all(source, wd_db.sm, ctx, only=list(STAGES), **kwargs)
    assert [result.stage for result in results] == list(STAGES)
    return results[-1]


def _codes(result: StageResult, code: str) -> list[list[str]]:
    """Id uwag o danym kodzie (kolejność wystąpienia)."""
    return [issue.ids for issue in result.issues if issue.code == code]


async def test_run_migrates_counters_and_ids(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Bieg tworzy 6 tabel celu z zachowaniem id; `owner_id` z datasetu; stan blokady wyzerowany."""
    result = await _migrate(source, wd_db, run_ctx)
    assert (result.source_count, result.created, result.updated, result.skipped) == (
        SOURCE_COUNT,
        11,
        0,
        0,
    )
    assert result.target_count == 1
    assert [issue.code for issue in result.issues] == [
        "mapping_document_missing",
        "mapping_document_missing",
        "run_running_closed",
    ]
    expected_counts = {
        "integrations": 1,
        "integration_sharepoint": 1,
        "integration_containers": 2,
        "integration_sync_runs": 2,
        "integration_sync_events": 3,
        "integration_item_mappings": 2,
    }
    for table, expected in expected_counts.items():
        assert await _count(wd_db.sm, table) == expected, table

    integration = await _record(
        wd_db.sm,
        "SELECT id, type, name, dataset_id, owner_id, config, max_file_size_bytes,"
        " ignored_extensions, scan_interval_seconds, delete_propagation, is_active, is_running,"
        " lock_acquired_at, lock_owner, cancel_requested, last_sync_at, last_sync_status,"
        " created_at, updated_at FROM integrations WHERE id = :id",
        {"id": INTEGRATION_ID},
    )
    assert integration["id"] == INTEGRATION_ID
    assert integration["type"] == "sharepoint"
    assert integration["name"] == "Dokumenty SharePoint"
    assert integration["dataset_id"] == KB1_ID
    assert integration["owner_id"] == U1_ID
    assert integration["config"] == "{}"
    assert integration["max_file_size_bytes"] == MAX_FILE_SIZE_BYTES
    assert integration["scan_interval_seconds"] == SCAN_INTERVAL_SECONDS
    assert integration["is_running"] == 0
    assert integration["lock_acquired_at"] is None
    assert integration["lock_owner"] is None
    assert integration["cancel_requested"] == 0
    assert integration["last_sync_at"] == SYNC_MS
    assert integration["last_sync_status"] == "success"
    assert integration["created_at"] == SYNC_MS
    # `updated_at` źródła ma DEFAULT CURRENT_TIMESTAMP/ON UPDATE — to czas wgrania fixture'u.
    assert integration["updated_at"] >= SYNC_MS


async def test_secret_is_reencrypted_and_never_leaks(
    source: Source, wd_db: WdDb, run_ctx: RunContext, expectations: dict[str, Any]
) -> None:
    """Sekret celu odszyfrowuje się kluczem WD; raport i Issues nie zawierają sekretu ani klucza."""
    result = await _migrate(source, wd_db, run_ctx)
    row = await _record(
        wd_db.sm, "SELECT secret_enc, secret_last4 FROM integrations WHERE id = :id", {"id": 1}
    )
    plaintext = expectations["sharepoint"]["client_secret"]
    wd_key = run_ctx.settings.crypto_key.get_secret_value()
    assert row["secret_enc"].startswith("v1:")
    assert decrypt_secret(wd_key, INTEGRATION_ID, row["secret_enc"]) == plaintext
    assert row["secret_last4"] == plaintext[-4:]

    report = Report(
        mode="run",
        dry_run=False,
        started_at="2025-10-01T08:11:00Z",
        finished_at="2025-10-01T08:11:00Z",
        inventories=[],
        results=[result],
    )
    rendered = json.dumps(report.to_json(), ensure_ascii=False) + report.to_markdown()
    assert plaintext not in rendered
    assert expectations["sharepoint"]["src_crypto_key"] not in rendered


async def test_containers_delta_and_times(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`delta_cursor` = `delta_link` źródła; druga droga bez kursora; czasy `*_at` w ms."""
    await _migrate(source, wd_db, run_ctx)
    first = await _record(
        wd_db.sm,
        "SELECT container_id, name, delta_cursor, last_sync_at, discovered_at"
        " FROM integration_containers WHERE container_id = :id",
        {"id": DRIVE1},
    )
    second = await _record(
        wd_db.sm,
        "SELECT container_id, name, delta_cursor, last_sync_at FROM integration_containers"
        " WHERE container_id = :id",
        {"id": DRIVE2},
    )
    assert first["name"] == "Dokumenty"
    assert first["delta_cursor"] == DELTA1
    assert first["last_sync_at"] == SYNC_MS
    assert first["discovered_at"] == SYNC_MS
    assert second["name"] == "Archiwum"
    assert second["delta_cursor"] is None
    assert second["last_sync_at"] is None


async def test_runs_events_and_mappings(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`running` domknięty jako `failed`; mappings bez dokumentów; poziomy zdarzeń zmapowane."""
    result = await _migrate(source, wd_db, run_ctx)

    runs = await _records(
        wd_db.sm,
        "SELECT id, run_trigger, status, started_at, finished_at FROM integration_sync_runs"
        " ORDER BY id",
    )
    assert [run["id"] for run in runs] == [1, 2]
    assert runs[0]["status"] == "success"
    assert runs[0]["run_trigger"] == "schedule"
    assert runs[1]["status"] == "failed"
    assert runs[1]["finished_at"] == runs[1]["started_at"] == SYNC_MS
    assert _codes(result, "run_running_closed") == [["2"]]

    events = await _records(
        wd_db.sm,
        "SELECT id, level, container_id, container_name FROM integration_sync_events ORDER BY id",
    )
    assert [event["level"] for event in events] == ["info", "warn", "info"]
    assert events[2]["container_id"] == DRIVE2
    assert events[2]["container_name"] == "Archiwum"

    mappings = await _records(
        wd_db.sm,
        "SELECT item_id, document_id, content_tag, last_status, last_error, updated_at"
        " FROM integration_item_mappings ORDER BY item_id",
    )
    assert [mapping["document_id"] for mapping in mappings] == [None, None]
    assert [mapping["content_tag"] for mapping in mappings] == ["etag-fixture-1", "etag-fixture-2"]
    assert [mapping["last_status"] for mapping in mappings] == ["ok", "failed"]
    assert [mapping["last_error"] for mapping in mappings] == [None, "Błąd parsowania."]
    assert [mapping["updated_at"] for mapping in mappings] == [SYNC_MS, SYNC_MS]
    assert _codes(result, "mapping_document_missing") == [[DOC1], [DOC2]]


async def test_second_run_is_idempotent(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """Drugi bieg: `created == updated == 0`, wszystko pominięte, `secret_enc` bez zmian."""
    await _migrate(source, wd_db, run_ctx)
    before = (await _record(wd_db.sm, "SELECT secret_enc FROM integrations WHERE id = 1"))[
        "secret_enc"
    ]
    second = await _migrate(source, wd_db, run_ctx)
    after = (await _record(wd_db.sm, "SELECT secret_enc FROM integrations WHERE id = 1"))[
        "secret_enc"
    ]
    assert (second.created, second.updated, second.skipped) == (0, 0, SOURCE_COUNT)
    assert second.source_count == SOURCE_COUNT
    assert second.target_count == 1
    assert after == before
    assert await _count(wd_db.sm, "integration_sync_events") == EVENT_COUNT


async def test_wrong_source_key_is_critical_and_rolls_back(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Zły klucz źródłowy → `critical sp_decrypt_failed` z id i rollback całego biegu."""
    ctx = replace(run_ctx, src_sp_crypto_key=SecretStr("00" * 32))
    results = await run_all(source, wd_db.sm, ctx, only=list(STAGES))
    integration = results[-1]
    critical = [issue for issue in integration.issues if issue.severity == "critical"]
    assert [issue.code for issue in critical] == ["sp_decrypt_failed"]
    assert critical[0].ids == ["1"]
    assert "00" * 32 not in critical[0].message
    assert await _count(wd_db.sm, "integrations") == 0
    assert await _count(wd_db.sm, "integration_sync_runs") == 0


async def test_missing_source_key_is_critical(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Brak klucza źródłowego → `critical sp_key_missing` z id wszystkich integracji i rollback."""
    ctx = replace(run_ctx, src_sp_crypto_key=None)
    results = await run_all(source, wd_db.sm, ctx, only=list(STAGES))
    critical = [issue for issue in results[-1].issues if issue.severity == "critical"]
    assert [issue.code for issue in critical] == ["sp_key_missing"]
    assert critical[0].ids == ["1"]
    assert await _count(wd_db.sm, "integrations") == 0


async def test_dry_run_writes_nothing(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`--dry-run` → po biegu żadna tabela integracji nie ma wierszy."""
    await run_all(source, wd_db.sm, run_ctx, only=list(STAGES), dry_run=True)
    for table in (
        "integrations",
        "integration_sharepoint",
        "integration_containers",
        "integration_sync_runs",
        "integration_sync_events",
        "integration_item_mappings",
    ):
        assert await _count(wd_db.sm, table) == 0, table


def test_plan_counts_and_validates_key(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`plan` liczy 5 tabel źródłowych, waliduje klucz i nic nie pisze."""
    inventory = plan_all(source, run_ctx, only=["integrations"])[0]
    assert inventory.stage == "integrations"
    assert inventory.source_counts == {
        "ai_hub_sharepoint_integrations": 1,
        "ai_hub_sharepoint_integration_drives": 2,
        "ai_hub_integration_sync_runs": 2,
        "ai_hub_integration_sync_events": 3,
        "ai_hub_integration_file_mappings": 2,
    }
    assert inventory.issues == []

    no_key = plan_all(source, replace(run_ctx, src_sp_crypto_key=None), only=["integrations"])[0]
    assert [issue.code for issue in no_key.issues] == ["sp_key_missing"]
    assert no_key.issues[0].ids == ["1"]


async def test_plan_writes_nothing(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`plan` nie zapisuje wierszy `integrations`."""
    plan_all(source, run_ctx, only=["integrations"])
    assert await _count(wd_db.sm, "integrations") == 0


async def test_scan_interval_is_clamped(
    source: Source, wd_db: WdDb, run_ctx: RunContext, ragflow_src: SourceDb
) -> None:
    """`scan_interval_seconds` < 30 w źródle → 30 w celu i Issue `scan_interval_clamped`."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE ai_hub_sharepoint_integrations SET scan_interval_seconds = 5 WHERE id = 1"
        )
    result = await _migrate(source, wd_db, run_ctx)
    row = await _record(wd_db.sm, "SELECT scan_interval_seconds FROM integrations WHERE id = 1")
    assert row["scan_interval_seconds"] == CLAMPED_SCAN_INTERVAL
    assert _codes(result, "scan_interval_clamped") == [["1"]]


async def test_missing_dataset_skips_integration_but_keeps_runs(
    source: Source, wd_db: WdDb, run_ctx: RunContext, ragflow_src: SourceDb
) -> None:
    """Brak datasetu integracji → pominięta z dziećmi; `sync_runs`/`sync_events` migrowane."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM knowledgebase WHERE id = %s", (KB1_ID,))
    result = await _migrate(source, wd_db, run_ctx)
    assert _codes(result, "integration_dataset_missing") == [["1"]]
    for table in (
        "integrations",
        "integration_sharepoint",
        "integration_containers",
        "integration_item_mappings",
    ):
        assert await _count(wd_db.sm, table) == 0, table
    assert await _count(wd_db.sm, "integration_sync_runs") == RUN_COUNT
    assert await _count(wd_db.sm, "integration_sync_events") == EVENT_COUNT


def test_cli_run_with_source_key_exits_0(
    ragflow_src: SourceDb,
    wd_db: WdDb,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expectations: dict[str, Any],
) -> None:
    """CLI `run` z kluczem źródłowym i mapą modeli → kod 0; bloby zapisane, raport bez sekretu.

    Etap `documents` pisze bloby, więc storage musi trafić w `tmp_path` (domyślne `/data`
    bywa niezapisywalne poza obrazem).
    """
    _export_env(monkeypatch, wd_db)
    monkeypatch.setenv("WD_STORAGE_ROOT", str(tmp_path / "wd-storage"))
    key = expectations["sharepoint"]["src_crypto_key"]
    code = cli.main(
        [
            "run",
            "--src-mysql",
            ragflow_src.dsn,
            "--model-map",
            str(FIXTURES_DIR / "model-map.yaml"),
            "--src-files-dir",
            str(FIXTURES_DIR / "files"),
            "--src-sp-crypto-key",
            key,
            "--report-dir",
            str(tmp_path),
        ]
    )
    assert code == EXIT_OK
    storage = tmp_path / "wd-storage"
    assert [path for path in (storage / "files").rglob("*") if path.is_file()]
    assert [path for path in (storage / "filemanager").rglob("*") if path.is_file()]
    reports = list(tmp_path.glob("migration-report-*.json")) + list(
        tmp_path.glob("migration-report-*.md")
    )
    assert len(reports) == REPORT_FILES
    rendered = "".join(path.read_text(encoding="utf-8") for path in reports)
    assert expectations["sharepoint"]["client_secret"] not in rendered
    assert key not in rendered


def _export_env(monkeypatch: pytest.MonkeyPatch, wd_db: WdDb) -> None:
    """Ustawia env `WD_DB_*` (i `WD_ENV=test`) na bazę docelową testu — CLI tworzy `Settings()`."""
    settings = wd_db.settings
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_DB_HOST", settings.db_host)
    monkeypatch.setenv("WD_DB_PORT", str(settings.db_port))
    monkeypatch.setenv("WD_DB_USER", settings.db_user)
    monkeypatch.setenv("WD_DB_PASSWORD", settings.db_password.get_secret_value())
    monkeypatch.setenv("WD_DB_NAME", settings.db_name)
