"""Testy integracyjne run_parse: PDF/DOCX/XLSX → zapis, progress_msg, derived HTML (brief T7).

Marker db + fakellm (fake-llm z verify.sh); kolejka i kontener jak u workera.
"""

import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import chunk_vectors
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.uow import transaction
from app.services.ingest_pipeline import run_parse
from app.storage.keys import derived_key
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import (
    claim_context,
    make_container,
    make_docx_bytes,
    make_pdf_bytes,
    make_source,
    make_xlsx_bytes,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

_TXT = (
    "Umowa najmu lokalu mieszkalnego. Lokator płaci czynsz piątego dnia miesiąca.\n" * 4
).encode()


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path, modele fake zarejestrowane."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


async def _document(
    sm: async_sessionmaker[AsyncSession], document_id: str
) -> documents_repo.DocumentRow:
    """Świeży odczyt dokumentu (asercje testowe)."""
    async with transaction(sm) as session:
        row = await documents_repo.get(session, document_id)
    assert row is not None
    return row


async def _scalar(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> int:
    """Skalar z SQL (asercje testowe)."""
    async with transaction(sm) as session:
        return int((await session.execute(text(sql), params)).scalar_one())


def _bodies(progress_msg: str) -> list[str]:
    """Linie progress_msg bez prefiksu godziny."""
    return [line.split(" ", 1)[1] for line in progress_msg.split("\n")]


async def test_pdf_docx_xlsx_produce_committed_chunks(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PDF (2 strony), DOCX, XLSX → run='3', progress=1, chunki committed, wektory, liczniki."""
    ds = await seed_dataset(sm)
    total = 0
    for filename, content in (
        ("umowa.pdf", make_pdf_bytes()),
        ("notatka.docx", make_docx_bytes()),
        ("tabela.xlsx", make_xlsx_bytes()),
    ):
        doc = await container.ingest.upload(
            ds.id, make_source(content, filename), created_by=ds.tenant_id
        )
        ctx = await claim_context(container, doc.id)
        await run_parse(container, ctx.task, ctx, executor=None)

        row = await _document(sm, doc.id)
        assert row.run == "3"
        assert row.progress == 1.0
        committed = await _scalar(
            sm,
            "SELECT COUNT(*) FROM chunks WHERE document_id = :d AND committed = 1",
            d=doc.id,
        )
        assert committed > 0
        assert row.chunk_count == committed
        async with transaction(sm) as session:
            vectors = await chunk_vectors.count_by_document(session, ds.embedding_dim, doc.id)
            stems = (
                (
                    await session.execute(
                        text("SELECT content_stem FROM chunks WHERE document_id = :d"),
                        {"d": doc.id},
                    )
                )
                .scalars()
                .all()
            )
        assert vectors == committed
        assert all(stem for stem in stems)
        total += committed

    async with transaction(sm) as session:
        dataset = await datasets_repo.get(session, ds.id)
    assert dataset is not None
    assert dataset.chunk_count == total


async def test_progress_msg_lines_in_order(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """progress_msg po PDF: kolejne linie z prefiksem HH:MM:SS (brief T7; C1 E5-H8a)."""
    ds = await seed_dataset(sm)
    doc = await container.ingest.upload(
        ds.id, make_source(make_pdf_bytes(), "umowa.pdf"), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)

    row = await _document(sm, doc.id)
    lines = row.progress_msg.split("\n")
    for line in lines:
        assert re.match(r"^\d\d:\d\d:\d\d ", line)
    bodies = _bodies(row.progress_msg)
    n = row.chunk_count
    assert len(bodies) == 8  # noqa: PLR2004 — konwersja partiami (C1) + komunikaty C7 + spis
    assert bodies[0] == "Task has been received."
    # C1: jednostka = strona fazy A + strona `text` fazy C (2 strony → 4 jednostki);
    # wpis `Page(1~N): … finished` zniknął.
    assert bodies[1] == "Converting pages 1/2"
    assert bodies[2] == "Converting pages 2/2"
    assert bodies[3] == "Converted 2 pages (text layer)"
    assert bodies[4] == f"Generate {n} chunks"
    assert bodies[5] == f"Embedding chunks ({n}/{n})"
    assert bodies[6] == "Outline: none (no bookmarks or headings)"  # krok 11c (K21 §2 p. 3)
    assert re.fullmatch(r"Indexing done \(\d+\.\d\ds\)\. Done\.", bodies[7])


async def test_normalized_html_in_storage(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Po DONE istnieje derived_key(ds, doc, "normalized.html") (brief T7)."""
    ds = await seed_dataset(sm)
    doc = await container.ingest.upload(
        ds.id, make_source(_TXT, "notatka.txt"), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)

    assert await container.storage.exists(derived_key(ds.id, doc.id, "normalized.html"))
    assert await container.storage.exists(doc.location)
