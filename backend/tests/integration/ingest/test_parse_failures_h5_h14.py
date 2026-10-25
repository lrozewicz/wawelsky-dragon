"""Integracyjne testy porażek parsowania: H5 (bomba ZIP) i H14 (timeout parsera, kontrakt T2).

Prawdziwy Worker + MariaDB: dokument-bomba i dokument z przekroczonym `WD_PARSE_TIMEOUT_S`
muszą zakończyć się `run='4'` (FAIL) z komunikatem błędu (trwałe → `fail_permanent`).
"""

import asyncio
import contextlib
import io
import os
import time
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.parsing.types import ConvertedDocument, ConvertOptions
from app.worker.handlers.parse_document import make_handler
from app.worker.loop import Worker
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container, make_source

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

_BOMB_BYTES = 20 * 1024 * 1024  # ~20 MB powtarzalnego znaku (pozycja #24)
_POLL_S = 0.05
_WAIT_TIMEOUT_S = 60.0


def _bomb_xlsx_bytes() -> bytes:
    """XLSX-bomba jako bajty: [Content_Types].xml + workbook.xml + arkusz ~20 MB."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr("xl/workbook.xml", b"<workbook/>")
        zf.writestr("xl/worksheets/sheet1.xml", b"A" * _BOMB_BYTES)
    return buffer.getvalue()


def _slow_convert(path: Path, fmt: str, opts: ConvertOptions) -> ConvertedDocument:
    """Konwerter wolny: śpi 3 s, dłużej niż parse_timeout_s=1 w teście."""
    time.sleep(3.0)
    return ConvertedDocument("<p>slow</p>", None, [], {}, [], {"chars": 0})


@contextlib.asynccontextmanager
async def _worker(settings: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener + prawdziwy Worker (handler parse_document, executor=None)."""
    tuned = settings.model_copy(update={"worker_poll_s": _POLL_S})
    container = await make_container(tuned, tmp_path)
    worker = Worker(container, {"parse_document": make_handler(None)})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    try:
        yield container
    finally:
        stop.set()
        await asyncio.wait_for(run_task, timeout=15)
        await container.aclose()


async def _wait_final(sm: async_sessionmaker[AsyncSession], document_id: str) -> None:
    """Czeka, aż dokument ma run ∈ {'2','3','4'} i żadne jego zadanie nie jest w toku."""
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        async with sm() as session:
            run = (
                await session.execute(
                    text("SELECT run FROM documents WHERE id = :i"), {"i": document_id}
                )
            ).scalar_one()
            counts = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total,"
                        " COALESCE(SUM(status NOT IN ('done', 'failed', 'cancelled', 'dead')), 0)"
                        " AS pending FROM tasks WHERE document_id = :i"
                    ),
                    {"i": document_id},
                )
            ).one()
        if str(run) in ("2", "3", "4") and int(counts.total) >= 1 and int(counts.pending) == 0:
            return
        await asyncio.sleep(0.2)
    raise AssertionError(
        f"dokument {document_id} nie osiągnął stanu końcowego w {_WAIT_TIMEOUT_S} s"
    )


async def _document(sm: async_sessionmaker[AsyncSession], document_id: str) -> DocumentRow | None:
    """Świeży wiersz dokumentu."""
    async with transaction(sm) as session:
        return await documents_repo.get(session, document_id)


async def test_zip_bomb_document_fails(
    migrated_db: Settings, tmp_path: Path, sm: async_sessionmaker[AsyncSession]
) -> None:
    """XLSX-bomba przy max_archive_ratio=10 → dokument FAIL, błąd „Limit exceeded …”."""
    settings = migrated_db.model_copy(update={"max_archive_ratio": 10})
    async with _worker(settings, tmp_path) as container:
        ds = await seed_dataset(sm)
        doc = await container.ingest.upload(
            ds.id,
            make_source(_bomb_xlsx_bytes(), "bomba.xlsx"),
            created_by=ds.tenant_id,
            parse=True,
        )

        await _wait_final(sm, doc.id)

        row = await _document(sm, doc.id)
        assert row is not None and row.run == "4"
        assert "Limit exceeded" in (row.error or "")
        assert "archive ratio" in (row.error or "")


async def test_parse_timeout_document_fails(
    migrated_db: Settings,
    tmp_path: Path,
    sm: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parse_timeout_s=1 + wolny konwerter → dokument FAIL, błąd „Parsing timed out after 1 s”."""
    monkeypatch.setattr("app.services.ingest_convert.convert", _slow_convert)
    settings = migrated_db.model_copy(update={"parse_timeout_s": 1})
    async with _worker(settings, tmp_path) as container:
        ds = await seed_dataset(sm)
        doc = await container.ingest.upload(
            ds.id,
            make_source(b"Ala ma kota.\n" * 10, "notatka.txt"),
            created_by=ds.tenant_id,
            parse=True,
        )

        await _wait_final(sm, doc.id)

        row = await _document(sm, doc.id)
        assert row is not None and row.run == "4"
        assert "Parsing timed out after 1 s" in (row.error or "")
