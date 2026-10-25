"""Testy integracyjne komendy ``diff`` (brief T5, kontrakt E4-6c §3.3) — MariaDB.

Pełna migracja fixture'u do celu, potem ``run_diff``: liczniki, posortowane id, obcięcie
``MAX_IDS`` i brak jakiegokolwiek zapisu. Kolumny czasu tabel integracji — DEC-145
(``discovered_at``/``started_at``/``integrations.updated_at``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.core.timeutil import now_ms
from app.tools.ragflow_migrate import cli
from app.tools.ragflow_migrate import diff as diff_mod
from app.tools.ragflow_migrate.diff import DiffReport, run_diff
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages import ORDER
from app.tools.ragflow_migrate.stages.base import RunContext
from tests.integration.ragflow_migrate.conftest import WdDb

pytestmark = pytest.mark.db

#: Tabele WD w stałej kolejności (kontrakt §3.3).
TABLES: tuple[str, ...] = (
    "users",
    "datasets",
    "documents",
    "chats",
    "chat_sessions",
    "chat_messages",
    "assistant_access",
    "api_keys",
    "integrations",
    "integration_sharepoint",
    "integration_containers",
    "integration_item_mappings",
    "integration_sync_runs",
    "integration_sync_events",
)

#: Zapytania kontrolne „nic nie zapisano” (kolumna czasu wg DEC-145); licznik + MAX czasu.
_SNAPSHOT_SQL: dict[str, tuple[str, str]] = {
    "users": ("users", "update_time"),
    "datasets": ("datasets", "update_time"),
    "documents": ("documents", "update_time"),
    "chats": ("chats", "update_time"),
    "chat_sessions": ("chat_sessions", "update_time"),
    "chat_messages": ("chat_messages", "update_time"),
    "assistant_access": ("assistant_access", "created_at"),
    "api_keys": ("api_keys", "update_time"),
    "integrations": ("integrations", "updated_at"),
    "integration_containers": ("integration_containers", "discovered_at"),
    "integration_item_mappings": ("integration_item_mappings", "updated_at"),
    "integration_sync_runs": ("integration_sync_runs", "started_at"),
    "integration_sync_events": ("integration_sync_events", "created_at"),
}

#: Pełna migracja fixture'u (wszystkie etapy z ``stages.ORDER``).
_ALL_STAGES: tuple[str, ...] = tuple(ORDER)

#: === czas przed wszystkimi wpisami fixture'u (ms epoki); pełne liczniki.
EPOCH_MS = 0

#: Znacznik przyszły względem ``now_ms()`` — warunek ``> since`` daje zero zmian.
FUTURE_GAP_MS = 10_000

#: Odstęp „mojej” zmiany od znacznika ``since`` w testach mutacji.
CHANGE_GAP_MS = 5_000

#: Liczba plików raportu CLI (JSON + Markdown, kontrakt §1).
REPORT_FILES = 2

#: Liczba zmienionych wierszy w teście obcięcia ``ids`` (fixture ma 3 użytkowników).
CHANGED_ROWS = 3
#: Zredukowany limit ``MAX_IDS`` w teście obcięcia (monkeypatch).
SMALL_MAX_IDS = 2


async def _migrated(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """Pełna migracja fixture'u do celu (wszystkie etapy)."""
    await run_all(source, wd_db.sm, run_ctx, only=list(_ALL_STAGES))


async def _ids(wd_db: WdDb, sql: str, params: dict[str, Any] | None = None) -> list[str]:
    """Pojedyncza kolumna jako lista ``str`` (świeża transakcja)."""
    async with wd_db.sm() as session:
        result = await session.execute(text(sql), params or {})
        return [str(value) for value in result.scalars().all()]


async def _count(wd_db: WdDb, table: str) -> int:
    """Liczba wierszy tabeli celu (`table` zawsze ze stałej tego pliku)."""
    async with wd_db.sm() as session:
        return int((await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one())  # noqa: S608


async def _scalar(wd_db: WdDb, sql: str) -> Any:
    """Pojedyncza wartość zapytania (np. ``MAX`` czasu) albo ``None``."""
    async with wd_db.sm() as session:
        return (await session.execute(text(sql))).scalar_one()


async def _execute(wd_db: WdDb, sql: str, params: dict[str, Any]) -> None:
    """Wykonuje UPDATE w celu i commituje (mutacja testu)."""
    async with wd_db.sm() as session:
        await session.execute(text(sql), params)
        await session.commit()


async def _snapshot(wd_db: WdDb) -> dict[str, tuple[int, int | None]]:
    """Migawka ``tabela → (liczba wierszy, MAX czasu)``; bez ``integration_sharepoint`` (JOIN)."""
    result: dict[str, tuple[int, int | None]] = {}
    for table, (source, column) in _SNAPSHOT_SQL.items():
        maximum = await _scalar(wd_db, f"SELECT MAX({column}) FROM {source}")  # noqa: S608
        result[table] = (await _count(wd_db, source), None if maximum is None else int(maximum))
    return result


def _entry(report: DiffReport, table: str) -> Any:
    """Wpis raportu dla tabeli (kontrakt §3.3 gwarantuje obecność wszystkich 14)."""
    return next(entry for entry in report.tables if entry.table == table)


async def test_diff_reports_all_tables_since_epoch(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) ``since`` przed migracją → pełne liczniki tabel z danymi, id posortowane."""
    await _migrated(source, wd_db, run_ctx)

    report = await run_diff(wd_db.settings, EPOCH_MS)

    assert [entry.table for entry in report.tables] == list(TABLES)
    users = _entry(report, "users")
    assert users.column == "update_time"
    assert users.changed == await _count(wd_db, "users")
    assert users.changed > 0
    assert users.ids == sorted(users.ids)
    assert users.truncated is False
    for table in ("datasets", "documents", "chats", "chat_sessions", "chat_messages"):
        count = await _count(wd_db, table)
        assert count > 0, table
        assert _entry(report, table).changed == count, table


async def test_diff_future_since_reports_no_changes(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(b) ``since`` po migracji → wszystkie liczniki 0, ``ids`` puste."""
    await _migrated(source, wd_db, run_ctx)

    report = await run_diff(wd_db.settings, now_ms() + FUTURE_GAP_MS)

    assert all(entry.changed == 0 for entry in report.tables)
    assert all(entry.ids == [] and entry.truncated is False for entry in report.tables)


async def test_diff_shows_only_row_changed_after_since(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) ``UPDATE chats`` po ``since`` → dokładnie ten wiersz; reszta tabel 0."""
    await _migrated(source, wd_db, run_ctx)
    chat_id = (await _ids(wd_db, "SELECT id FROM chats ORDER BY id LIMIT 1"))[0]
    since = now_ms()

    await _execute(
        wd_db,
        "UPDATE chats SET name = :name, update_time = :t WHERE id = :id",
        {"name": "zmieniony", "t": since + CHANGE_GAP_MS, "id": chat_id},
    )

    report = await run_diff(wd_db.settings, since)

    chats = _entry(report, "chats")
    assert chats.changed == 1
    assert chats.ids == [chat_id]
    others = {entry.table: entry.changed for entry in report.tables if entry.table != "chats"}
    assert set(others.values()) == {0}, others


async def test_diff_covers_access_and_chat_messages(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(d) zmiana ``assistant_access`` (``created_at``) i ``chat_messages`` jest wykazana."""
    await _migrated(source, wd_db, run_ctx)
    access_rows = await _ids(
        wd_db, "SELECT CONCAT(email, ':', chat_id) FROM assistant_access ORDER BY email, chat_id"
    )
    email, chat_id = access_rows[0].split(":", 1)
    message_id = (await _ids(wd_db, "SELECT id FROM chat_messages ORDER BY id LIMIT 1"))[0]
    since = now_ms()
    future = since + CHANGE_GAP_MS

    await _execute(
        wd_db,
        "UPDATE assistant_access SET created_at = :t WHERE email = :email AND chat_id = :chat",
        {"t": future, "email": email, "chat": chat_id},
    )
    await _execute(
        wd_db,
        "UPDATE chat_messages SET update_time = :t WHERE id = :id",
        {"t": future, "id": message_id},
    )

    report = await run_diff(wd_db.settings, since)

    access = _entry(report, "assistant_access")
    assert access.column == "created_at"
    assert access.changed == 1
    assert access.ids == [f"{email}:{chat_id}"]
    messages = _entry(report, "chat_messages")
    assert messages.changed == 1
    assert messages.ids == [message_id]


async def test_diff_truncates_ids_but_keeps_full_count(
    source: Source, wd_db: WdDb, run_ctx: RunContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(e) ponad limit → ``truncated``, ``len(ids) == MAX_IDS``, ``changed`` pełny."""
    await _migrated(source, wd_db, run_ctx)
    user_ids = await _ids(wd_db, f"SELECT id FROM users ORDER BY id LIMIT {CHANGED_ROWS}")  # noqa: S608
    assert len(user_ids) == CHANGED_ROWS
    since = now_ms()
    for user_id in user_ids:
        await _execute(
            wd_db,
            "UPDATE users SET update_time = :t WHERE id = :id",
            {"t": since + CHANGE_GAP_MS, "id": user_id},
        )
    monkeypatch.setattr(diff_mod, "MAX_IDS", SMALL_MAX_IDS)

    report = await run_diff(wd_db.settings, since)

    users = _entry(report, "users")
    assert users.changed == CHANGED_ROWS
    assert len(users.ids) == SMALL_MAX_IDS
    assert users.ids == user_ids[:SMALL_MAX_IDS]
    assert users.truncated is True


async def test_diff_writes_nothing(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(f) ``diff`` nie zapisuje: liczniki i ``MAX`` czasów wszystkich tabel bez zmian."""
    await _migrated(source, wd_db, run_ctx)
    before = await _snapshot(wd_db)

    await run_diff(wd_db.settings, EPOCH_MS)

    assert await _snapshot(wd_db) == before


async def test_cli_diff_writes_reports(
    source: Source,
    wd_db: WdDb,
    run_ctx: RunContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cli.main(["diff", …])`` na bazie celu: rc 0 i para raportów ``diff-report-*``.

    ``cli.main`` woła ``asyncio.run`` — biegnie w osobnym wątku (w teście jest już pętla).
    """
    await _migrated(source, wd_db, run_ctx)
    settings = wd_db.settings
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_DB_HOST", settings.db_host)
    monkeypatch.setenv("WD_DB_PORT", str(settings.db_port))
    monkeypatch.setenv("WD_DB_USER", settings.db_user)
    monkeypatch.setenv("WD_DB_PASSWORD", settings.db_password.get_secret_value())
    monkeypatch.setenv("WD_DB_NAME", settings.db_name)
    report_dir = tmp_path / "reports"

    rc = await asyncio.to_thread(
        cli.main,
        ["diff", "--since", "2000-01-01T00:00:00Z", "--report-dir", str(report_dir)],
    )

    assert rc == 0
    written = sorted(path.name for path in report_dir.iterdir())
    assert len(written) == REPORT_FILES
    assert written[0].startswith("diff-report-") and written[0].endswith(".json")
    assert written[1].startswith("diff-report-") and written[1].endswith(".md")
    payload = json.loads((report_dir / written[0]).read_text(encoding="utf-8"))
    assert payload["command"] == "diff"
    assert payload["since"] == "2000-01-01T00:00:00Z"
    assert [entry["table"] for entry in payload["tables"]] == list(TABLES)
