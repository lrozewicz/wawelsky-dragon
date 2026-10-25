"""Testy integracyjne komendy ``reparse`` (brief T3, kontrakt E4-6c §3.1).

Bieg ``reparse`` na bazie celu po migracji etapów ``users, models, datasets, documents``.
Kolejkowanie idzie wyłącznie przez ``Container.ingest.enqueue_parse`` — testy sprawdzają
skutek w tabeli ``tasks`` i stan ``documents.run``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.container import Container
from app.tools.ragflow_migrate import cli
from app.tools.ragflow_migrate.reparse import run_reparse
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext
from tests.integration.ragflow_migrate._chat_fixtures import migrate, rows, scalar
from tests.integration.ragflow_migrate.conftest import WdDb

pytestmark = pytest.mark.db

#: Etapy potrzebne, by dokumenty z blobami trafiły do celu (kontrakt §3.1).
STAGES: list[str] = ["users", "models", "datasets", "documents"]

#: Liczba dokumentów fixture'u bez bloba (f03 zły rozmiar, f04 brak pliku) — kontrakt §3.1.
NO_BLOB_DOCUMENTS = 2

#: Liczba plików raportu zapisywanych przez CLI (JSON + Markdown, kontrakt §1).
REPORT_FILES = 2

_QUEUED_DOCS = "SELECT id FROM documents WHERE content_hash <> '' ORDER BY id"
_NO_BLOB_DOCS = "SELECT id FROM documents WHERE content_hash = '' ORDER BY id"
_DATASET_IDS = "SELECT id FROM datasets ORDER BY id"
_TASKS = "SELECT document_id, priority, status FROM tasks ORDER BY document_id"
_TASK_COUNT = "SELECT COUNT(*) FROM tasks WHERE task_type = 'parse_document'"
_DOC_RUNS = "SELECT id, run FROM documents ORDER BY id"
_DOC_DATASET = "SELECT dataset_id FROM documents WHERE id = :id"


def _settings(wd_db: WdDb, tmp_path: Path) -> Settings:
    """Ustawienia celu biegu ``reparse`` (storage w katalogu tymczasowym, kontrakt §3.1)."""
    return wd_db.settings.model_copy(update={"storage_root": str(tmp_path)})


async def _ids(wd_db: WdDb, sql: str) -> list[str]:
    """Pojedyncza kolumna id jako lista (bez powtórzeń sensu — zapytania są deterministyczne)."""
    return [str(row["id"]) for row in await rows(wd_db.sm, sql)]


async def _set_run(wd_db: WdDb, document_id: str, run: str) -> None:
    """Ustawia ``documents.run`` dokumentu celu (symulacja stanu po parsowaniu; test)."""
    async with wd_db.sm() as session:
        await session.execute(
            text("UPDATE documents SET run = :run WHERE id = :id"),
            {"run": run, "id": document_id},
        )
        await session.commit()


async def _migrated(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """Bieg etapów źródło→cel wymaganych przez ``reparse``."""
    await migrate(source, wd_db, run_ctx, only=STAGES)


async def test_reparse_queues_documents_with_blob(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """Kolejkuje dokładnie dokumenty z niepustym ``content_hash``; f03/f04 bez bloba pomija."""
    await _migrated(source, wd_db, run_ctx)
    expected_queued = await _ids(wd_db, _QUEUED_DOCS)
    expected_no_blob = await _ids(wd_db, _NO_BLOB_DOCS)
    assert len(expected_no_blob) == NO_BLOB_DOCUMENTS  # fixture: f03 (zły rozmiar), f04 (brak)

    report = await run_reparse(_settings(wd_db, tmp_path), None, 0)

    assert report.queued_ids == expected_queued
    assert sorted(report.skipped_no_blob) == expected_no_blob
    assert report.skipped_state == {}
    assert report.priority == 0
    assert report.datasets == await _ids(wd_db, _DATASET_IDS)

    tasks = await rows(wd_db.sm, _TASKS)
    assert sorted(str(task["document_id"]) for task in tasks) == expected_queued
    assert {str(task["status"]) for task in tasks} == {"queued"}
    assert {int(task["priority"]) for task in tasks} == {0}
    assert not set(expected_no_blob) & {str(task["document_id"]) for task in tasks}

    runs = {str(row["id"]): str(row["run"]) for row in await rows(wd_db.sm, _DOC_RUNS)}
    assert {doc_id for doc_id, run in runs.items() if run == "1"} == set(expected_queued)


async def test_reparse_second_run_queues_nothing(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """Drugi bieg: ``run='1'`` z pierwszego → ``skipped_state["1"]``, zero nowych zadań."""
    await _migrated(source, wd_db, run_ctx)
    settings = _settings(wd_db, tmp_path)
    first = await run_reparse(settings, None, 0)
    tasks_after_first = await scalar(wd_db.sm, _TASK_COUNT)

    second = await run_reparse(settings, None, 0)

    assert second.queued_ids == []
    assert sorted(second.skipped_state["1"]) == sorted(first.queued_ids)
    assert await scalar(wd_db.sm, _TASK_COUNT) == tasks_after_first == len(first.queued_ids)


async def test_reparse_limits_to_given_datasets(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """``datasets=[id]``: kolejkowane tylko dokumenty tego datasetu (i jego blobów)."""
    await _migrated(source, wd_db, run_ctx)
    document_id = (await _ids(wd_db, _QUEUED_DOCS))[0]
    dataset_id = str((await rows(wd_db.sm, _DOC_DATASET, {"id": document_id}))[0]["dataset_id"])
    expected = [
        doc_id
        for doc_id in await _ids(wd_db, _QUEUED_DOCS)
        if str((await rows(wd_db.sm, _DOC_DATASET, {"id": doc_id}))[0]["dataset_id"]) == dataset_id
    ]

    report = await run_reparse(_settings(wd_db, tmp_path), [dataset_id], 0)

    assert report.datasets == [dataset_id]
    assert sorted(report.queued_ids) == sorted(expected)
    assert sorted(report.queued_ids) != sorted(await _ids(wd_db, _QUEUED_DOCS))  # nie wszystkie
    tasks = await rows(wd_db.sm, _TASKS)
    assert sorted(str(task["document_id"]) for task in tasks) == sorted(expected)


async def test_reparse_unknown_dataset_raises(wd_db: WdDb, tmp_path: Path) -> None:
    """Nieznane id datasetu → ``ValueError`` (kontrakt §3.1)."""
    with pytest.raises(ValueError, match="Nieznany dataset"):
        await run_reparse(_settings(wd_db, tmp_path), ["nie-ma"], 0)


async def test_reparse_empty_dataset_list_raises(wd_db: WdDb, tmp_path: Path) -> None:
    """Pusta lista datasetów to błąd, nigdy „wszystkie” (uwaga z przeglądu T1)."""
    with pytest.raises(ValueError, match="pusta lista"):
        await run_reparse(_settings(wd_db, tmp_path), [], 0)


async def test_reparse_priority_low_goes_to_tasks(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """``priority=-1`` (tło) trafia do ``tasks.priority`` każdego zadania."""
    await _migrated(source, wd_db, run_ctx)

    report = await run_reparse(_settings(wd_db, tmp_path), None, -1)

    assert report.priority == -1
    tasks = await rows(wd_db.sm, _TASKS)
    assert tasks
    assert {int(task["priority"]) for task in tasks} == {-1}


async def test_reparse_skips_document_with_other_run(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """Dokument z ``run='3'`` (i blobem) trafia do ``skipped_state["3"]``, nie do kolejki."""
    await _migrated(source, wd_db, run_ctx)
    document_id = (await _ids(wd_db, _QUEUED_DOCS))[0]
    await _set_run(wd_db, document_id, "3")

    report = await run_reparse(_settings(wd_db, tmp_path), None, 0)

    assert report.skipped_state["3"] == [document_id]
    assert document_id not in report.queued_ids
    tasks = await rows(wd_db.sm, _TASKS)
    assert document_id not in {str(task["document_id"]) for task in tasks}


async def test_reparse_skips_document_with_active_task(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """``run='0'`` z zadaniem queued/running → ``skipped_state["1"]``, bez drugiego zadania."""
    await _migrated(source, wd_db, run_ctx)
    settings = _settings(wd_db, tmp_path)
    document_id = (await _ids(wd_db, _QUEUED_DOCS))[0]
    container = Container(settings)
    await container.start()
    try:
        await container.ingest.enqueue_parse([document_id])
    finally:
        await container.aclose()
    await _set_run(wd_db, document_id, "0")  # niespójność: zadanie aktywne, a run znów '0'
    tasks_before = await scalar(wd_db.sm, _TASK_COUNT)

    report = await run_reparse(settings, None, 0)

    assert report.skipped_state["1"] == [document_id]
    assert document_id not in report.queued_ids
    tasks = await rows(wd_db.sm, _TASKS)
    assert [str(task["document_id"]) for task in tasks].count(document_id) == tasks_before
    assert len(tasks) == tasks_before + len(report.queued_ids)
    assert "## Pominięte, run=1" in report.to_markdown()


async def test_reparse_json_and_markdown_shape(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Path
) -> None:
    """``to_json`` ma klucze i typy wg §3.1; ``json.dumps`` bez błędu; Markdown z nagłówkiem."""
    await _migrated(source, wd_db, run_ctx)

    report = await run_reparse(_settings(wd_db, tmp_path), None, 0)
    payload = report.to_json()

    assert payload["version"] == 1
    assert payload["command"] == "reparse"
    assert payload["priority"] == 0
    assert isinstance(payload["datasets"], list)
    assert isinstance(payload["queued_ids"], list)
    assert isinstance(payload["skipped_no_blob"], list)
    assert isinstance(payload["skipped_state"], dict)
    assert payload["queued"] == len(report.queued_ids)
    assert payload["started_at"].endswith("Z") and payload["finished_at"].endswith("Z")
    json.dumps(payload)  # bez błędu (żadnych obiektów poza JSON)
    markdown = report.to_markdown()
    assert markdown.startswith("# Reparse")
    assert report.queued_ids[0] in markdown


async def test_cli_reparse_writes_reports(
    source: Source,
    wd_db: WdDb,
    run_ctx: RunContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cli.main(["reparse", …])`` na bazie celu: rc 0 i para raportów ``reparse-report-*``.

    ``cli.main`` woła ``asyncio.run`` — biegnie w osobnym wątku (w teście jest już pętla);
    ``WD_DB_*`` z ustawień ``wd_db`` wskazuje bazę celu tego testu.
    """
    await _migrated(source, wd_db, run_ctx)
    settings = wd_db.settings
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_DB_HOST", settings.db_host)
    monkeypatch.setenv("WD_DB_PORT", str(settings.db_port))
    monkeypatch.setenv("WD_DB_USER", settings.db_user)
    monkeypatch.setenv("WD_DB_PASSWORD", settings.db_password.get_secret_value())
    monkeypatch.setenv("WD_DB_NAME", settings.db_name)
    monkeypatch.setenv("WD_STORAGE_ROOT", str(tmp_path / "cli-storage"))
    report_dir = tmp_path / "reports"

    rc = await asyncio.to_thread(
        cli.main, ["reparse", "--datasets", "all", "--report-dir", str(report_dir)]
    )
    assert rc == 0

    written = sorted(path.name for path in report_dir.iterdir())
    assert len(written) == REPORT_FILES
    assert written[0].startswith("reparse-report-") and written[0].endswith(".json")
    assert written[1].startswith("reparse-report-") and written[1].endswith(".md")
    payload = json.loads((report_dir / written[0]).read_text(encoding="utf-8"))
    assert payload["command"] == "reparse"
    assert payload["queued"] == len(await _ids(wd_db, _QUEUED_DOCS))
