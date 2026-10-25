"""Testy czystej funkcji etapu ``access`` (brief T3, kontrakt §4) — bez bazy."""

from datetime import UTC, datetime
from typing import Any

from app.tools.ragflow_migrate.stages.access import resolve_access

D1_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f01"
D2_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f02"
ORPHAN_DIALOG_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f99"
NOW_MS = 1759999999000
SOURCE_ACCESS_MS = 1759306260000


def row(**overrides: Any) -> dict[str, Any]:
    """Wiersz ``ai_hub_user_assistant_access`` o kształcie fixture'u, z nadpisanymi polami."""
    values: dict[str, Any] = {
        "email": "admin@rf.test",
        "dialog_id": D1_ID,
        "created_at": datetime(2025, 10, 1, 8, 11, tzinfo=UTC),
        "created_by": "admin@rf.test",
    }
    values.update(overrides)
    return values


def codes(issues: list[Any]) -> list[tuple[str, str]]:
    """Pary ``(kod, waga)`` uwag — do zwięzłych asercji."""
    return [(issue.code, issue.severity) for issue in issues]


def test_email_is_lowercased_and_datetime_becomes_epoch_ms() -> None:
    """E-mail zapisany lowercase; ``datetime`` (naiwny UTC) → ms epoki (kontrakt §4)."""
    targets, issues = resolve_access([row(email="Alice@RF.Test")], {D1_ID}, NOW_MS)
    assert targets == [
        {
            "email": "alice@rf.test",
            "chat_id": D1_ID,
            "created_by": "admin@rf.test",
            "created_at": SOURCE_ACCESS_MS,
        }
    ]
    assert issues == []


def test_naive_datetime_is_treated_as_utc() -> None:
    """``datetime`` bez strefy traktowany jest jak UTC (zachowanie pymysql, §4)."""
    naive, _issues = resolve_access([row(created_at=datetime(2025, 10, 1, 8, 11))], {D1_ID}, NOW_MS)
    assert naive[0]["created_at"] == SOURCE_ACCESS_MS


def test_null_created_at_falls_back_to_now_ms() -> None:
    """``created_at`` NULL → ``now_ms`` (kontrakt §4, brief pkt 2)."""
    targets, issues = resolve_access([row(created_at=None)], {D1_ID}, NOW_MS)
    assert targets[0]["created_at"] == NOW_MS
    assert issues == []


def test_null_created_by_stays_null() -> None:
    """``created_by`` NULL zostaje NULL (marker funkcjonalny też dosłownie, kontrakt §4)."""
    targets, issues = resolve_access(
        [
            row(created_by=None),
            row(email="marker@rf.test", created_by="hub-compat-auto-provisioning"),
        ],
        {D1_ID},
        NOW_MS,
    )
    assert targets[0]["created_by"] is None
    assert targets[1]["created_by"] == "hub-compat-auto-provisioning"
    assert issues == []


def test_orphan_dialog_warns_and_is_skipped() -> None:
    """Dialog spoza ``chat_ids`` → warning ``access_orphan``, brak wiersza celu (§4)."""
    targets, issues = resolve_access(
        [row(dialog_id=ORPHAN_DIALOG_ID, email="orphan@rf.test")], {D1_ID}, NOW_MS
    )
    assert targets == []
    assert codes(issues) == [("access_orphan", "warning")]
    assert issues[0].ids == [ORPHAN_DIALOG_ID]


def test_case_variant_duplicate_collapses_to_one_row_with_warning() -> None:
    """``Alice@X`` i ``alice@x`` dla tego samego czatu → jeden wiersz + ``access_duplicate``."""
    targets, issues = resolve_access(
        [
            row(email="Alice@RF.Test", created_by="pierwszy"),
            row(email="alice@rf.test", created_by="drugi"),
        ],
        {D1_ID},
        NOW_MS,
    )
    assert len(targets) == 1
    assert targets[0]["email"] == "alice@rf.test"
    assert targets[0]["created_by"] == "pierwszy"  # wygrywa pierwszy w kolejności (email, dialog)
    assert codes(issues) == [("access_duplicate", "warning")]
    assert issues[0].ids == ["alice@rf.test", D1_ID]


def test_same_email_for_different_chats_is_not_duplicate() -> None:
    """Ten sam e-mail dla różnych czatów to dwa wiersze, bez uwag (klucz PK, §4)."""
    targets, issues = resolve_access(
        [row(dialog_id=D1_ID), row(dialog_id=D2_ID)], {D1_ID, D2_ID}, NOW_MS
    )
    assert {target["chat_id"] for target in targets} == {D1_ID, D2_ID}
    assert issues == []
