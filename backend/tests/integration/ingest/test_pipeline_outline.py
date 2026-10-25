"""Testy integracyjne kroku 11c: spis treści na końcu ``parse_document`` (K21 §2 p. 1-3; T3).

Marker db + fakellm (fake-llm z verify.sh); upload, kolejka i kontener jak u workera.
Sprawdzają profil w ``document_profiles``, linię logu w ``progress_msg`` i to, że błąd
wyznaczania spisu nie przewraca parsowania.
"""

import json
import os
from collections.abc import AsyncIterator
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
from app.services import ingest_pipeline as pipeline
from app.services.ingest_pipeline import run_parse
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import (
    claim_context,
    make_container,
    make_docx_bytes,
    make_pdf_bytes,
    make_source,
)
from tests.unit.parsing.outline_pdf import make_outlined_pdf

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

BOOKMARKS = [("Rozdzial I", 0), ("Podrozdzial", 1), ("Dzial", 2)]


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path, modele fake zarejestrowane."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


async def _parse(
    container: Container,
    ds: DatasetRow,
    content: bytes,
    filename: str,
    *,
    clear_existing: bool = False,
) -> str:
    """Upload → claim → ``run_parse``; zwraca identyfikator dokumentu."""
    doc = await container.ingest.upload(
        ds.id, make_source(content, filename), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id, clear_existing=clear_existing)
    await run_parse(container, ctx.task, ctx, executor=None)
    return doc.id


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
) -> tuple[list[dict[str, Any]], str, int]:
    """Profil dokumentu z ``document_profiles`` (asercje testowe)."""
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
            .one()
        )
    return json.loads(row["outline"]), str(row["outline_source"]), int(row["outline_count"])


def _bodies(progress_msg: str) -> list[str]:
    """Linie progress_msg bez prefiksu godziny."""
    return [line.split(" ", 1)[1] for line in progress_msg.split("\n")]


async def test_pdf_bookmarks_write_profile_and_log_line(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PDF z zakładkami → profil ``pdf_bookmarks``, strona = indeks celu + 1, linia logu."""
    ds = await seed_dataset(sm)
    document_id = await _parse(container, ds, make_outlined_pdf(BOOKMARKS), "rocznik.pdf")

    outline, source, count = await _profile(sm, document_id)
    assert source == "pdf_bookmarks"
    assert outline == [
        {"level": 0, "title": "Rozdzial I", "page": 1},
        {"level": 1, "title": "Podrozdzial", "page": 2},
        {"level": 2, "title": "Dzial", "page": 3},
    ]
    assert count == len(outline)
    row = await _document(sm, document_id)
    assert row.run == "3"
    assert "Outline: 3 entries (PDF bookmarks)" in _bodies(row.progress_msg)


async def test_pdf_without_bookmarks_falls_back_to_none(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PDF bez zakładek i bez nagłówków → ``none`` z pustym spisem i linią logu (K21 §2 p. 2c)."""
    ds = await seed_dataset(sm)
    document_id = await _parse(container, ds, make_pdf_bytes(), "umowa.pdf")

    outline, source, count = await _profile(sm, document_id)
    assert (outline, source, count) == ([], "none", 0)
    row = await _document(sm, document_id)
    assert "Outline: none (no bookmarks or headings)" in _bodies(row.progress_msg)


async def test_docx_headings_write_profile_and_log_line(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DOCX bez zakładek → nagłówki bloków konwersji jako spis (K21 §2 p. 2b)."""
    ds = await seed_dataset(sm)
    document_id = await _parse(container, ds, make_docx_bytes(), "notatka.docx")

    outline, source, _ = await _profile(sm, document_id)
    assert source == "headings"
    assert [item["title"] for item in outline] == ["Umowa najmu"]
    assert outline[0]["level"] == 0
    row = await _document(sm, document_id)
    assert "Outline: 1 entries (headings)" in _bodies(row.progress_msg)


async def test_reparse_overwrites_profile(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Reparsowanie nadpisuje profil (upsert po ``document_id``; K21 §1)."""
    ds = await seed_dataset(sm)
    content = make_outlined_pdf(BOOKMARKS)
    document_id = await _parse(container, ds, content, "rocznik.pdf")
    await _parse(container, ds, content, "rocznik.pdf", clear_existing=True)

    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM document_profiles WHERE document_id = :d"),
                    {"d": document_id},
                )
            )
            .scalars()
            .one()
        )
    assert int(rows) == 1
    outline, source, _ = await _profile(sm, document_id)
    assert source == "pdf_bookmarks"
    assert len(outline) == len(BOOKMARKS)


async def test_outline_line_present_before_run_done(
    container: Container, sm: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linia ``Outline:`` jest już w ``progress_msg``, gdy atomowy zapis ustawia ``run='3'`` (T12).

    Kolejność kroków 11c przed 11 (K21 §2 p. 1): gdy ``write_parse_result`` widzi wiersz dokumentu
    po raz pierwszy, ``run`` nie jest jeszcze ``'3'``, a log zawiera już wiersz spisu — okno między
    „Sukcesem” w UI a linią „Indexing done” nie obejmuje wyznaczania spisu.
    """
    real_write = pipeline.write_parse_result
    seen: dict[str, str] = {}

    async def spy(*args: Any, **kwargs: Any) -> None:
        row = await _document(sm, kwargs["doc"].id)
        seen["run"] = row.run
        seen["progress_msg"] = row.progress_msg
        await real_write(*args, **kwargs)

    monkeypatch.setattr(pipeline, "write_parse_result", spy)
    ds = await seed_dataset(sm)
    await _parse(container, ds, make_outlined_pdf(BOOKMARKS), "rocznik.pdf")

    assert seen["run"] != "3"
    assert "Outline: 3 entries (PDF bookmarks)" in _bodies(seen["progress_msg"])


async def test_outline_failure_keeps_parse_done(
    container: Container, sm: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Błąd spisu nie psuje parsowania: ``none``, ostrzeżenie, ``run='3'`` (K21 §2 p. 1)."""

    def boom(*_args: object, **_kwargs: object) -> list[dict[str, Any]]:
        raise RuntimeError("uszkodzone zakladki")

    monkeypatch.setattr("app.services.ingest_outline.outline_from_pdf", boom)
    ds = await seed_dataset(sm)
    document_id = await _parse(container, ds, make_outlined_pdf(BOOKMARKS), "rocznik.pdf")

    outline, source, count = await _profile(sm, document_id)
    assert (outline, source, count) == ([], "none", 0)
    row = await _document(sm, document_id)
    assert row.run == "3"
    assert row.progress == 1.0
    bodies = _bodies(row.progress_msg)
    assert "[WARNING] Outline detection failed: uszkodzone zakladki" in bodies
    assert "Outline: none (no bookmarks or headings)" in bodies
