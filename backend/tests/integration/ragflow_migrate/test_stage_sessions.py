"""Testy etapu `sessions` migracji RAGFlow→WD (brief T2, kontrakt §3 i §6) — wymagają MariaDB."""

import json
from datetime import datetime
from typing import Any

import pytest

from app.tools.ragflow_migrate.runner import plan_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from tests.integration.ragflow_migrate._chat_fixtures import (
    D1_ID,
    S1_ID,
    S2_ID,
    U1_ID,
    U1_TOKEN,
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

DS1_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f01"
DOC1_ID = "f1a2b3c4d5e60718293a4b5c6d7e8f01"
DOC2_ID = "f1a2b3c4d5e60718293a4b5c6d7e8f02"

S3_ID = "7c6d5e4f3a2b10819293a4b5c6d7e803"
S4_ID = "7c6d5e4f3a2b10819293a4b5c6d7e804"
S5_ID = "7c6d5e4f3a2b10819293a4b5c6d7e805"
ORPHAN_CHAT_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f99"
PAIR_ID_1 = "11111111-1111-1111-1111-111111111111"
PAIR_ID_2 = "22222222-2222-2222-2222-222222222222"

#: Etapy potrzebne etapowi `sessions` (kontrakt §5): właściciel czatu i sam czat w celu.
SESSION_ONLY = ["users", "models", "datasets", "chats", "sessions"]

#: Rozmowy fixture'u (`data.sql`); dwie mają po jednej referencji bez celu (kontrakt §3).
SOURCE_CONVERSATIONS = 2

HTTP_OK = 200
CONV_CREATE_MS = 1759306140000

#: Jawna lista normalizacji profilu 0.24 (kontrakt §6) — pól, których test NIE porównuje 1:1.
API_NORMALIZATIONS = (
    "messages[].id i messages[].created_at (dla źródła bez tych pól są generowane)",
    "kolejność kluczy w obiektach JSON",
    "create_time/update_time/create_date/update_date wyliczane z conversation (ms)",
)

#: Referencje dokładanej rozmowy — format fixture'u (chunk_id, content_with_weight, doc_id…).
CHUNK_REFERENCE_1: dict[str, Any] = {
    "chunk_id": "CHUNK-FIXTURE-A",
    "content_with_weight": "Wawelsky Dragon to lekki system RAG.",
    "doc_id": DOC1_ID,
    "docnm_kwd": "raport.pdf",
    "kb_id": DS1_ID,
    "image_id": "IMG-A",
    "positions": [[1, 2, 3]],
}
CHUNK_REFERENCE_2: dict[str, Any] = {
    "chunk_id": "CHUNK-FIXTURE-B",
    "content_with_weight": "Indeksowanie zależy od rozmiaru.",
    "doc_id": DOC2_ID,
    "docnm_kwd": "umowa.docx",
    "kb_id": DS1_ID,
    "image_id": None,
    "positions": [[4, 5, 6]],
}

PAIR_MESSAGE: str = json.dumps(
    [
        {"role": "assistant", "content": "prolog"},
        {"role": "user", "content": "pytanie-1", "id": PAIR_ID_1},
        {"role": "assistant", "content": "odpowiedź-1", "id": PAIR_ID_1},
        {"role": "user", "content": "pytanie-2", "id": PAIR_ID_2},
        {"role": "assistant", "content": "odpowiedź-2", "id": PAIR_ID_2},
    ]
)
PAIR_ROLES = ["assistant", "user", "assistant", "user", "assistant"]

_CONVERSATION_INSERT = (
    "INSERT INTO `conversation` (`id`,`create_time`,`create_date`,`update_time`,`update_date`,"
    "`dialog_id`,`name`,`message`,`reference`,`user_id`)"
    " VALUES (%s, %s, NOW(), %s, NOW(), %s, %s, %s, %s, %s)"
)


def insert_conversation(  # noqa: PLR0913 — warianty wiersza fixture'u w jednym miejscu
    conn: Any,
    conversation_id: str,
    *,
    dialog_id: str = D1_ID,
    name: str = "session-x",
    message: str | None = None,
    reference: str | None = None,
    user_id: str | None = "admin@rf.test",
) -> None:
    """Wstawia wiersz ``conversation`` do źródła (brief pkt 3c-3e — bez edycji ``data.sql``)."""
    with conn.cursor() as cursor:
        cursor.execute(
            _CONVERSATION_INSERT,
            (
                conversation_id,
                CONV_CREATE_MS,
                CONV_CREATE_MS,
                dialog_id,
                name,
                message,
                reference,
                user_id,
            ),
        )


def expected_sessions(source: Source) -> dict[str, dict[str, Any]]:
    """Oczekiwane sesje liczone z wierszy ``conversation`` źródła (nie z kodu etapu, §6)."""
    expected: dict[str, dict[str, Any]] = {}
    for conversation in source.rows("conversation"):
        entries = json.loads(conversation["message"]) if conversation["message"] else []
        expected[str(conversation["id"])] = {
            "name": conversation["name"],
            "user_id": conversation["user_id"],
            "messages": [{"role": e["role"], "content": e["content"]} for e in entries],
        }
    return expected


def expected_chunk_reference(chunk: dict[str, Any]) -> dict[str, Any]:
    """Kształt ChunkReference v0.24 (kontrakt §6) liczony niezależnie od ``app``."""
    return {
        "id": chunk.get("chunk_id", chunk.get("id")),
        "content": chunk.get("content_with_weight", chunk.get("content")),
        "document_id": chunk.get("doc_id", chunk.get("document_id")),
        "document_name": chunk.get("docnm_kwd", chunk.get("document_name")),
        "dataset_id": chunk.get("kb_id", chunk.get("dataset_id")),
        "image_id": chunk.get("image_id", chunk.get("img_id")),
        "positions": chunk.get("positions", chunk.get("position_int")),
    }


def reference_entry(chunk: dict[str, Any]) -> dict[str, Any]:
    """Wpis ``reference`` w formacie fixture'u (``chunks`` + ``doc_aggs``)."""
    return {"chunks": [chunk], "doc_aggs": []}


def issue_ids(holder: StageResult | Any, code: str) -> set[str]:
    """Zbiór id uwag o danym kodzie w wyniku etapu albo inwentarzu `plan`."""
    return {row_id for issue in holder.issues if issue.code == code for row_id in issue.ids}


async def test_run_migrates_sessions_and_messages(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Dwie rozmowy → dwie sesje; `user_id` dosłownie ze źródła, `owner_id` = tenant czatu."""
    results = await migrate(source, wd_db, run_ctx, only=SESSION_ONLY)
    sessions = results[-1]
    assert sessions.stage == "sessions"
    assert sessions.source_count == SOURCE_CONVERSATIONS
    assert (sessions.created, sessions.updated, sessions.skipped) == (SOURCE_CONVERSATIONS, 0, 0)
    assert sessions.target_count == SOURCE_CONVERSATIONS
    assert issue_ids(sessions, "reference_unattached") == {S1_ID, S2_ID}
    assert [issue.severity for issue in sessions.issues] == ["warning", "warning"]
    assert await rows(
        wd_db.sm,
        "SELECT id, chat_id, name, user_id, owner_id, source, message_count"
        " FROM chat_sessions ORDER BY id",
    ) == [
        {
            "id": S1_ID,
            "chat_id": D1_ID,
            "name": "session-1",
            "user_id": "admin@rf.test",
            "owner_id": U1_ID,
            "source": "api",
            "message_count": 2,
        },
        {
            "id": S2_ID,
            "chat_id": D1_ID,
            "name": "session-2",
            "user_id": "alice@rf.test",
            "owner_id": U1_ID,
            "source": "api",
            "message_count": 2,
        },
    ]
    stored = await rows(
        wd_db.sm,
        "SELECT session_id, seq, role, content, reference FROM chat_messages"
        " ORDER BY session_id, seq",
    )
    expected = expected_sessions(source)
    for session_id in (S1_ID, S2_ID):
        messages = [m for m in stored if m["session_id"] == session_id]
        assert [m["seq"] for m in messages] == [0, 1]
        assert [{"role": m["role"], "content": m["content"]} for m in messages] == expected[
            session_id
        ]["messages"]
        # Fixture ma po jednej referencji bez celu (brak role != user z seq > 0) — nie trafia.
        assert [m["reference"] for m in messages] == [None, None]


async def test_run_keeps_created_at_and_session_times(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Czasy sesji z `conversation` (ms) i `created_at` wiadomości w sekundach."""
    await migrate(source, wd_db, run_ctx, only=SESSION_ONLY)
    session = await row(
        wd_db.sm,
        "SELECT create_time, update_time, create_date FROM chat_sessions WHERE id = :id",
        {"id": S1_ID},
    )
    assert session["create_time"] == CONV_CREATE_MS
    assert session["update_time"] == CONV_CREATE_MS
    assert session["create_date"] == datetime(2025, 10, 1, 8, 9)
    assert (
        await scalar(
            wd_db.sm,
            "SELECT created_at FROM chat_messages WHERE session_id = :id AND seq = 0",
            {"id": S1_ID},
        )
        == CONV_CREATE_MS / 1000
    )


async def test_api_lists_migrated_sessions(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Any
) -> None:
    """(b) `GET /api/v1/chats/{id}/sessions` profilem 0.24: kształt równy źródłu (rozmowy §6)."""
    await migrate(source, wd_db, run_ctx)
    expected = expected_sessions(source)
    with client(wd_db.settings, tmp_path) as http:
        response = http.get(f"/api/v1/chats/{D1_ID}/sessions", headers=bearer(U1_TOKEN))
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["code"] == 0, body
    items = {item["id"]: item for item in body["data"]}
    assert set(items) == {S1_ID, S2_ID}
    for session_id in (S1_ID, S2_ID):
        item = items[session_id]
        source_session = expected[session_id]
        assert item["name"] == source_session["name"]
        assert item["user_id"] == source_session["user_id"]
        assert [
            {"role": m["role"], "content": m["content"]} for m in item["messages"]
        ] == source_session["messages"]
        # Prolog (seq 0, assistant) bez `id` (kontrakt §6; patrz: API_NORMALIZATIONS).
        assert "id" not in item["messages"][0]
        assert "reference" not in item["messages"][0]


async def test_api_attaches_references_pairs_and_ids(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext, tmp_path: Any
) -> None:
    """(c) 2 referencje i wspólne id pary → `reference` na seq 2 i 4, id pary spójne."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_conversation(
            conn,
            S3_ID,
            name="session-para",
            message=PAIR_MESSAGE,
            reference=json.dumps(
                [reference_entry(CHUNK_REFERENCE_1), reference_entry(CHUNK_REFERENCE_2)]
            ),
        )
    # Domyślne `only` obejmuje `keys`: token u1 w celu, żeby API uwierzytelniło żądanie (§6).
    await migrate(source, wd_db, run_ctx)
    stored = await rows(
        wd_db.sm,
        "SELECT seq, id, reference FROM chat_messages WHERE session_id = :id ORDER BY seq",
        {"id": S3_ID},
    )
    assert [m["reference"] is not None for m in stored] == [False, False, True, False, True]
    assert json.loads(stored[2]["reference"]) == {"chunks": [CHUNK_REFERENCE_1], "doc_aggs": []}
    # Para user+assistant dzieli źródłowe id: asystent je zachowuje, user dostaje uuid5 (§3).
    assert stored[2]["id"] == PAIR_ID_1
    assert stored[4]["id"] == PAIR_ID_2
    assert stored[1]["id"] != PAIR_ID_1
    assert stored[3]["id"] != PAIR_ID_2
    with client(wd_db.settings, tmp_path) as http:
        response = http.get(f"/api/v1/chats/{D1_ID}/sessions", headers=bearer(U1_TOKEN))
    body = response.json()
    assert body["code"] == 0, body
    item = {entry["id"]: entry for entry in body["data"]}[S3_ID]
    assert [m["role"] for m in item["messages"]] == PAIR_ROLES
    assert item["messages"][2]["reference"] == [expected_chunk_reference(CHUNK_REFERENCE_1)]
    assert item["messages"][4]["reference"] == [expected_chunk_reference(CHUNK_REFERENCE_2)]
    # Wiadomości bez referencji nie mają klucza `reference` (jawna normalizacja shimu, §6).
    for index in (0, 1, 3):
        assert "reference" not in item["messages"][index]


async def test_null_message_and_reference_are_stored(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(d) `message` i `reference` NULL → sesja zapisana z 0 wiadomości, bez wyjątku."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_conversation(conn, S4_ID, name="session-pusta", message=None, reference=None)
    result = (await migrate(source, wd_db, run_ctx, only=SESSION_ONLY))[-1]
    assert result.created == SOURCE_CONVERSATIONS + 1
    assert await row(
        wd_db.sm,
        "SELECT name, message_count FROM chat_sessions WHERE id = :id",
        {"id": S4_ID},
    ) == {"name": "session-pusta", "message_count": 0}
    assert (
        await scalar(
            wd_db.sm,
            "SELECT COUNT(*) FROM chat_messages WHERE session_id = :id",
            {"id": S4_ID},
        )
        == 0
    )


async def test_conversation_of_unmigrated_chat_is_skipped(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(e) Rozmowa czatu spoza celu → warning `session_chat_missing`, `skipped` = 1."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_conversation(conn, S5_ID, dialog_id=ORPHAN_CHAT_ID, name="session-sierota")
    result = (await migrate(source, wd_db, run_ctx, only=SESSION_ONLY))[-1]
    assert result.source_count == SOURCE_CONVERSATIONS + 1
    assert (result.created, result.updated, result.skipped) == (SOURCE_CONVERSATIONS, 0, 1)
    assert result.target_count == SOURCE_CONVERSATIONS
    assert issue_ids(result, "session_chat_missing") == {S5_ID}
    assert [issue.severity for issue in result.issues if issue.code == "session_chat_missing"] == [
        "warning"
    ]
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chat_sessions") == SOURCE_CONVERSATIONS


async def test_second_run_is_idempotent_and_changes_replace_messages(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Drugi bieg bez zmian → skipped; zmiana `message` → `updated` bez duplikatów."""
    await migrate(source, wd_db, run_ctx, only=SESSION_ONLY)
    second = (await migrate(source, wd_db, run_ctx, only=SESSION_ONLY))[-1]
    assert (second.created, second.updated, second.skipped) == (0, 0, SOURCE_CONVERSATIONS)
    changed = json.dumps(
        [
            {"role": "assistant", "content": "Czym jest Wawelsky Dragon?"},
            {"role": "user", "content": "Zmieniona odpowiedź."},
            {"role": "assistant", "content": "Nowa odpowiedź.", "thumbup": 1},
        ]
    )
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE `conversation` SET `message` = %s WHERE `id` = %s", (changed, S1_ID))
    third = (await migrate(source, wd_db, run_ctx, only=SESSION_ONLY))[-1]
    assert (third.created, third.updated, third.skipped) == (0, 1, SOURCE_CONVERSATIONS - 1)
    assert await row(
        wd_db.sm,
        "SELECT message_count FROM chat_sessions WHERE id = :id",
        {"id": S1_ID},
    ) == {"message_count": 3}
    assert await rows(
        wd_db.sm,
        "SELECT seq, role, content, thumbup FROM chat_messages WHERE session_id = :id ORDER BY seq",
        {"id": S1_ID},
    ) == [
        {"seq": 0, "role": "assistant", "content": "Czym jest Wawelsky Dragon?", "thumbup": None},
        {"seq": 1, "role": "user", "content": "Zmieniona odpowiedź.", "thumbup": None},
        {"seq": 2, "role": "assistant", "content": "Nowa odpowiedź.", "thumbup": 1},
    ]
    # Trzeci bieg: `thumbup` (TINYINT) nie może wymuszać zapisu (idempotencja bool/int).
    fourth = (await migrate(source, wd_db, run_ctx, only=SESSION_ONLY))[-1]
    assert (fourth.created, fourth.updated, fourth.skipped) == (0, 0, SOURCE_CONVERSATIONS)


async def test_dry_run_and_plan_write_nothing(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(g) `--dry-run` nie zostawia wierszy; źródło nietknięte; `plan` liczy bez zapisu."""
    inventory = plan_all(source, run_ctx, only=["sessions"])[0]
    assert inventory.stage == "sessions"
    assert inventory.source_counts == {"conversation": SOURCE_CONVERSATIONS}
    assert inventory.not_migrated == {}
    assert issue_ids(inventory, "reference_unattached") == {S1_ID, S2_ID}
    results = await migrate(source, wd_db, run_ctx, only=SESSION_ONLY, dry_run=True)
    assert results[-1].created == SOURCE_CONVERSATIONS
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chat_sessions") == 0
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chat_messages") == 0
    assert source.count("conversation") == SOURCE_CONVERSATIONS
