"""Testy integracyjne sekcji ``parse`` i próbki kontraktowej ``verify`` (brief T7, kontrakt E4-6c
§3.2, §5 i §6).

Harness jak w ``test_verify.py``: ``ragflow_src``/``source``/``wd_db``/``run_ctx`` i pełny bieg
``run_all(source, wd_db.sm, run_ctx)``. Próbkę kontraktową wołamy przez ``asyncio.to_thread`` —
``TestClient`` stawia własną pętlę zdarzeń (kontrakt §6). Rozbieżności wywołujemy surowym SQL-em
na ``wd_db.sm``, bo próbka czyta wyłącznie stan celu i odpowiedzi API.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tools.ragflow_migrate import cli
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext
from app.tools.ragflow_migrate.verify import run_verify
from app.tools.ragflow_migrate.verify_contract import run_contract_sample
from app.tools.ragflow_migrate.verify_parse import collect_parse
from app.tools.ragflow_migrate.verify_types import (
    ContractMismatch,
    ContractSample,
    ParseFailure,
    ParseSummary,
    VerifyReport,
)
from tests.integration.ragflow_migrate._chat_fixtures import source_writer
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

#: Id z fixture'u (``data.sql``) — te same stałe co w pozostałych testach migracji.
U1_ID = "b0a1c2d3e4f5061728394a5b6c7d8e91"
D1_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f01"
D2_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f02"
S1_ID = "7c6d5e4f3a2b10819293a4b5c6d7e801"
S2_ID = "7c6d5e4f3a2b10819293a4b5c6d7e802"
S3_ID = "7c6d5e4f3a2b10819293a4b5c6d7e803"
EXTRA_SESSION_ID = "7c6d5e4f3a2b10819293a4b5c6d7e899"

#: Nazwy źródłowe czatu i sesji, których pilnują testy rozbieżności (``data.sql``).
D1_NAME = "chat-rag"
S1_NAME = "session-1"
S1_MESSAGES = 2
S2_NAME = "session-2"
EXTRA_SESSION_NAME = "sesja-nadmiarowa"

#: Czasy z fixture'u (``data.sql``) — wstawiane wiersze źródeł i celu.
SESSION_CREATE_MS = 1759306140000

#: Liczby próbki na fixture: dwa czaty właścicieli z tokenem i dwie rozmowy czatu ``d1``.
FIXTURE_CHATS = 2
FIXTURE_SESSIONS = 2

#: Wartości podstawione w teście liczników parsowania: dwa nieudane i jeden gotowy dokument.
FAILED_DOCUMENTS = 2
DONE_CHUNKS = 7

#: Długość ``reason`` nieudanego parsowania (kontrakt §3.2).
REASON_LIMIT = 200
LONG_PROGRESS_MSG = "p" * (REASON_LIMIT + 50)

EXIT_OK = 0
EXIT_CRITICAL = 2


async def _contract(source: Source, wd_db: WdDb) -> ContractSample:
    """``run_contract_sample`` na ustawieniach celu, w wątku (własna pętla ``TestClient``)."""
    return await asyncio.to_thread(run_contract_sample, source, wd_db.settings)


async def _parse(wd_db: WdDb) -> ParseSummary:
    """``collect_parse`` na sesji celu (świeża transakcja)."""
    async with wd_db.sm() as session:
        return await collect_parse(session)


async def _verify(ragflow_src: SourceDb, wd_db: WdDb, ctx: RunContext) -> VerifyReport:
    """``run_verify`` na źródle fixture'u (połączenie zakłada i zamyka sam test)."""
    src = Source.connect(ragflow_src.dsn)
    try:
        return await run_verify(src, wd_db.settings, ctx)
    finally:
        src.close()


async def _exec(wd_db: WdDb, statements: Sequence[tuple[str, dict[str, Any]]]) -> None:
    """Wykonuje instrukcje SQL w jednej transakcji celu (zapis testu, nie kod migracji)."""
    async with wd_db.sm() as session:
        for sql, params in statements:
            await session.execute(text(sql), params)
        await session.commit()


async def _scalars(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> list[str]:
    """Kolumna tekstowa z bazy celu (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return [str(value) for value in result.scalars().all()]


async def _count(sm: async_sessionmaker[AsyncSession], sql: str) -> int:
    """Pojedyncza liczba z bazy celu."""
    async with sm() as session:
        result = await session.execute(text(sql))
        return int(result.scalar_one())


async def _cli_verify(ragflow_src: SourceDb, report_dir: Path) -> int:
    """``cli.main(["verify", …])`` na bazie celu testu; ``asyncio.run`` idzie w osobny wątek."""
    return await asyncio.to_thread(
        cli.main,
        ["verify", "--src-mysql", ragflow_src.dsn, "--report-dir", str(report_dir)],
    )


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


async def test_contract_sample_matches_source_after_full_migration(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Czysty bieg: brak rozbieżności, liczby porównanych czatów i sesji z fixture'u.

    Fixture ma token dla każdego właściciela czatu (``data.sql``), więc nic nie jest pominięte.
    """
    await run_all(source, wd_db.sm, run_ctx)
    sample = await _contract(source, wd_db)

    assert sample.mismatches == []
    assert sample.chats_checked == FIXTURE_CHATS
    assert sample.sessions_checked == FIXTURE_SESSIONS
    assert sample.skipped_no_key == []


async def test_collect_parse_counts_unstarted_documents(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(b) Po migracji wszystkie dokumenty czekają (``run='0'``), bez kawałków i bez błędów."""
    await run_all(source, wd_db.sm, run_ctx)
    summary = await _parse(wd_db)

    assert summary.unstarted == await _count(wd_db.sm, "SELECT COUNT(*) FROM documents")
    assert (summary.done, summary.failed) == (0, 0)
    assert summary.chunks_total == 0
    assert summary.failures == []


async def test_collect_parse_reports_failed_and_done_documents(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) ``run='4'`` → ``failures`` (``error``, potem ``progress_msg``, obcięte do 200 znaków)."""
    await run_all(source, wd_db.sm, run_ctx)
    documents = await _scalars(wd_db.sm, "SELECT id FROM documents ORDER BY id")
    failed_id, done_id, progress_id = documents[0], documents[1], documents[2]
    await _exec(
        wd_db,
        [
            ("UPDATE documents SET run = '4', error = 'boom' WHERE id = :id", {"id": failed_id}),
            (
                "UPDATE documents SET run = '3', chunk_count = :chunks WHERE id = :id",
                {"id": done_id, "chunks": DONE_CHUNKS},
            ),
            (
                "UPDATE documents SET run = '4', error = '', progress_msg = :msg WHERE id = :id",
                {"id": progress_id, "msg": LONG_PROGRESS_MSG},
            ),
        ],
    )
    summary = await _parse(wd_db)

    assert summary.failed == FAILED_DOCUMENTS
    assert summary.failures == [
        ParseFailure(failed_id, "boom"),
        ParseFailure(progress_id, LONG_PROGRESS_MSG[:REASON_LIMIT]),
    ]
    assert summary.done == 1
    assert summary.chunks_total == DONE_CHUNKS
    assert summary.unstarted == len(documents) - (FAILED_DOCUMENTS + 1)


async def test_missing_chat_is_contract_mismatch(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(d) Skasowany czat w celu → ``ContractMismatch(kind="chat", field="missing")``."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("DELETE FROM chats WHERE id = :id", {"id": D1_ID})])
    sample = await _contract(source, wd_db)

    assert sample.mismatches == [
        ContractMismatch("chat", D1_ID, "missing", D1_NAME, ""),
    ]
    # Czat bez odpowiedzi w API nie ma czego porównywać w sesjach (API zwróciłoby odmowę).
    assert sample.sessions_checked == 0


async def test_changed_chat_name_is_contract_mismatch(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(e) Zmieniona nazwa czatu w celu → mismatch ``field="name"`` z nazwą źródła."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("UPDATE chats SET name = 'inna' WHERE id = :id", {"id": D1_ID})])
    sample = await _contract(source, wd_db)

    assert sample.mismatches == [ContractMismatch("chat", D1_ID, "name", D1_NAME, "inna")]


async def test_removed_session_messages_are_contract_mismatch(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Usunięte wiadomości sesji → mismatch ``field="message_count"``."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("DELETE FROM chat_messages WHERE session_id = :id", {"id": S1_ID})])
    sample = await _contract(source, wd_db)

    assert sample.mismatches == [
        ContractMismatch("session", S1_ID, "message_count", str(S1_MESSAGES), "0")
    ]
    assert sample.sessions_checked == FIXTURE_SESSIONS


async def test_contract_sample_never_exposes_owner_token(
    source: Source,
    wd_db: WdDb,
    run_ctx: RunContext,
    expectations: dict[str, Any],
) -> None:
    """(g) Rozbieżności próbki nie zawierają tokenu właściciela (kontrakt §6)."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("UPDATE chats SET name = 'inna' WHERE id = :id", {"id": D1_ID})])
    sample = await _contract(source, wd_db)
    dump = json.dumps(asdict(sample), ensure_ascii=False)

    assert sample.mismatches
    for entry in expectations["tokens"]:
        assert entry["token"] not in dump


async def test_missing_and_renamed_sessions_are_contract_mismatches(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(i) Sesja brakująca i sesja o zmienionej nazwie → mismatches ``missing`` i ``name``."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(
        wd_db,
        [
            ("DELETE FROM chat_sessions WHERE id = :id", {"id": S1_ID}),
            ("UPDATE chat_sessions SET name = 'inna' WHERE id = :id", {"id": S2_ID}),
        ],
    )
    sample = await _contract(source, wd_db)

    assert sample.mismatches == [
        ContractMismatch("session", S1_ID, "missing", S1_NAME, ""),
        ContractMismatch("session", S2_ID, "name", S2_NAME, "inna"),
    ]
    assert sample.sessions_checked == FIXTURE_SESSIONS


async def test_extra_session_in_target_is_contract_mismatch(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(j) Sesja obecna w celu, a nieobecna w źródle → mismatch ``field="missing"``."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(
        wd_db,
        [
            (
                "INSERT INTO chat_sessions"
                " (id, chat_id, name, create_time, create_date, update_time, update_date)"
                " VALUES (:id, :chat_id, :name, :ms, NOW(3), :ms, NOW(3))",
                {
                    "id": EXTRA_SESSION_ID,
                    "chat_id": D1_ID,
                    "name": EXTRA_SESSION_NAME,
                    "ms": SESSION_CREATE_MS,
                },
            )
        ],
    )
    sample = await _contract(source, wd_db)

    assert ContractMismatch("session", EXTRA_SESSION_ID, "missing", "", EXTRA_SESSION_NAME) in (
        sample.mismatches
    )


async def test_session_without_source_messages_matches(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(k) Rozmowa bez ``message`` (NULL) → sesja porównana, zero wiadomości po obu stronach."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO `conversation` (`id`,`create_time`,`create_date`,`update_time`,"
            "`update_date`,`dialog_id`,`name`,`message`,`reference`,`user_id`)"
            " VALUES (%s, %s, NOW(), %s, NOW(), %s, %s, %s, %s, %s)",
            (
                S3_ID,
                SESSION_CREATE_MS,
                SESSION_CREATE_MS,
                D2_ID,
                "session-pusta",
                None,
                None,
                "alice@rf.test",
            ),
        )
    await run_all(source, wd_db.sm, run_ctx)
    sample = await _contract(source, wd_db)

    assert sample.mismatches == []
    assert sample.sessions_checked == FIXTURE_SESSIONS + 1


async def test_chat_without_owner_key_is_skipped(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(l) Właściciel czatu bez klucza w źródle → id czatu w ``skipped_no_key``, nie porównany."""
    await run_all(source, wd_db.sm, run_ctx)
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM `api_token` WHERE `tenant_id` = %s", (U1_ID,))
    sample = await _contract(source, wd_db)

    assert sample.skipped_no_key == [D1_ID]
    assert sample.chats_checked == 1
    assert sample.mismatches == []


async def test_unauthenticated_response_is_contract_mismatch(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(m) Klucz nieobecny w celu → odmowa API; czaty zgłoszone jako ``missing`` z komunikatem."""
    await run_all(source, wd_db.sm, run_ctx)
    await _exec(wd_db, [("DELETE FROM api_keys", {})])
    sample = await _contract(source, wd_db)

    assert [mismatch.id for mismatch in sample.mismatches] == [D1_ID, D2_ID]
    assert {mismatch.field for mismatch in sample.mismatches} == {"missing"}
    assert all(mismatch.actual for mismatch in sample.mismatches)
    assert sample.chats_checked == FIXTURE_CHATS
    assert sample.sessions_checked == 0


async def test_source_without_dialogs_checks_nothing(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(n) Źródło bez czatów → pusta próbka (nie ma czego porównywać)."""
    await run_all(source, wd_db.sm, run_ctx)
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM `dialog`")
    sample = await _contract(source, wd_db)

    assert sample == ContractSample(
        chats_checked=0, sessions_checked=0, mismatches=[], skipped_no_key=[]
    )


async def test_verify_full_run_and_cli_exit_codes(
    ragflow_src: SourceDb,
    wd_db: WdDb,
    run_ctx: RunContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(h) Pełny ``run_verify`` bez uwag krytycznych; CLI rc 0, po skasowaniu czatu rc 2."""
    source = Source.connect(ragflow_src.dsn)
    try:
        await run_all(source, wd_db.sm, run_ctx)
    finally:
        source.close()
    report = await _verify(ragflow_src, wd_db, run_ctx)

    assert report.has_critical() is False
    assert report.contract == ContractSample(FIXTURE_CHATS, FIXTURE_SESSIONS, [], [])

    _cli_env(monkeypatch, wd_db, tmp_path)
    report_dir = tmp_path / "reports"
    assert await _cli_verify(ragflow_src, report_dir) == EXIT_OK

    await _exec(wd_db, [("DELETE FROM chats WHERE id = :id", {"id": D1_ID})])
    assert await _cli_verify(ragflow_src, report_dir) == EXIT_CRITICAL
