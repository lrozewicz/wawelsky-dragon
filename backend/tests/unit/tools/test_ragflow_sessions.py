"""Testy czystych funkcji etapu ``sessions`` (brief T2, kontrakt §3) — bez bazy."""

import json
import uuid
from typing import Any

from app.tools.ragflow_migrate.stages.sessions_rows import (
    build_messages,
    message_ids,
    parse_messages,
    parse_references,
    resolve_session,
    session_name,
)

SESSION_ID = "7c6d5e4f3a2b10819293a4b5c6d7e801"
CHAT_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f01"
OWNER_ID = "b0a1c2d3e4f5061728394a5b6c7d8e91"
CREATE_MS = 1759306140000
NOW_MS = 1759999999000
FIXTURE_MESSAGE_COUNT = 2
MESSAGE_CREATED_AT = 1234.5
STORED_CREATE_MS = 111
STORED_UPDATE_MS = 222

#: Sesja fixture'u: ``[assistant, user]`` + jedna referencja bez celu (brief, przypadek 2).
FIXTURE_MESSAGES = json.dumps(
    [
        {"role": "assistant", "content": "Czym jest Wawelsky Dragon?"},
        {"role": "user", "content": "To lekki system RAG."},
    ]
)
FIXTURE_REFERENCE = json.dumps(
    [{"chunks": [{"chunk_id": "CHUNK-1"}], "doc_aggs": [], "prompt": "Jesteś asystentem."}]
)

#: Pary pytanie/odpowiedź (brief, przypadek 1): ``[A0, U1, A2, U3, A4]`` + dwie referencje.
PAIR_MESSAGES = json.dumps(
    [
        {"role": "assistant", "content": "prolog"},
        {"role": "user", "content": "pytanie-1"},
        {"role": "assistant", "content": "odpowiedź-1"},
        {"role": "user", "content": "pytanie-2"},
        {"role": "assistant", "content": "odpowiedź-2"},
    ]
)
REFERENCE_ONE = {"chunks": [{"chunk_id": "CHUNK-1"}], "doc_aggs": []}
REFERENCE_TWO = {"chunks": [{"chunk_id": "CHUNK-2"}], "doc_aggs": []}
PAIR_REFERENCE = json.dumps([REFERENCE_ONE, REFERENCE_TWO])


def _messages(message_json: Any, reference_json: Any = None) -> list[dict[str, Any]]:
    """Wiadomości z ``build_messages`` bez uwag (asercje na kształcie wierszy)."""
    messages, _issues = build_messages(SESSION_ID, message_json, reference_json, CREATE_MS)
    return messages


def test_references_land_on_non_user_messages_after_prologue() -> None:
    """(i) Dwie referencje → ``seq`` 2 i 4; pozostałe wiadomości bez ``reference``."""
    messages = _messages(PAIR_MESSAGES, PAIR_REFERENCE)
    assert [message["seq"] for message in messages] == [0, 1, 2, 3, 4]
    assert [message["role"] for message in messages] == [
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert messages[0]["reference"] is None
    assert messages[1]["reference"] is None
    assert json.loads(messages[2]["reference"]) == REFERENCE_ONE
    assert messages[3]["reference"] is None
    assert json.loads(messages[4]["reference"]) == REFERENCE_TWO


def test_reference_without_target_warns() -> None:
    """(ii) Fixture `[assistant, user]` + 1 referencja → brak celu i ``reference_unattached``."""
    messages, issues = build_messages(SESSION_ID, FIXTURE_MESSAGES, FIXTURE_REFERENCE, CREATE_MS)
    assert len(messages) == FIXTURE_MESSAGE_COUNT
    assert [message["reference"] for message in messages] == [None, None]
    assert [(issue.code, issue.severity, issue.ids) for issue in issues] == [
        ("reference_unattached", "warning", [SESSION_ID])
    ]


def test_empty_reference_entry_does_not_consume_target() -> None:
    """(iii) Pusty wpis ``{}`` w ``reference`` jest pomijany (nie zużywa celu przypięcia)."""
    messages = _messages(PAIR_MESSAGES, json.dumps([{}, REFERENCE_ONE]))
    assert json.loads(messages[2]["reference"]) == REFERENCE_ONE
    assert messages[4]["reference"] is None


def test_pair_shares_source_id_with_assistant() -> None:
    """(iv) Para user+assistant dzieli id: asystent zachowuje źródłowe, user dostaje ``uuid5``."""
    shared = "shared-pair-id"
    entries = json.dumps(
        [
            {"role": "assistant", "content": "prolog"},
            {"role": "user", "content": "pytanie", "id": shared},
            {"role": "assistant", "content": "odpowiedź", "id": shared},
        ]
    )
    messages = _messages(entries)
    expected_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wd-migrate:{SESSION_ID}:1"))
    assert messages[2]["id"] == shared
    assert messages[1]["id"] == expected_uuid
    assert messages[0]["id"] == str(uuid.uuid5(uuid.NAMESPACE_URL, f"wd-migrate:{SESSION_ID}:0"))


def test_message_json_fallbacks_and_invalid_warn() -> None:
    """(v) `message` NULL/""/nie-lista → ``[]``; uwaga tylko dla niepoprawnego JSON-u."""
    assert parse_messages(SESSION_ID, None) == ([], [])
    assert parse_messages(SESSION_ID, "") == ([], [])
    entries, issues = parse_messages(SESSION_ID, "{nie-json")
    assert entries == []
    assert [(issue.code, issue.severity) for issue in issues] == [
        ("session_json_invalid", "warning")
    ]
    # JSON obiektu zamiast listy to niepoprawny ``message``; lista nie-obiektów → uwagi per element.
    entries, issues = parse_messages(SESSION_ID, '{"role": "assistant"}')
    assert entries == []
    assert [(issue.code, issue.severity) for issue in issues] == [
        ("session_json_invalid", "warning")
    ]
    entries, issues = parse_messages(SESSION_ID, "[1, 2]")
    assert entries == []
    assert [issue.code for issue in issues] == ["message_invalid", "message_invalid"]
    assert _messages(None) == []
    assert _messages("[nie-json") == []


def test_role_outside_enum_is_skipped_without_seq_gaps() -> None:
    """(vi) Rola spoza enum → element pominięty, ``seq`` kolejnych wiadomości bez luk."""
    entries = json.dumps(
        [
            {"role": "assistant", "content": "prolog"},
            {"role": "wizard", "content": "nie-wiadomo"},
            "nie-obiekt",
            {"role": "user", "content": "pytanie"},
        ]
    )
    messages, issues = build_messages(SESSION_ID, entries, None, CREATE_MS)
    assert [message["seq"] for message in messages] == [0, 1]
    assert [message["role"] for message in messages] == ["assistant", "user"]
    assert [issue.code for issue in issues] == ["message_invalid", "message_invalid"]
    assert issues[0].ids == [SESSION_ID]


def test_thumbup_feedback_created_at_from_message() -> None:
    """(vii) ``thumbup``/``feedback``/``created_at`` z wiadomości; ``created_at`` ma fallback."""
    entries = json.dumps(
        [
            {
                "role": "assistant",
                "content": "odpowiedź",
                "thumbup": 1,
                "feedback": "ok",
                "created_at": 1234.5,
            },
            {"role": "assistant", "content": "inna", "thumbup": None, "feedback": None},
            {"role": "assistant", "content": None, "thumbup": 0},
        ]
    )
    messages = _messages(entries)
    assert messages[0]["thumbup"] is True
    assert messages[0]["feedback"] == "ok"
    assert messages[0]["created_at"] == MESSAGE_CREATED_AT
    assert messages[1]["thumbup"] is None
    assert messages[1]["feedback"] is None
    assert messages[1]["created_at"] == CREATE_MS / 1000
    assert messages[2]["thumbup"] is False
    assert messages[2]["content"] == ""
    for message in messages:
        assert message["prompt_tokens"] is None
        assert message["completion_tokens"] is None
        assert message["create_time"] == CREATE_MS
        assert message["update_time"] == CREATE_MS


def test_message_ids_of_invalid_source_ids_fall_back_to_uuid5() -> None:
    """Źródłowe id dłuższe niż 36 znaków albo nie-tekstowe → ``uuid5`` (kontrakt §3)."""
    entries = json.dumps(
        [
            {"role": "assistant", "content": "a", "id": "x" * 40},
            {"role": "assistant", "content": "b", "id": 12},
        ]
    )
    ids = message_ids(json.loads(entries), SESSION_ID)
    assert ids == [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"wd-migrate:{SESSION_ID}:0")),
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"wd-migrate:{SESSION_ID}:1")),
    ]


def test_references_of_broken_json_are_empty() -> None:
    """``reference`` niepoprawne/nie-lista → brak referencji bez uwagi (kontrakt §3)."""
    assert parse_references(None) == []
    assert parse_references("") == []
    assert parse_references("{nie-json") == []
    assert parse_references('{"chunks": []}') == []
    assert parse_references('[{"chunks": []}, "nie-obiekt", {}]') == [{"chunks": []}]


def test_session_name_default() -> None:
    """Nazwa sesji: wartość źródła, a gdy NULL/pusta — ``New session`` (kontrakt §3)."""
    assert session_name("session-1") == "session-1"
    assert session_name(None) == "New session"
    assert session_name("") == "New session"


def test_resolve_session_skips_conversation_of_missing_chat() -> None:
    """(e) Rozmowa czatu spoza celu → ``None`` i warning ``session_chat_missing``."""
    row = {
        "id": SESSION_ID,
        "dialog_id": CHAT_ID,
        "name": "session-1",
        "message": FIXTURE_MESSAGES,
        "reference": FIXTURE_REFERENCE,
        "user_id": "admin@rf.test",
        "create_time": CREATE_MS,
        "update_time": CREATE_MS,
    }
    session, messages, issues = resolve_session(row, {}, None, NOW_MS)
    assert session is None
    assert messages == []
    assert [(issue.code, issue.ids) for issue in issues] == [("session_chat_missing", [SESSION_ID])]


def test_resolve_session_builds_row_and_messages() -> None:
    """Wiersz rozmowy → kolumny ``chat_sessions`` z właścicielem czatu i ``message_count``."""
    row = {
        "id": SESSION_ID,
        "dialog_id": CHAT_ID,
        "name": None,
        "message": FIXTURE_MESSAGES,
        "reference": FIXTURE_REFERENCE,
        "user_id": "alice@rf.test",
        "create_time": CREATE_MS,
        "update_time": CREATE_MS,
    }
    session, messages, issues = resolve_session(row, {CHAT_ID: OWNER_ID}, None, NOW_MS)
    assert session is not None
    assert session["name"] == "New session"
    assert session["user_id"] == "alice@rf.test"
    assert session["owner_id"] == OWNER_ID
    assert session["source"] == "api"
    assert session["message_count"] == len(messages) == FIXTURE_MESSAGE_COUNT
    assert session["create_time"] == CREATE_MS
    assert [issue.code for issue in issues] == ["reference_unattached"]


def test_resolve_session_keeps_user_id_null_and_falls_back_to_now() -> None:
    """``user_id`` NULL zostaje NULL; brak czasu w źródle → istniejąca wartość celu, inaczej now."""
    row = {
        "id": SESSION_ID,
        "dialog_id": CHAT_ID,
        "name": "session-1",
        "message": None,
        "reference": None,
        "user_id": None,
        "create_time": None,
        "update_time": None,
    }
    session, messages, _issues = resolve_session(
        row, {CHAT_ID: OWNER_ID}, (STORED_CREATE_MS, STORED_UPDATE_MS), NOW_MS
    )
    assert session is not None
    assert session["user_id"] is None
    assert session["create_time"] == STORED_CREATE_MS
    assert session["update_time"] == STORED_UPDATE_MS
    assert messages == []
    first, _messages_out, _issues_out = resolve_session(row, {CHAT_ID: OWNER_ID}, None, NOW_MS)
    assert first is not None
    assert first["create_time"] == NOW_MS
