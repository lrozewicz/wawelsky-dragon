"""Testy etapu `access` migracji RAGFlow→WD (brief T3, kontrakt §4 i §6) — wymagają MariaDB."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.tools.ragflow_migrate.runner import plan_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.access import SOURCE_TABLE
from app.tools.ragflow_migrate.stages.base import RunContext
from tests.integration.ragflow_migrate._chat_fixtures import (
    D1_ID,
    U2_TOKEN,
    bearer,
    client,
    migrate,
    row,
    rows,
    scalar,
    source_writer,
)
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

#: Etapy potrzebne samemu etapowi `access` + odczytowi przez API (K7, kontrakt §5).
ACCESS_ONLY = ["users", "models", "datasets", "chats", "keys", "access"]

SOURCE_ACCESS_ROWS = 2
ORPHAN_DIALOG_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f99"
#: `created_at` źródła (2025-10-01 08:11:00 UTC) niezależnie przeliczony na ms (brief pkt 3a).
SOURCE_ACCESS_MS = int(datetime(2025, 10, 1, 8, 11, tzinfo=UTC).timestamp() * 1000)

#: Token FIKCYJNY u3 (nie sekret) — negatywny przypadek K7 (brief pkt 3f).
U3_TOKEN = "ragflow-FIXTURE-u3-plain"  # noqa: S105
U3_ID = "b0a1c2d3e4f5061728394a5b6c7d8e93"

HTTP_OK = 200

_ACCESS_INSERT = (
    "INSERT INTO `ai_hub_user_assistant_access` (`email`,`dialog_id`,`created_at`,`created_by`)"
    " VALUES (%s, %s, NOW(), %s)"
)
_ACCESS_UPDATE_BY = (
    "UPDATE `ai_hub_user_assistant_access` SET `created_by` = %s"
    " WHERE `email` = %s AND `dialog_id` = %s"
)


def insert_access(conn: Any, email: str, dialog_id: str, created_by: str | None = None) -> None:
    """Wstawia wiersz `ai_hub_user_assistant_access` do źródła (brief — bez edycji `data.sql`)."""
    with conn.cursor() as cursor:
        cursor.execute(_ACCESS_INSERT, (email, dialog_id, created_by))


def issue_ids(result: Any, code: str) -> set[str]:
    """Zbiór id uwag o danym kodzie w wyniku/inwentarzu etapu."""
    return {row_id for issue in result.issues if issue.code == code for row_id in issue.ids}


def codes(result: Any) -> list[tuple[str, str]]:
    """Pary ``(kod, waga)`` uwag w kolejności wyniku."""
    return [(issue.code, issue.severity) for issue in result.issues]


async def test_run_migrates_two_access_rows(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Dwa dostępy fixture'u → dwa wiersze `assistant_access` z czasem źródła w ms."""
    results = await migrate(source, wd_db, run_ctx, only=ACCESS_ONLY)
    access = results[-1]
    assert access.stage == "access"
    assert access.source_count == SOURCE_ACCESS_ROWS
    assert (access.created, access.updated, access.skipped) == (SOURCE_ACCESS_ROWS, 0, 0)
    assert access.target_count == SOURCE_ACCESS_ROWS
    assert access.issues == []
    assert await rows(
        wd_db.sm,
        "SELECT email, chat_id, created_by, created_at FROM assistant_access ORDER BY email",
    ) == [
        {
            "email": "admin@rf.test",
            "chat_id": D1_ID,
            "created_by": "admin@rf.test",
            "created_at": SOURCE_ACCESS_MS,
        },
        {
            "email": "alice@rf.test",
            "chat_id": D1_ID,
            "created_by": "admin@rf.test",
            "created_at": SOURCE_ACCESS_MS,
        },
    ]


async def test_orphan_access_warns_and_is_skipped(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(b) Dostęp do dialogu spoza `dialog` → warning `access_orphan`, brak wiersza w celu."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_access(conn, "orphan@rf.test", ORPHAN_DIALOG_ID, "admin@rf.test")
    inventory = plan_all(source, run_ctx, only=["access"])[0]
    assert inventory.source_counts == {SOURCE_TABLE: SOURCE_ACCESS_ROWS + 1}
    assert issue_ids(inventory, "access_orphan") == {ORPHAN_DIALOG_ID}
    result = (await migrate(source, wd_db, run_ctx, only=ACCESS_ONLY))[-1]
    assert result.source_count == SOURCE_ACCESS_ROWS + 1
    assert (result.created, result.updated, result.skipped) == (SOURCE_ACCESS_ROWS, 0, 1)
    assert issue_ids(result, "access_orphan") == {ORPHAN_DIALOG_ID}
    assert codes(result) == [("access_orphan", "warning")]
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM assistant_access") == SOURCE_ACCESS_ROWS


async def test_created_by_marker_and_null_are_kept(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) `created_by='hub-compat-auto-provisioning'` i NULL zachowane dosłownie (kontrakt §4)."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_access(conn, "marker@rf.test", D1_ID, "hub-compat-auto-provisioning")
        insert_access(conn, "nullby@rf.test", D1_ID, None)
    await migrate(source, wd_db, run_ctx, only=ACCESS_ONLY)
    assert (
        await scalar(
            wd_db.sm,
            "SELECT created_by FROM assistant_access WHERE email = :e",
            {"e": "marker@rf.test"},
        )
        == "hub-compat-auto-provisioning"
    )
    assert await row(
        wd_db.sm,
        "SELECT created_by FROM assistant_access WHERE email = :e",
        {"e": "nullby@rf.test"},
    ) == {"created_by": None}


async def test_second_run_is_idempotent_then_update_is_detected(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(d) Drugi bieg: 0/0/source_count; zmiana `created_by` w źródle → `updated`=1."""
    await migrate(source, wd_db, run_ctx, only=ACCESS_ONLY)
    second = (await migrate(source, wd_db, run_ctx, only=ACCESS_ONLY))[-1]
    assert (second.created, second.updated, second.skipped) == (0, 0, SOURCE_ACCESS_ROWS)
    assert second.target_count == SOURCE_ACCESS_ROWS
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(_ACCESS_UPDATE_BY, ("nowy@rf.test", "alice@rf.test", D1_ID))
    third = (await migrate(source, wd_db, run_ctx, only=ACCESS_ONLY))[-1]
    assert (third.created, third.updated, third.skipped) == (0, 1, 1)
    assert (
        await scalar(
            wd_db.sm,
            "SELECT created_by FROM assistant_access WHERE email = :e",
            {"e": "alice@rf.test"},
        )
        == "nowy@rf.test"
    )


async def test_dry_run_writes_nothing_and_source_is_untouched(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(e) `--dry-run` nie zostawia wierszy w `assistant_access`; źródło nietknięte."""
    before = source.count(SOURCE_TABLE)
    results = await migrate(source, wd_db, run_ctx, only=ACCESS_ONLY, dry_run=True)
    assert results[-1].created == SOURCE_ACCESS_ROWS
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM assistant_access") == 0
    assert source.count(SOURCE_TABLE) == before == SOURCE_ACCESS_ROWS


async def test_run_without_chats_reports_all_rows_orphan(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Bez etapu `chats` (brak `ctx.shared['chat_ids']`) `SELECT id FROM chats` zwraca pusto →
    wszystkie dostępy osierocone, brak zapisu (kontrakt §1, §4)."""
    result = (await migrate(source, wd_db, run_ctx, only=["access"]))[-1]
    assert result.source_count == SOURCE_ACCESS_ROWS
    assert (result.created, result.updated, result.skipped) == (0, 0, SOURCE_ACCESS_ROWS)
    assert result.target_count == 0
    assert issue_ids(result, "access_orphan") == {D1_ID}
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM assistant_access") == 0


async def test_api_grantee_sees_chat_without_grant_does_not(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext, tmp_path: Any
) -> None:
    """(f) K7 przez API: alice (grant do d1) widzi d1; u3 (bez grantu i własności) nie.

    Fixture ma `user` u3 z `is_active='0'`/`status='0'`, więc przed migracją aktywujemy go
    w źródle (przez `source_writer`), by jego klucz przeszedł uwierzytelnienie.
    """
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE `user` SET `is_active` = '1', `status` = '1' WHERE `id` = %s", (U3_ID,)
        )
    await migrate(source, wd_db, run_ctx, only=ACCESS_ONLY)
    with client(wd_db.settings, tmp_path) as http:
        granted = http.get("/api/v1/chats", headers=bearer(U2_TOKEN))
        ungranted = http.get("/api/v1/chats", headers=bearer(U3_TOKEN))
    assert granted.status_code == HTTP_OK
    granted_body = granted.json()
    assert granted_body["code"] == 0, granted_body
    assert D1_ID in {item["id"] for item in granted_body["data"]}
    assert ungranted.status_code == HTTP_OK
    ungranted_body = ungranted.json()
    assert ungranted_body["code"] == 0, ungranted_body
    assert D1_ID not in {item["id"] for item in ungranted_body["data"]}
