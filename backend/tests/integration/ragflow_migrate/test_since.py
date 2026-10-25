"""Przyrost ``run --since``: etapy czytają do upsertu tylko wiersze zmienione po ``since_ms``.

Brief T2 WP E4-6c, kontrakt §2. Testy wymagają MariaDB; wzorzec harnessu: ``conftest.py``
(fixture źródła i celu) oraz ``_chat_fixtures.py`` (``migrate``, ``source_writer``, ``scalar``,
``row``).
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

import pytest

from app.tools.ragflow_migrate import stages
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from tests.integration.ragflow_migrate._chat_fixtures import migrate, row, scalar, source_writer
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

#: Etapy biegu w testach: wszystkie z ``stages.ORDER`` poza ``integrations`` (brief, wymaganie 3a).
ONLY: tuple[str, ...] = tuple(name for name in stages.ORDER if name != "integrations")

#: Etapy objęte filtrem ``--since`` (kontrakt §2).
FILTERED: tuple[str, ...] = ("users", "datasets", "documents", "chats", "sessions", "keys")

#: Tabele źródła z kolumną ``update_time`` (BIGINT ms) — z nich liczymy ``T``.
SINCE_TABLES: tuple[str, ...] = (
    "user",
    "knowledgebase",
    "file",
    "document",
    "file2document",
    "dialog",
    "conversation",
    "api_token",
)

#: Id z fixture'u (``data.sql``), których dotyczą testy.
KB1_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f01"
CHAT2_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f02"
S1_ID = "7c6d5e4f3a2b10819293a4b5c6d7e801"
S2_ID = "7c6d5e4f3a2b10819293a4b5c6d7e802"
DOC1_ID = "f1a2b3c4d5e60718293a4b5c6d7e8f01"
DOC2_ID = "f1a2b3c4d5e60718293a4b5c6d7e8f02"
LOCAL_FILE_ID = "0a1b2c3d4e5f60718293a4b5c6d7e80a"

#: Odstęp znacznika ``--since`` od największego ``update_time`` źródła (brief, wymaganie 3b).
GAP_MS = 1000

#: Uwaga biegu w postaci porównywalnej między biegami: ``(waga, kod, id)``.
IssueKey = tuple[str, str, tuple[str, ...]]


@contextmanager
def _source(dsn: str) -> Iterator[Source]:
    """Świeże połączenie ze źródłem — zamknięte po biegu.

    ``Source`` siedzi w transakcji read-only, więc po ``UPDATE`` z testu potrzebne jest nowe
    połączenie (wzór: ``test_null_times.py``).
    """
    source = Source.connect(dsn)
    try:
        yield source
    finally:
        source.close()


def _max_update_time(dsn: str) -> int:
    """Największy ``update_time`` (ms) w tabelach źródła objętych filtrem ``--since``."""
    parts = [
        f"SELECT MAX(`update_time`) AS t FROM `{table}`"  # noqa: S608 — nazwy z SINCE_TABLES
        for table in SINCE_TABLES
    ]
    selects = " UNION ALL ".join(parts)
    with source_writer(dsn) as conn, conn.cursor() as cursor:
        cursor.execute(f"SELECT MAX(t) FROM ({selects}) AS all_times")  # noqa: S608 — jak wyżej
        found = cursor.fetchone()
    assert found is not None
    return int(found[0])


def _update_source(dsn: str, sql: str, params: tuple[Any, ...]) -> None:
    """Wykonuje ``UPDATE`` w źródle (sesja ``Source`` jest read-only)."""
    with source_writer(dsn) as conn, conn.cursor() as cursor:
        cursor.execute(sql, params)


async def _run(
    source: Source, wd_db: WdDb, run_ctx: RunContext, since_ms: int | None
) -> dict[str, StageResult]:
    """Bieg etapów ``ONLY`` z czystym ``shared`` i podanym ``since_ms``; wyniki po nazwie etapu."""
    ctx = replace(run_ctx, shared={}, since_ms=since_ms)
    results = await migrate(source, wd_db, ctx, only=ONLY)
    return {result.stage: result for result in results}


def _issue_keys(results: dict[str, StageResult]) -> set[IssueKey]:
    """Uwagi biegu jako zbiór ``(waga, kod, id)`` — do porównania przyrostu z pełnym biegiem."""
    return {
        (issue.severity, issue.code, tuple(issue.ids))
        for result in results.values()
        for issue in result.issues
    }


def _assert_no_new_alert(baseline: set[IssueKey], results: dict[str, StageResult]) -> None:
    """Przyrost nie zgłasza nowych uwag ``critical`` ani kodów ``*_missing``/``*_orphan``."""
    alerts = {
        key
        for key in _issue_keys(results)
        if key[0] == "critical" or key[1].endswith(("_missing", "_orphan"))
    }
    assert alerts <= baseline


def _assert_no_writes(results: dict[str, StageResult], stages_checked: tuple[str, ...]) -> None:
    """Wskazane etapy nie zapisały niczego w tym biegu."""
    for stage in stages_checked:
        assert (results[stage].created, results[stage].updated) == (0, 0), stage


def _assert_no_rows(results: dict[str, StageResult], stages_checked: tuple[str, ...]) -> None:
    """Etapy z filtrem nie przetworzyły ani jednego wiersza (``source_count`` po filtrze, §2)."""
    for stage in stages_checked:
        assert results[stage].source_count == 0, stage


async def test_since_none_is_full_run(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(a) ``since_ms=None``: pełny bieg tworzy wiersze, drugi bieg nie zapisuje niczego."""
    first = await _run(source, wd_db, run_ctx, None)
    assert list(first) == list(ONLY)
    assert all(result.created > 0 for result in first.values())
    assert not any(
        issue.severity == "critical" for result in first.values() for issue in result.issues
    )

    second = await _run(source, wd_db, run_ctx, None)
    _assert_no_writes(second, ONLY)


async def test_since_updates_only_changed_dataset(
    ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(b) Zmieniony ``knowledgebase`` → pisze tylko etap ``datasets`` (``updated == 1``)."""
    with _source(ragflow_src.dsn) as source:
        baseline = _issue_keys(await _run(source, wd_db, run_ctx, None))

    since = _max_update_time(ragflow_src.dsn) + GAP_MS
    _update_source(
        ragflow_src.dsn,
        "UPDATE `knowledgebase` SET `name` = %s, `update_time` = %s WHERE `id` = %s",
        ("kb-naive (zmieniona)", since, KB1_ID),
    )

    with _source(ragflow_src.dsn) as source:
        results = await _run(source, wd_db, run_ctx, since)

    assert (results["datasets"].created, results["datasets"].updated) == (0, 1)
    assert results["datasets"].source_count == 1
    _assert_no_writes(results, tuple(name for name in ONLY if name != "datasets"))
    _assert_no_rows(results, tuple(name for name in FILTERED if name != "datasets"))
    assert (
        await scalar(wd_db.sm, "SELECT name FROM datasets WHERE id = :id", {"id": KB1_ID})
        == "kb-naive (zmieniona)"
    )
    _assert_no_new_alert(baseline, results)


async def test_since_updates_only_changed_chat(
    ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) Zmieniony ``dialog`` → pisze tylko etap ``chats``; sesje i datasety nietknięte."""
    with _source(ragflow_src.dsn) as source:
        baseline = _issue_keys(await _run(source, wd_db, run_ctx, None))

    since = _max_update_time(ragflow_src.dsn) + GAP_MS
    _update_source(
        ragflow_src.dsn,
        "UPDATE `dialog` SET `name` = %s, `update_time` = %s WHERE `id` = %s",
        ("chat-book (zmieniony)", since, CHAT2_ID),
    )

    with _source(ragflow_src.dsn) as source:
        results = await _run(source, wd_db, run_ctx, since)

    assert (results["chats"].created, results["chats"].updated) == (0, 1)
    assert results["chats"].source_count == 1
    _assert_no_writes(results, tuple(name for name in ONLY if name != "chats"))
    _assert_no_rows(results, tuple(name for name in FILTERED if name != "chats"))
    assert (
        await scalar(wd_db.sm, "SELECT name FROM chats WHERE id = :id", {"id": CHAT2_ID})
        == "chat-book (zmieniony)"
    )
    _assert_no_new_alert(baseline, results)


async def test_since_rewrites_messages_of_changed_conversation(
    ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(d) Zmieniona ``conversation`` → wiadomości tej sesji na nowo, inne sesje nietknięte."""
    with _source(ragflow_src.dsn) as source:
        baseline = _issue_keys(await _run(source, wd_db, run_ctx, None))

    before = await scalar(
        wd_db.sm, "SELECT COUNT(*) FROM chat_messages WHERE session_id = :id", {"id": S1_ID}
    )
    other_before = await scalar(
        wd_db.sm, "SELECT COUNT(*) FROM chat_messages WHERE session_id = :id", {"id": S2_ID}
    )

    since = _max_update_time(ragflow_src.dsn) + GAP_MS
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT `message` FROM `conversation` WHERE `id` = %s", (S1_ID,))
        found = cursor.fetchone()
        assert found is not None
        messages = json.loads(str(found[0]))
        messages.append({"role": "assistant", "content": "Trzecia wiadomość (test --since)."})
        cursor.execute(
            "UPDATE `conversation` SET `message` = %s, `update_time` = %s WHERE `id` = %s",
            (json.dumps(messages, ensure_ascii=False), since, S1_ID),
        )

    with _source(ragflow_src.dsn) as source:
        results = await _run(source, wd_db, run_ctx, since)

    assert (results["sessions"].created, results["sessions"].updated) == (0, 1)
    assert results["sessions"].source_count == 1
    _assert_no_writes(results, tuple(name for name in ONLY if name != "sessions"))
    _assert_no_rows(results, tuple(name for name in FILTERED if name != "sessions"))
    after = await scalar(
        wd_db.sm, "SELECT COUNT(*) FROM chat_messages WHERE session_id = :id", {"id": S1_ID}
    )
    assert after == before + 1
    assert (
        await scalar(
            wd_db.sm, "SELECT message_count FROM chat_sessions WHERE id = :id", {"id": S1_ID}
        )
        == after
    )
    assert (
        await scalar(
            wd_db.sm, "SELECT COUNT(*) FROM chat_messages WHERE session_id = :id", {"id": S2_ID}
        )
        == other_before
    )
    _assert_no_new_alert(baseline, results)


async def test_since_in_future_writes_nothing(
    ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(e) ``since_ms`` po wszystkich ``update_time`` źródła → żaden etap nic nie zapisuje."""
    with _source(ragflow_src.dsn) as source:
        baseline = _issue_keys(await _run(source, wd_db, run_ctx, None))

    datasets_before = await scalar(wd_db.sm, "SELECT COUNT(*) FROM datasets")
    sessions_before = await scalar(wd_db.sm, "SELECT COUNT(*) FROM chat_sessions")
    future = _max_update_time(ragflow_src.dsn) + 10 * GAP_MS
    with _source(ragflow_src.dsn) as source:
        results = await _run(source, wd_db, run_ctx, future)

    _assert_no_writes(results, ONLY)
    _assert_no_rows(results, FILTERED)
    assert not any(
        issue.severity == "critical" for result in results.values() for issue in result.issues
    )
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM datasets") == datasets_before
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chat_sessions") == sessions_before
    _assert_no_new_alert(baseline, results)


async def test_since_updates_only_changed_document(
    ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Zmieniony ``document`` → tylko on jest pisany, a jego blob zostaje na miejscu."""
    with _source(ragflow_src.dsn) as source:
        baseline = _issue_keys(await _run(source, wd_db, run_ctx, None))

    before = await row(
        wd_db.sm,
        "SELECT location, content_hash FROM documents WHERE id = :id",
        {"id": DOC1_ID},
    )

    since = _max_update_time(ragflow_src.dsn) + GAP_MS
    _update_source(
        ragflow_src.dsn,
        "UPDATE `document` SET `name` = %s, `update_time` = %s WHERE `id` = %s",
        ("raport (zmieniony).pdf", since, DOC1_ID),
    )

    with _source(ragflow_src.dsn) as source:
        results = await _run(source, wd_db, run_ctx, since)

    assert (results["documents"].created, results["documents"].updated) == (0, 1)
    assert results["documents"].source_count == 1
    _assert_no_writes(results, tuple(name for name in ONLY if name != "documents"))
    _assert_no_rows(results, tuple(name for name in FILTERED if name != "documents"))
    changed = await row(
        wd_db.sm,
        "SELECT name, location, content_hash FROM documents WHERE id = :id",
        {"id": DOC1_ID},
    )
    assert changed["name"] == "raport (zmieniony).pdf"
    assert changed["location"] == before["location"]
    assert changed["content_hash"] == before["content_hash"]
    assert await scalar(wd_db.sm, "SELECT name FROM documents WHERE id = :id", {"id": DOC2_ID}) == (
        "umowa.docx"
    )
    _assert_no_new_alert(baseline, results)


async def test_since_changed_file_is_not_an_orphan(
    ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(g) Zmieniony plik w niezmienionym drzewie: pisany i bez fałszywego ``file_orphan``."""
    with _source(ragflow_src.dsn) as source:
        baseline = _issue_keys(await _run(source, wd_db, run_ctx, None))

    since = _max_update_time(ragflow_src.dsn) + GAP_MS
    _update_source(
        ragflow_src.dsn,
        "UPDATE `file` SET `update_time` = %s WHERE `id` = %s",
        (since, LOCAL_FILE_ID),
    )

    with _source(ragflow_src.dsn) as source:
        results = await _run(source, wd_db, run_ctx, since)

    assert (results["documents"].created, results["documents"].updated) == (0, 1)
    assert results["documents"].source_count == 1
    assert [issue for issue in results["documents"].issues if issue.code == "file_orphan"] == []
    _assert_no_writes(results, tuple(name for name in ONLY if name != "documents"))
    _assert_no_rows(results, tuple(name for name in FILTERED if name != "documents"))
    assert (
        await scalar(wd_db.sm, "SELECT name FROM files WHERE id = :id", {"id": LOCAL_FILE_ID})
        == "notatka-lokalna.txt"
    )
    _assert_no_new_alert(baseline, results)
