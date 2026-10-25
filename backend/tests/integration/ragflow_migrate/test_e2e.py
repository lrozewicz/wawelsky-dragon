"""Test end-to-end ciągu operatora migracji RAGFlow→WD (brief T8, kontrakt E4-6c).

Jeden test przechodzi cały ciąg: ``plan`` → ``run --dry-run`` → ``run`` → ``reparse`` →
worker na fake-llm → ``verify`` → retrieval → ``diff`` → przyrost ``run --since``.
CLI wołamy przez ``asyncio.to_thread`` (robi ``asyncio.run``) z env ``WD_*`` na bazę celu
tego testu (wzór: ``test_reparse.py::test_cli_reparse_writes_reports``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.timeutil import iso
from app.services.retrieval import RetrievalQuery
from app.tools.ragflow_migrate import cli
from app.worker.main import create_worker
from tests.integration.ragflow_migrate.conftest import (
    FIXTURES_DIR,
    SourceDb,
    WdDb,
    source_writer,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

#: Wiersze przenoszone 1:1: (etap, tabela źródła, tabela celu) — kontrakt E4-6c §3.2.
COUNT_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("users", "user", "users"),
    ("datasets", "knowledgebase", "datasets"),
    ("documents", "document", "documents"),
    ("documents", "file", "files"),
    ("chats", "dialog", "chats"),
    ("sessions", "conversation", "chat_sessions"),
    ("keys", "api_token", "api_keys"),
    ("access", "ai_hub_user_assistant_access", "assistant_access"),
    ("integrations", "ai_hub_sharepoint_integrations", "integrations"),
)

#: Dokumenty fixture'u bez bloba (f03 zły rozmiar, f04 brak pliku) — README §13.
NO_BLOB_DOCUMENTS = 2
STORAGE_DIRNAME = "wd-storage"
#: Szybki poll kolejki workera i limit czekania na stan końcowy dokumentu (brief T8).
POLL_S = 0.05
WAIT_TIMEOUT_S = 90.0


def _seed_env(monkeypatch: pytest.MonkeyPatch, settings: Settings, storage_root: Path) -> None:
    """``WD_*`` na bazę celu i storage testu — ``cli.main`` tworzy ``Settings()`` sam."""
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_DB_HOST", settings.db_host)
    monkeypatch.setenv("WD_DB_PORT", str(settings.db_port))
    monkeypatch.setenv("WD_DB_USER", settings.db_user)
    monkeypatch.setenv("WD_DB_PASSWORD", settings.db_password.get_secret_value())
    monkeypatch.setenv("WD_DB_NAME", settings.db_name)
    monkeypatch.setenv("WD_STORAGE_ROOT", str(storage_root))


def _common_args(src: SourceDb, model_map_path: Path, sp_crypto_key: str) -> list[str]:
    """Argumenty wspólne ``plan``/``run``: źródło, mapa modeli, pliki i klucz sekretu SP."""
    return [
        "--src-mysql",
        src.dsn,
        "--model-map",
        str(model_map_path),
        "--src-files-dir",
        str(FIXTURES_DIR / "files"),
        "--src-sp-crypto-key",
        sp_crypto_key,
    ]


async def _cli(args: list[str]) -> int:
    """``cli.main`` w osobnym wątku (w teście jest już pętla asyncio)."""
    return await asyncio.to_thread(cli.main, args)


def _report(directory: Path, prefix: str) -> dict[str, Any]:
    """Zawartość jedynego raportu JSON o prefiksie w katalogu."""
    matches = sorted(directory.glob(f"{prefix}-*.json"))
    assert len(matches) == 1, [path.name for path in matches]
    return json.loads(matches[0].read_text(encoding="utf-8"))


def _counter_by_stage(payload: dict[str, Any], key: str) -> dict[str, int]:
    """``results[].<key>`` per etap z raportu migracji (``created``/``source_count``)."""
    return {str(result["stage"]): int(result[key]) for result in payload["results"]}


def _counts_by_stage(payload: dict[str, Any]) -> dict[str, dict[str, int]]:
    """``inventories[].source_counts`` per etap z raportu ``plan`` (liczniki źródła)."""
    return {
        str(inv["stage"]): {str(name): int(count) for name, count in inv["source_counts"].items()}
        for inv in payload["inventories"]
    }


async def _scalar(sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any]) -> Any:
    """Pojedyncza wartość z bazy celu (świeża transakcja)."""
    async with sm() as session:
        return (await session.execute(text(sql), params)).scalar_one()


def _files(root: Path) -> list[Path]:
    """Pliki pod katalogiem storage (pusto, gdy katalogu nie ma)."""
    return sorted(path for path in root.rglob("*") if path.is_file())


@contextlib.asynccontextmanager
async def _worker(settings: Settings) -> AsyncIterator[Container]:
    """Prawdziwy Worker na kontenerze testu (wzorzec ``_worker`` z test_worker_e2e)."""
    container, worker = create_worker(settings)
    await container.start()
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    try:
        yield container
    finally:
        stop.set()
        await asyncio.wait_for(run_task, timeout=15)
        await container.aclose()


async def _wait_final(
    sm: async_sessionmaker[AsyncSession], document_id: str, *, timeout_s: float = WAIT_TIMEOUT_S
) -> None:
    """Czeka, aż dokument ma stan końcowy (``run`` ∈ {'2','3','4'}) bez zadań w toku.

    Wzorzec ``_wait_final`` z ``test_worker_e2e``: sam ``run`` nie wystarcza, więc wymagamy
    też, by istniało zadanie dokumentu i żadne nie było w stanie nieterminalnym.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        async with sm() as session:
            run = (
                await session.execute(
                    text("SELECT run FROM documents WHERE id = :i"), {"i": document_id}
                )
            ).scalar_one()
            counts = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total,"
                        " COALESCE(SUM(status NOT IN ('done','failed','cancelled','dead')), 0)"
                        " AS pending, COALESCE(SUM(status = 'dead'), 0) AS dead"
                        " FROM tasks WHERE document_id = :i"
                    ),
                    {"i": document_id},
                )
            ).one()
        if (
            str(run) in ("2", "3", "4") and int(counts.total) >= 1 and int(counts.pending) == 0
        ) or int(counts.dead) > 0:
            return
        await asyncio.sleep(0.2)
    raise AssertionError(f"dokument {document_id} nie osiągnął stanu końcowego w {timeout_s} s")


async def _rows(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Wiersze z bazy celu jako słowniki (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return [dict(record) for record in result.mappings().all()]


async def test_full_operator_flow(  # noqa: PLR0913, PLR0915, PLR0917 — jeden scenariusz przekrojowy
    ragflow_src: SourceDb,
    wd_db: WdDb,
    tmp_path: Path,
    expectations: dict[str, Any],
    model_map_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan → dry-run → run → reparse → worker → verify → retrieval → diff → przyrost."""
    storage_root = tmp_path / STORAGE_DIRNAME
    _seed_env(monkeypatch, wd_db.settings, storage_root)
    common = _common_args(ragflow_src, model_map_path, expectations["sharepoint"]["src_crypto_key"])

    # 1. plan — inwentarz źródła, rc 0.
    plan_dir = tmp_path / "reports" / "plan"
    assert await _cli(["plan", *common, "--report-dir", str(plan_dir)]) == 0
    plan = _report(plan_dir, "migration-report")
    assert plan["mode"] == "plan"

    # 2. run --dry-run — nic nie zostaje w celu ani w storage.
    dry_dir = tmp_path / "reports" / "dry-run"
    assert await _cli(["run", *common, "--dry-run", "--report-dir", str(dry_dir)]) == 0
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM users", {}) == 0
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM documents", {}) == 0
    assert _files(storage_root) == []

    # 3. run — pełna migracja; liczby w celu zgodne z licznikami źródła z raportu ``plan``.
    run_dir = tmp_path / "reports" / "run"
    assert await _cli(["run", *common, "--report-dir", str(run_dir)]) == 0
    run = _report(run_dir, "migration-report")
    source = _counts_by_stage(plan)
    for stage, source_table, target_table in COUNT_CHECKS:
        count_sql = f"SELECT COUNT(*) FROM {target_table}"  # noqa: S608 — stała z testu
        target = await _scalar(wd_db.sm, count_sql, {})
        assert target == source[stage][source_table], (stage, target_table)
    for stage, created in _counter_by_stage(run, "created").items():
        assert created == _counter_by_stage(run, "source_count")[stage], stage

    # 4. reparse — kolejkuje dokumenty z blobem, bez bloba pomija.
    reparse_dir = tmp_path / "reports" / "reparse"
    assert await _cli(["reparse", "--datasets", "all", "--report-dir", str(reparse_dir)]) == 0
    reparse = _report(reparse_dir, "reparse-report")
    assert len(reparse["skipped_no_blob"]) == NO_BLOB_DOCUMENTS
    assert reparse["queued"] == source["documents"]["document"] - NO_BLOB_DOCUMENTS

    # 5. worker na fake-llm przetwarza kolejkę parsowania do stanu końcowego.
    worker_settings = wd_db.settings.model_copy(
        update={"storage_root": str(storage_root), "ocr_engine": "none", "worker_poll_s": POLL_S}
    )
    async with _worker(worker_settings) as container:
        assert container.llm is not None
        for document_id in reparse["queued_ids"]:
            await _wait_final(wd_db.sm, document_id)
        docs = {
            str(doc["id"]): doc
            for doc in await _rows(
                wd_db.sm,
                "SELECT id, name, dataset_id, run, error, chunk_count FROM documents ORDER BY id",
            )
        }
        done = [doc for doc in docs.values() if doc["run"] == "3"]
        failed = [doc for doc in docs.values() if doc["run"] == "4"]
        # Wszystkie cztery dokumenty z blobem kończą DONE — ``raport.pdf`` i ``umowa.docx``
        # to prawdziwe pliki z ``make_binaries.py`` (PDF z warstwą tekstową, DOCX mammotha).
        assert sorted(str(doc["name"]) for doc in done) == [
            "notatki.txt",
            "raport.pdf",
            "stare.md",
            "umowa.docx",
        ]
        assert failed == []
        assert all(int(doc["chunk_count"]) > 0 for doc in done)
        # Dokumenty bez bloba nie były kolejkowane: run='0' i znacznik z etapu ``documents``.
        for document_id in reparse["skipped_no_blob"]:
            assert docs[document_id]["run"] == "0"
            assert str(docs[document_id]["error"]).startswith("migration:")

        # 6. verify — zgodność celu ze źródłem, rc 0 (brak uwag krytycznych).
        verify_dir = tmp_path / "reports" / "verify"
        verify_code = await _cli(
            [
                "verify",
                "--src-mysql",
                ragflow_src.dsn,
                "--model-map",
                str(model_map_path),
                "--report-dir",
                str(verify_dir),
            ]
        )
        assert verify_code == 0
        verify = _report(verify_dir, "verify-report")
        assert verify["ok"] is True
        assert all(
            entry["source"] == entry["target"] and entry["missing_ids"] == []
            for entry in verify["counts"]
        )
        # Wszystkie dokumenty z blobem przeszły parsing: ``parse.done`` = ``queued`` (4).
        assert verify["parse"]["done"] + verify["parse"]["failed"] == reparse["queued"]
        assert verify["parse"]["done"] == len(done)
        assert verify["parse"]["chunks_total"] == sum(int(doc["chunk_count"]) for doc in done)
        assert verify["parse"]["chunks_total"] > 0
        assert verify["files"]["missing_blob"] == [
            document_id
            for document_id in reparse["skipped_no_blob"]
            if "blob missing" in str(docs[document_id]["error"])
        ]
        assert sorted(
            [*verify["files"]["missing_blob"], *verify["files"]["size_mismatch"]]
        ) == sorted(reparse["skipped_no_blob"])
        assert verify["contract_sample"]["mismatches"] == []
        assert verify["contract_sample"]["chats_checked"] >= 1

        # 7. retrieval na przeniesionym datasecie zwraca chunk przeniesionego dokumentu.
        # Treść ``notatki.txt`` w fixture to ``fixture notatki txt`` (README §13).
        migrated = next(doc for doc in docs.values() if doc["name"] == "notatki.txt")
        result = await container.retrieval.retrieve_trusted(
            RetrievalQuery(question="notatki", dataset_ids=(str(migrated["dataset_id"]),))
        )
        assert result.total >= 1
        assert str(migrated["id"]) in {chunk.document_id for chunk in result.chunks}

    # 8. diff — wszystkie wiersze celu są nowsze niż 2000-01-01, w tym wszyscy użytkownicy.
    diff_dir = tmp_path / "reports" / "diff"
    assert (
        await _cli(["diff", "--since", "2000-01-01T00:00:00Z", "--report-dir", str(diff_dir)]) == 0
    )
    diff = _report(diff_dir, "diff-report")
    by_table = {str(entry["table"]): entry for entry in diff["tables"]}
    assert by_table["users"]["changed"] == source["users"]["user"]

    # 9. przyrost — zmiana w źródle wchodzi do celu przez ``run --since``.
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT id, name FROM knowledgebase ORDER BY id")
        dataset_id, old_name = cursor.fetchone()
        cursor.execute("SELECT MAX(update_time) FROM knowledgebase")
        max_time = int(cursor.fetchone()[0])
        new_name = f"{old_name} (przyrost)"
        cursor.execute(
            "UPDATE knowledgebase SET name = %s, update_time = %s WHERE id = %s",
            (new_name, max_time + 1000, dataset_id),
        )
    since_dir = tmp_path / "reports" / "since"
    assert (
        await _cli(["run", *common, "--since", iso(max_time), "--report-dir", str(since_dir)]) == 0
    )
    assert (
        await _scalar(wd_db.sm, "SELECT name FROM datasets WHERE id = :i", {"i": str(dataset_id)})
        == new_name
    )
