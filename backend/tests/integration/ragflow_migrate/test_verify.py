"""Testy integracyjne komendy ``verify`` (brief T4, kontrakt E4-6c §3.2 i §4).

Harness jak w ``test_stage_*.py``: ``ragflow_src``/``source``/``wd_db``/``run_ctx`` i pełny bieg
``run_all(source, wd_db.sm, run_ctx)`` (wszystkie etapy). Brakujące wiersze w celu wywołujemy
surowym SQL-em na ``wd_db.sm``, bo raport czyta wyłącznie stan tabel.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.auth_tokens import sha256_hex
from app.tools.ragflow_migrate import cli
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext
from app.tools.ragflow_migrate.verify import run_verify
from app.tools.ragflow_migrate.verify_types import ContractMismatch, CountEntry, VerifyReport
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

#: Id z fixture'u (data.sql) — te same stałe co w pozostałych testach migracji.
U3_ID = "b0a1c2d3e4f5061728394a5b6c7d8e93"
D1_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f01"
D2_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f02"
DS3_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f03"

#: Id integracji SharePoint źródła (``ai_hub_sharepoint_integrations.id`` = 1).
INTEGRATION_ID = "1"

#: Dokumenty fixture'u z błędem bloba nadanym przez etap ``documents`` (kontrakt §3.2).
DOC_MISSING_BLOB = "f1a2b3c4d5e60718293a4b5c6d7e8f04"
DOC_SIZE_MISMATCH = "f1a2b3c4d5e60718293a4b5c6d7e8f03"

#: Klucz wiersza dostępu fixture'u (``<lower(email)>:<dialog_id>``, kontrakt §3.2).
ACCESS_KEY = f"admin@rf.test:{D1_ID}"

#: Kolejność wpisów ``counts`` (kontrakt §3.2) — stała, nie zależna od danych.
EXPECTED_TABLES: list[str] = [
    "users",
    "datasets",
    "documents",
    "files",
    "chats",
    "chat_sessions",
    "assistant_access",
    "api_keys",
    "integrations",
]

#: Liczby wierszy źródła fixture'u (pełna tabela, po wyłączeniu osieroconych).
EXPECTED_SOURCE: dict[str, int] = {
    "users": 3,
    "datasets": 3,
    "documents": 6,
    "files": 10,
    "chats": 2,
    "chat_sessions": 2,
    "assistant_access": 2,
    "api_keys": 4,
    "integrations": 1,
}

#: Tabele, których brak wierszy jest rozbieżnością krytyczną (kontrakt §3.2).
CRITICAL_TABLES: tuple[str, ...] = (
    "users",
    "chats",
    "assistant_access",
    "integrations",
    "datasets",
    "documents",
    "api_keys",
)

#: Dokument fixture'u (``ankieta.csv``, kb-qa) — kasowany w teście licznika ``documents``.
#: Nie należy do żadnego czatu, więc próbka kontraktowa §6 zostaje czysta.
DOC_ID = "f1a2b3c4d5e60718293a4b5c6d7e8f04"

#: Plik fixture'u (``zalacznik.txt``) — kasowany w teście licznika, który zostaje ``warning``.
FILE_ID = "0a1b2c3d4e5f60718293a4b5c6d7e809"

#: Klucz API boba (``u3``) — nie ma czatu, więc kasowanie nie psuje próbki kontraktowej.
#: Id klucza w WD to ``sha256(token)[:32]`` (``stages/keys.py::_key_id``).
API_KEY_TOKEN = "ragflow-FIXTURE-u3-plain"  # noqa: S105 — token FIKCYJNY z fixture'u
API_KEY_ID = sha256_hex(API_KEY_TOKEN)[:32]

JSON_KEYS = {
    "version",
    "command",
    "started_at",
    "finished_at",
    "ok",
    "counts",
    "files",
    "embedding_mismatch_chats",
    "unmapped_models",
    "orphan_access",
    "parse",
    "contract_sample",
    "issues",
}

REPORT_FILES = 2
EXIT_OK = 0
EXIT_CRITICAL = 2


async def _verify(ragflow_src: SourceDb, wd_db: WdDb, ctx: RunContext) -> VerifyReport:
    """``run_verify`` na źródle fixture'u (połączenie zakłada i zamyka sam test)."""
    src = Source.connect(ragflow_src.dsn)
    try:
        return await run_verify(src, wd_db.settings, ctx)
    finally:
        src.close()


def _entry(report: VerifyReport, table: str) -> CountEntry:
    """Wpis liczników dla tabeli (obecność wpisu jest częścią kontraktu §3.2)."""
    return next(entry for entry in report.counts if entry.table == table)


def _issues(report: VerifyReport, code: str) -> list[Any]:
    """Uwagi raportu o danym kodzie (kontrakt §3.2)."""
    return [issue for issue in report.issues if issue.code == code]


def _count_issue(report: VerifyReport, table: str) -> Any:
    """Uwaga ``count_missing`` tej tabeli (komunikat zawiera nazwę tabeli — kontrakt §3.2).

    Kasowanie wiersza celu pociąga wiersze zależne (``ON DELETE CASCADE``), więc w raporcie
    może być kilka uwag ``count_missing`` — szukamy tej jednej, o którą chodzi w teście.
    """
    return next(
        issue for issue in _issues(report, "count_missing") if f"tabeli {table} " in issue.message
    )


async def _exec(wd_db: WdDb, statements: Sequence[tuple[str, dict[str, Any]]]) -> None:
    """Wykonuje instrukcje SQL w jednej transakcji celu (zapis testu, nie kod migracji)."""
    async with wd_db.sm() as session:
        for sql, params in statements:
            await session.execute(text(sql), params)
        await session.commit()


async def _count(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> int:
    """Pojedyncza liczba z bazy celu (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return int(result.scalar_one())


async def _cli_verify(ragflow_src: SourceDb, tmp_path: Path) -> int:
    """``cli.main(["verify", …])`` na bazie celu testu; ``asyncio.run`` idzie w osobny wątek."""
    return await asyncio.to_thread(
        cli.main,
        [
            "verify",
            "--src-mysql",
            ragflow_src.dsn,
            "--report-dir",
            str(tmp_path),
        ],
    )


def _written_reports(report_dir: Path) -> tuple[list[str], dict[str, Any], str]:
    """Nazwy plików raportu oraz ich JSON i Markdown (I/O poza pętlą zdarzeń testu)."""
    written = sorted(path.name for path in report_dir.iterdir())
    payload = json.loads((report_dir / written[0]).read_text(encoding="utf-8"))
    return written, payload, (report_dir / written[1]).read_text(encoding="utf-8")


def _cli_env(monkeypatch: pytest.MonkeyPatch, wd_db: WdDb, tmp_path: Path) -> None:
    """Env ``WD_*`` na bazę celu testu — ``cli.main`` tworzy ``Settings()`` sam."""
    settings = wd_db.settings
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_DB_HOST", settings.db_host)
    monkeypatch.setenv("WD_DB_PORT", str(settings.db_port))
    monkeypatch.setenv("WD_DB_USER", settings.db_user)
    monkeypatch.setenv("WD_DB_PASSWORD", settings.db_password.get_secret_value())
    monkeypatch.setenv("WD_DB_NAME", settings.db_name)
    monkeypatch.setenv("WD_STORAGE_ROOT", str(tmp_path / "cli-storage"))


async def test_clean_run_after_full_migration(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Czysty bieg: brak uwag krytycznych, liczniki źródła i sekcje plików z fixture'u."""
    await run_all(source, wd_db.sm, run_ctx)
    report = await _verify(ragflow_src, wd_db, run_ctx)

    assert report.has_critical() is False
    assert [entry.table for entry in report.counts] == EXPECTED_TABLES
    assert {entry.table: entry.source for entry in report.counts} == EXPECTED_SOURCE
    for table in CRITICAL_TABLES:
        entry = _entry(report, table)
        assert entry.missing_ids == [], table
        assert entry.critical is False, table
    for table in EXPECTED_TABLES:
        assert _entry(report, table).missing_ids == [], table
    # Fixture nie ma wiersza access wskazującego dialog spoza źródła (data.sql).
    assert report.orphan_access == []
    assert report.missing_blob == [DOC_MISSING_BLOB]
    assert report.size_mismatch == [DOC_SIZE_MISMATCH]
    assert _issues(report, "blob_missing")[0].severity == "warning"
    assert _issues(report, "blob_size_mismatch")[0].severity == "warning"


async def test_missing_chat_in_target_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Skasowany czat: ``chats.missing_ids``, ``critical``, Issue ``count_missing`` i rc 2.

    Test broni mutacji ``e4-6c-verify-ignores-missing-chat.patch`` (wyrocznia briefu T4).
    """
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("DELETE FROM chats WHERE id = :id", {"id": D1_ID})])
    report = await _verify(ragflow_src, wd_db, run_ctx)

    entry = _entry(report, "chats")
    assert entry.source == EXPECTED_SOURCE["chats"]
    assert entry.missing_ids == [D1_ID]
    assert entry.critical is True
    issue = _count_issue(report, "chats")
    assert issue.ids == [D1_ID]
    assert issue.severity == "critical"
    assert report.has_critical() is True
    assert report.to_json()["ok"] is False


async def test_missing_assistant_access_in_target_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Skasowany wiersz dostępu: klucz ``<lower(email)>:<dialog_id>`` i uwaga krytyczna."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(
        wd_db,
        [
            (
                "DELETE FROM assistant_access WHERE email = :email AND chat_id = :chat",
                {"email": "admin@rf.test", "chat": D1_ID},
            )
        ],
    )
    report = await _verify(ragflow_src, wd_db, run_ctx)

    entry = _entry(report, "assistant_access")
    assert entry.missing_ids == [ACCESS_KEY]
    assert entry.critical is True
    assert _count_issue(report, "assistant_access").ids == [ACCESS_KEY]
    assert report.has_critical() is True


async def test_missing_user_in_target_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Skasowany użytkownik (po jego kluczach): ``users.missing_ids`` i uwaga krytyczna."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(
        wd_db,
        [
            ("DELETE FROM api_keys WHERE user_id = :id", {"id": U3_ID}),
            ("DELETE FROM users WHERE id = :id", {"id": U3_ID}),
        ],
    )
    report = await _verify(ragflow_src, wd_db, run_ctx)

    entry = _entry(report, "users")
    assert entry.missing_ids == [U3_ID]
    assert entry.critical is True
    assert _count_issue(report, "users").ids == [U3_ID]
    assert report.has_critical() is True


async def test_missing_integration_in_target_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Skasowana integracja: ``integrations.missing_ids`` (id jako tekst) i uwaga krytyczna."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("DELETE FROM integrations WHERE id = :id", {"id": int(INTEGRATION_ID)})])
    report = await _verify(ragflow_src, wd_db, run_ctx)

    entry = _entry(report, "integrations")
    assert entry.missing_ids == [INTEGRATION_ID]
    assert entry.critical is True
    assert _count_issue(report, "integrations").ids == [INTEGRATION_ID]
    assert report.has_critical() is True


async def test_missing_dataset_in_target_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Skasowany dataset: ``datasets.missing_ids``, ``critical`` i uwaga ``count_missing``.

    FK ``chat_datasets.dataset_id`` jest ``RESTRICT`` — najpierw zdejmujemy powiązanie czatu.
    DS3 należy do czatu ``d2`` (``data.sql``), więc próbka kontraktowa §6 zgłasza dodatkowo
    rozjazd ``datasets`` tego czatu (oczekiwany zbiór bierze się z ``dialog.kb_ids`` ŹRÓDŁA).
    Kasowanie datasetu pociąga jego dokumenty (``documents.dataset_id`` ``CASCADE``), więc
    krytyczne są też brakujące wiersze ``documents``.
    """
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(
        wd_db,
        [
            ("DELETE FROM chat_datasets WHERE dataset_id = :id", {"id": DS3_ID}),
            ("DELETE FROM datasets WHERE id = :id", {"id": DS3_ID}),
        ],
    )
    report = await _verify(ragflow_src, wd_db, run_ctx)

    entry = _entry(report, "datasets")
    assert entry.missing_ids == [DS3_ID]
    assert entry.critical is True
    issue = _count_issue(report, "datasets")
    assert issue.ids == [DS3_ID]
    assert issue.severity == "critical"
    assert report.contract.mismatches == [ContractMismatch("chat", D2_ID, "datasets", DS3_ID, "")]
    assert report.has_critical() is True


async def test_missing_document_in_target_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Skasowany dokument: ``documents.missing_ids``, ``critical`` i uwaga ``count_missing``."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("DELETE FROM documents WHERE id = :id", {"id": DOC_ID})])
    report = await _verify(ragflow_src, wd_db, run_ctx)

    entry = _entry(report, "documents")
    assert entry.source == EXPECTED_SOURCE["documents"]
    assert entry.missing_ids == [DOC_ID]
    assert entry.critical is True
    issue = _count_issue(report, "documents")
    assert issue.ids == [DOC_ID]
    assert issue.severity == "critical"
    assert report.has_critical() is True
    assert report.to_json()["ok"] is False


async def test_missing_api_key_in_target_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Skasowany klucz API: ``api_keys.missing_ids``, ``critical`` i uwaga ``count_missing``.

    Kasujemy klucz użytkownika bez czatu (``u3``), żeby próbka kontraktowa §6 została czysta —
    jedyną krytyczną uwagą raportu jest wtedy brak klucza.
    """
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("DELETE FROM api_keys WHERE id = :id", {"id": API_KEY_ID})])
    report = await _verify(ragflow_src, wd_db, run_ctx)

    entry = _entry(report, "api_keys")
    assert entry.source == EXPECTED_SOURCE["api_keys"]
    assert entry.missing_ids == [API_KEY_ID]
    assert entry.critical is True
    issue = _count_issue(report, "api_keys")
    assert issue.ids == [API_KEY_ID]
    assert issue.severity == "critical"
    assert {issue.code for issue in report.issues if issue.severity == "critical"} == {
        "count_missing"
    }
    assert report.has_critical() is True


async def test_missing_file_is_warning_only(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Skasowany plik: licznik zgłasza brak jako ``warning`` — sam raport pozostaje rc 0."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("DELETE FROM files WHERE id = :id", {"id": FILE_ID})])
    report = await _verify(ragflow_src, wd_db, run_ctx)

    entry = _entry(report, "files")
    assert entry.missing_ids == [FILE_ID]
    assert entry.critical is False
    issue = _count_issue(report, "files")
    assert issue.ids == [FILE_ID]
    assert issue.severity == "warning"
    assert report.has_critical() is False
    assert report.to_json()["ok"] is True


async def test_report_json_has_contract_keys_and_no_tokens(
    source: Source,
    ragflow_src: SourceDb,
    wd_db: WdDb,
    run_ctx: RunContext,
    expectations: dict[str, Any],
) -> None:
    """``to_json``: klucze wg §3.2, ``ok`` z uwag oraz żadnego tokenu z ``expectations.json``."""
    await run_all(source, wd_db.sm, run_ctx)
    report = await _verify(ragflow_src, wd_db, run_ctx)
    payload = report.to_json()
    dump = json.dumps(payload, ensure_ascii=False)
    markdown = report.to_markdown()

    assert set(payload) == JSON_KEYS
    assert payload["version"] == 1
    assert payload["command"] == "verify"
    assert payload["ok"] == (not report.has_critical())
    assert [entry["table"] for entry in payload["counts"]] == EXPECTED_TABLES
    assert payload["orphan_access"] == []
    for entry in expectations["tokens"]:
        assert entry["token"] not in dump
        assert sha256_hex(entry["token"]) not in dump
        assert entry["token"] not in markdown


async def test_cli_verify_exit_codes_and_reports(
    ragflow_src: SourceDb,
    wd_db: WdDb,
    run_ctx: RunContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI: rc 0 i dwa pliki raportu na czystym biegu; po skasowaniu czatu rc 2."""
    src = Source.connect(ragflow_src.dsn)
    report_dir = tmp_path / "reports"
    try:
        await run_all(src, wd_db.sm, run_ctx)
    finally:
        src.close()
    _cli_env(monkeypatch, wd_db, tmp_path)

    assert await _cli_verify(ragflow_src, report_dir) == EXIT_OK
    written, payload, markdown = _written_reports(report_dir)
    assert len(written) == REPORT_FILES
    assert written[0].startswith("verify-report-") and written[0].endswith(".json")
    assert written[1].startswith("verify-report-") and written[1].endswith(".md")
    assert payload["command"] == "verify"
    assert payload["ok"] is True
    assert markdown.startswith("# Verify RAGFlow → WD")

    await _exec(wd_db, [("DELETE FROM chats WHERE id = :id", {"id": D1_ID})])
    assert await _cli_verify(ragflow_src, report_dir) == EXIT_CRITICAL
    assert await _count(wd_db.sm, "SELECT COUNT(*) FROM chats WHERE id = :id", {"id": D1_ID}) == 0
