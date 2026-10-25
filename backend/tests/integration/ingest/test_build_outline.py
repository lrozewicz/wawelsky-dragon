"""Testy integracyjne zadania ``build_outline`` i przeglądu workera (K21 §2 p. 4; T4).

Marker db: MariaDB po migracji; storage w ``tmp_path`` i prawdziwa kolejka (``DbTaskQueue``).
Sprawdzają przegląd ``sweep_once`` (porcja, brak duplikatów), handler na plikach rzeczywistych
(PDF → zakładki, DOCX → nagłówki) oraz ścieżkę dokumentu po imporcie K19 (``run='3'`` bez
profilu) uzupełnianego przeglądem — bez ponownego parsowania.
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from app.storage.keys import validate_key
from app.worker.handlers.build_outline import build_outline
from app.worker.outline_sweep import sweep_once
from app.worker.queue import NewTask
from tests.integration.ingest.conftest import make_document_row, seed_dataset
from tests.integration.ingest.pipeline_helpers import (
    WORKER_ID,
    build_context,
    make_container,
    make_docx_bytes,
    worker_queue,
)
from tests.unit.parsing.outline_pdf import make_outlined_pdf

pytestmark = pytest.mark.db

BOOKMARKS = [("Rozdzial I", 0), ("Podrozdzial", 1), ("Dzial", 2)]


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path (jak u workera)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


async def _insert_document(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    ds: DatasetRow,
    name: str,
    content: bytes | None,
) -> str:
    """Dokument ``run='3'`` z oryginałem w storage (``content=None`` → bez pliku) bez profilu."""
    document_id = uuid.uuid4().hex
    row = replace(make_document_row(ds, document_id=document_id, name=name), run="3", progress=1.0)
    if content is not None:
        await container.storage.put(validate_key(row.location), content)
    async with transaction(sm) as session:
        await documents_repo.insert(session, row)
    return document_id


async def _document(
    sm: async_sessionmaker[AsyncSession], document_id: str
) -> documents_repo.DocumentRow:
    """Świeży odczyt dokumentu (asercje testowe)."""
    async with transaction(sm) as session:
        row = await documents_repo.get(session, document_id)
    assert row is not None
    return row


async def _profile(
    sm: async_sessionmaker[AsyncSession], document_id: str
) -> tuple[list[dict[str, Any]], str, int] | None:
    """Profil dokumentu z ``document_profiles`` albo ``None`` gdy brak wiersza."""
    async with transaction(sm) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT outline, outline_source, outline_count FROM document_profiles"
                        " WHERE document_id = :d"
                    ),
                    {"d": document_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    return json.loads(row["outline"]), str(row["outline_source"]), int(row["outline_count"])


async def _queued_outline_tasks(sm: async_sessionmaker[AsyncSession]) -> list[tuple[str, int]]:
    """Zadania ``build_outline`` w kolejce: ``(public_id, priority)`` (asercje testowe)."""
    async with transaction(sm) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT public_id, priority FROM tasks"
                    " WHERE task_type = 'build_outline' AND status = 'queued'"
                )
            )
        ).all()
    return [(str(row[0]), int(row[1])) for row in rows]


def _bodies(progress_msg: str) -> list[str]:
    """Linie progress_msg bez prefiksu godziny."""
    return [line.split(" ", 1)[1] for line in progress_msg.split("\n")]


async def _run_claimed_outline(container: Container, document_id: str) -> None:
    """Claimuje zakolejkowane ``build_outline`` tego dokumentu i wykonuje handler."""
    queue = worker_queue(container)
    task = await queue.claim(WORKER_ID, ["build_outline"])
    assert task is not None, "zadanie build_outline musi być do wzięcia"
    assert task.payload["document_id"] == document_id
    await build_outline(task, build_context(container, task, queue))


async def test_sweep_enqueues_once_then_skips_queued(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """3 dokumenty bez profilu → 3 zadania tła; drugi przegląd → 0 nowych (K21 §2 p. 4)."""
    ds = await seed_dataset(sm)
    for index in range(3):
        await _insert_document(container, sm, ds, f"rocznik-{index}.pdf", None)

    first = await sweep_once(container)
    assert first == 3  # noqa: PLR2004 — trzy dokumenty bez profilu z briefu
    tasks = await _queued_outline_tasks(sm)
    assert len(tasks) == 3  # noqa: PLR2004 — trzy zakolejkowane zadania
    assert {priority for _, priority in tasks} == {-1}  # priorytet tła

    second = await sweep_once(container)
    assert second == 0
    assert len(await _queued_outline_tasks(sm)) == 3  # noqa: PLR2004 — bez duplikatów


async def test_handler_pdf_bookmarks_writes_profile_and_log(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PDF z zakładkami → profil ``pdf_bookmarks``; ``run``/``progress`` bez zmian (K21 §2 p. 4)."""
    ds = await seed_dataset(sm)
    document_id = await _insert_document(
        container, sm, ds, "rocznik.pdf", make_outlined_pdf(BOOKMARKS)
    )

    await sweep_once(container)
    await _run_claimed_outline(container, document_id)

    assert await _profile(sm, document_id) == (
        [
            {"level": 0, "title": "Rozdzial I", "page": 1},
            {"level": 1, "title": "Podrozdzial", "page": 2},
            {"level": 2, "title": "Dzial", "page": 3},
        ],
        "pdf_bookmarks",
        3,
    )
    row = await _document(sm, document_id)
    assert row.run == "3"
    assert row.progress == 1.0
    assert row.chunk_count == 0  # brak ponownego parsowania — chunki bez zmian
    assert "Outline: 3 entries (PDF bookmarks)" in _bodies(row.progress_msg)


async def test_handler_non_pdf_uses_headings(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DOCX → nagłówki bloków konwersji bez modeli jako spis (K21 §2 p. 2b/4)."""
    ds = await seed_dataset(sm)
    document_id = await _insert_document(container, sm, ds, "notatka.docx", make_docx_bytes())

    await sweep_once(container)
    await _run_claimed_outline(container, document_id)

    outline, source, count = await _profile(sm, document_id)  # type: ignore[misc]
    assert source == "headings"
    assert [item["title"] for item in outline] == ["Umowa najmu"]
    assert count == 1
    row = await _document(sm, document_id)
    assert "Outline: 1 entries (headings)" in _bodies(row.progress_msg)


async def test_handler_error_writes_none_profile_and_log(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak oryginału w storage → ``none`` + ostrzeżenie, bez zapętlenia (K21 §2 p. 4)."""
    ds = await seed_dataset(sm)
    # Dokument z ``location`` wskazującym na nieistniejący plik (oryginał usunięty poza API).
    document_id = await _insert_document(container, sm, ds, "brak.pdf", None)

    await sweep_once(container)
    await _run_claimed_outline(container, document_id)

    assert await _profile(sm, document_id) == ([], "none", 0)
    row = await _document(sm, document_id)
    bodies = _bodies(row.progress_msg)
    assert any(body.startswith("[WARNING] Outline detection failed:") for body in bodies)
    assert "Outline: none (no bookmarks or headings)" in bodies


async def test_handler_deleted_document_finishes_without_error(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zadanie wskazujące nieistniejący dokument → koniec bez błędu i bez profilu (§2 p. 4).

    FK ``tasks.document_id`` kaskaduje z usunięciem dokumentu, więc realnie zadanie znika razem
    z dokumentem; gałąź broni się przed ``document_id`` wskazującym brak wiersza (payload bez
    kolumny ``document_id``).
    """
    queue = worker_queue(container)
    missing_id = uuid.uuid4().hex
    await queue.enqueue(
        NewTask(
            task_type="build_outline",
            payload={"document_id": missing_id},
            priority=-1,
        )
    )
    task = await queue.claim(WORKER_ID, ["build_outline"])
    assert task is not None

    await build_outline(task, build_context(container, task, queue))

    assert await _profile(sm, missing_id) is None


async def test_sweep_fills_profile_for_post_import_document(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dokument po imporcie (``run='3'`` bez profilu) dostaje profil po przeglądzie (§2 p. 4)."""
    ds = await seed_dataset(sm)
    document_id = await _insert_document(
        container, sm, ds, "notatka.md", b"# Umowa najmu\n\ntekst\n"
    )
    assert await _profile(sm, document_id) is None  # stan po imporcie: dokument bez profilu

    assert await sweep_once(container) == 1
    await _run_claimed_outline(container, document_id)

    outline, source, _ = await _profile(sm, document_id)  # type: ignore[misc]
    assert source == "headings"
    assert [item["title"] for item in outline] == ["Umowa najmu"]
