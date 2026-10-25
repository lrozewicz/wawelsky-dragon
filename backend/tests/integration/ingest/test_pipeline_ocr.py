"""Ingestia PDF z tabelą dwupoziomową — profil OCR OTSL (WP E5-H4a T4).

Dataset z `layout_recognize="fake-ocr"` (profil OTSL, T3) ingestuje testowy PDF i daje chunk
tabeli z `colspan` oraz linearyzacją nagłówka wielopoziomowego (DEC-246). Inny model wizji
(`fake-vision`, profil HTML) zachowuje się jak dotąd. Wymaga fake-llm przez `WD_LLM_BASE_URL`.
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
from app.db.repositories import models as models_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.services.ingest_pipeline import run_parse
from app.worker.errors import PermanentError
from tests.integration.ingest.conftest import DEFAULT_PARSER_CONFIG, TIME_MS, seed_dataset
from tests.integration.ingest.pipeline_helpers import claim_context, make_container, make_source

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

_PDF = Path(__file__).resolve().parents[2] / "fixtures" / "ocr" / "two_level_table.pdf"


@pytest.fixture(autouse=True)
def _serialize_fakellm(serialize_fakellm: None) -> None:
    """Blokada fake-llm (stan globalny) wspólna z ``test_concurrency.py`` — patrz conftest.

    Bez niej równoległe (xdist) żądania wizji ``fake-ocr`` z tego pliku podnosiły
    obserwowane ``max_concurrent`` w ``test_concurrency.py`` (flak ``== 8``).
    """


async def _register_image_models(container: Container) -> None:
    """Rejestruje modele image2text: `fake-ocr` (OTSL) i `fake-vision` (HTML)."""
    async with transaction(container.sessionmaker) as session:
        await models_repo.insert(
            session,
            id="f" * 32,
            name="fake-ocr",
            model_type="image2text",
            is_default=False,
            now_ms=TIME_MS,
        )
        await models_repo.insert(
            session,
            id="d" * 32,
            name="fake-vision",
            model_type="image2text",
            is_default=False,
            now_ms=TIME_MS,
        )


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path, modele fake + image2text."""
    instance = await make_container(migrated_db, tmp_path)
    await _register_image_models(instance)
    yield instance
    await instance.aclose()


async def _parse(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    layout_recognize: str,
    *,
    extra_parser_config: dict | None = None,
) -> DocumentRow:
    """Dataset z parserem wizji + upload fixture PDF + run_parse; zwraca dokument.

    ``extra_parser_config`` scala się do ``parser_config`` ponad ``layout_recognize``
    (np. wyłączenie korekty diakrytyków).
    """
    parser_config = {
        **DEFAULT_PARSER_CONFIG,
        "layout_recognize": layout_recognize,
        **(extra_parser_config or {}),
    }
    ds = await seed_dataset(sm, parser_config=parser_config)
    doc = await container.ingest.upload(
        ds.id, make_source(_PDF.read_bytes(), _PDF.name), created_by=ds.tenant_id
    )
    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)
    return doc


async def _chunks(
    sm: async_sessionmaker[AsyncSession], document_id: str
) -> list[dict[str, object]]:
    """Chunki committed=1 (typ, tekst, HTML) w kolejności ordinal."""
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT chunk_type, content, content_llm FROM chunks"
                        " WHERE document_id = :d AND committed = 1 ORDER BY ordinal"
                    ),
                    {"d": document_id},
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


async def test_fake_ocr_two_level_table_chunk(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`fake-ocr` → tabela colspan="2", linearyzacja „2022 / …" (DEC-246) i korekta
    diakrytyków słownikiem wordfreq („ogolem" → „ogółem", DEC-249)."""
    doc = await _parse(container, sm, "fake-ocr")
    rows = await _chunks(sm, doc.id)
    tables = [row for row in rows if row["chunk_type"] == "table"]
    assert tables, "brak chunka typu tabela"
    html = "".join(str(row["content_llm"] or "") for row in tables)
    body = "\n".join(str(row["content"]) for row in rows)
    assert 'colspan="2"' in html
    assert "2022 / ogółem: 10,8" in body
    assert "2022 / kobiety: 11,3" in body
    assert "ogolem" not in body.lower()
    assert "PROMPT-MISMATCH" not in body


async def test_fake_ocr_diacritics_disabled_keeps_raw_text(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wyłączone etapy korekty (`layer`/`wordfreq` False) → surowe „ogolem" z modelu wizji."""
    doc = await _parse(
        container,
        sm,
        "fake-ocr",
        extra_parser_config={"diacritics": {"layer": False, "wordfreq": False}},
    )
    rows = await _chunks(sm, doc.id)
    tables = [row for row in rows if row["chunk_type"] == "table"]
    assert tables, "brak chunka typu tabela"
    html = "".join(str(row["content_llm"] or "") for row in tables)
    body = "\n".join(str(row["content"]) for row in rows)
    assert "2022 / ogolem: 10,8" in body
    assert 'colspan="2"' in html


async def test_fake_ocr_invalid_diacritics_config_fails(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Niepoprawny typ flagi (`layer: "false"`) → `PermanentError` z nazwą klucza."""
    with pytest.raises(PermanentError, match=re.escape("invalid parser_config.diacritics: layer")):
        await _parse(
            container, sm, "fake-ocr", extra_parser_config={"diacritics": {"layer": "false"}}
        )


async def test_other_vision_model_unchanged(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`fake-vision` (profil HTML) → brak tabeli colspan, parsowanie bez wyjątku."""
    doc = await _parse(container, sm, "fake-vision")
    rows = await _chunks(sm, doc.id)
    assert rows, "brak chunków"
    html = "".join(str(row["content_llm"] or "") for row in rows)
    assert 'colspan="2"' not in html
    assert all(row["chunk_type"] != "table" for row in rows)
