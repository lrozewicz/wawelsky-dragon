"""Testy integracyjne auto-metadanych w ``run_parse`` (brief T4; SC-E6-1a-01/02/07).

Marker db + fakellm (fake-llm z verify.sh); dokument dziedziczy ``parser_config`` datasetu.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.uow import transaction
from app.services.ingest_pipeline import run_parse
from app.services.ingest_progress import ProgressReporter
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import claim_context, make_container, make_source

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

FIELDS = [
    {"key": "rok", "type": "string", "description": "Rok, którego dotyczą dane"},
    {"key": "typ", "type": "string", "enum": ["raport", "rocznik", "ustawa"]},
]

PARSER_CONFIG = {
    "chunk_token_num": 128,
    "delimiter": "\n",
    "layout_recognize": "DeepDOC",
    "auto_keywords": 0,
    "auto_questions": 0,
    "html4excel": False,
    "pages": [[1, 1000000]],
    "enable_metadata": True,
    "metadata": FIELDS,
}

FIXTURE = (
    "rok: 2023\n"
    "typ: raport\n"
    "Autor: Jan Kowalski\n"
    "Niniejszy raport opisuje stan środowiska w roku 2023."
    " Kolejne zdania wypełniają treść dokumentu testowego.\n"
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


async def _parse(container: Container, document_id: str) -> None:
    """Prowadzi dokument przez run_parse (jak worker)."""
    ctx = await claim_context(container, document_id)
    await run_parse(container, ctx.task, ctx, executor=None)


async def test_auto_metadata_extracts_fields(
    container: Container, sm: async_sessionmaker[AsyncSession], serialize_fakellm: None
) -> None:
    """SC-E6-1a-01: fixture z liniami rok/typ → meta_fields i log `Auto metadata: 2 fields`."""
    ds = await seed_dataset(sm, parser_config=PARSER_CONFIG)
    doc = await container.ingest.upload(
        ds.id, make_source(FIXTURE, "fixture.txt"), created_by=ds.tenant_id
    )
    await _parse(container, doc.id)

    row = await _document(sm, doc.id)
    assert row.run == "3"
    assert row.meta_fields == {"rok": "2023", "typ": "raport"}
    assert "Auto metadata: 2 fields" in row.progress_msg


async def test_progress_never_regresses_with_auto_questions(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    serialize_fakellm: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U6: raportowany postęp nie maleje przy `auto_questions>0` (MINOR T4, krok 8b).

    `_prepare_chunks` sięga 0.60 (generacja pytań), więc krok 8b nie może raportować 0.55.
    """
    seen: list[float] = []
    original = ProgressReporter.report

    async def spy(
        self: ProgressReporter, progress: float, msg: str | None = None, *, force: bool = False
    ) -> None:
        seen.append(progress)
        await original(self, progress, msg, force=force)

    monkeypatch.setattr(ProgressReporter, "report", spy)

    config = {**PARSER_CONFIG, "auto_questions": 1}
    ds = await seed_dataset(sm, parser_config=config)
    doc = await container.ingest.upload(
        ds.id, make_source(FIXTURE, "fixture.txt"), created_by=ds.tenant_id
    )
    await _parse(container, doc.id)

    assert 0.60 in seen  # noqa: PLR2004 — postęp generacji pytań (kontrakt C7)
    assert seen == sorted(seen)


async def test_auto_metadata_no_match_keeps_meta(
    container: Container, sm: async_sessionmaker[AsyncSession], serialize_fakellm: None
) -> None:
    """SC-E6-1a-01: treść bez dopasowań → meta bez zmian, `Auto metadata: 0 fields`, Sukces."""
    ds = await seed_dataset(sm, parser_config=PARSER_CONFIG)
    content = ("Umowa najmu lokalu mieszkalnego. Lokator płaci czynsz piątego dnia.\n" * 3).encode()
    doc = await container.ingest.upload(
        ds.id, make_source(content, "umowa.txt"), created_by=ds.tenant_id
    )
    await _parse(container, doc.id)

    row = await _document(sm, doc.id)
    assert row.run == "3"
    assert row.meta_fields == {}
    assert "Auto metadata: 0 fields" in row.progress_msg


async def test_auto_metadata_invalid_response_keeps_meta(
    container: Container, sm: async_sessionmaker[AsyncSession], serialize_fakellm: None
) -> None:
    """SC-E6-1a-02: model zwraca nie-JSON → meta bez zmian, parsowanie Sukces, bez stack trace."""
    ds = await seed_dataset(sm, parser_config=PARSER_CONFIG)
    content = (
        "FAKE_METADATA_INVALID\nrok: 2023\ntyp: raport\n"
        "Treść dokumentu testowego wypełniająca chunk.\n"
    ).encode()
    doc = await container.ingest.upload(
        ds.id, make_source(content, "invalid.txt"), created_by=ds.tenant_id
    )
    await _parse(container, doc.id)

    row = await _document(sm, doc.id)
    assert row.run == "3"
    assert row.meta_fields == {}
    assert "Traceback" not in row.progress_msg
    assert "Auto metadata: 0 fields" in row.progress_msg


async def test_auto_metadata_preserves_existing_fields(
    container: Container, sm: async_sessionmaker[AsyncSession], serialize_fakellm: None
) -> None:
    """SC-E6-1a-07: istniejące ``meta_fields`` nie znikają przy dopisaniu nowych pól."""
    ds = await seed_dataset(sm, parser_config=PARSER_CONFIG)
    doc = await container.ingest.upload(
        ds.id, make_source(FIXTURE, "fixture.txt"), created_by=ds.tenant_id
    )
    async with transaction(sm) as session:
        await documents_repo.set_meta_fields(session, doc.id, meta_fields={"wd_source": "seed"})
    await _parse(container, doc.id)

    row = await _document(sm, doc.id)
    assert row.meta_fields == {"wd_source": "seed", "rok": "2023", "typ": "raport"}


async def test_auto_metadata_disabled_makes_no_call(
    container: Container, sm: async_sessionmaker[AsyncSession], serialize_fakellm: None
) -> None:
    """SC-E6-1a: ``enable_metadata`` fałszywe → brak wywołania modelu i brak wpisu w logu.

    ``llm_id`` wskazuje model nieistniejący: gdyby krok rozwiązywał/wywoływał model,
    ``run_parse`` padłby (``PermanentError``), więc ``run == "3"`` dowodzi pominięcia kroku.
    """
    config = {**PARSER_CONFIG, "enable_metadata": False, "llm_id": "no-such-chat-model"}
    ds = await seed_dataset(sm, parser_config=config)
    doc = await container.ingest.upload(
        ds.id, make_source(FIXTURE, "fixture.txt"), created_by=ds.tenant_id
    )
    await _parse(container, doc.id)

    row = await _document(sm, doc.id)
    assert row.run == "3"
    assert row.meta_fields == {}
    assert "Auto metadata" not in row.progress_msg
