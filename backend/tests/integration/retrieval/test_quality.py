"""Test jakości retrievalu na mini-korpusie PL w trybie termowym (brief T6; R0 p. 1, M6)."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories.datasets import DatasetRow
from app.services.retrieval import RetrievalQuery
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

FIXTURES = Path(__file__).parents[2] / "fixtures" / "retrieval"

# Korpus: cztery dokumenty po polsku, każdy o odrębnym temacie (brief T6 p. 1).
CORPUS: tuple[str, ...] = (
    "regulamin-urlopow.txt",
    "umowa-najmu.txt",
    "bhp-magazyn.txt",
    "faktury-ksiegowosc.txt",
)

# Pytania sformułowane innymi formami fleksyjnymi niż w korpusie; (pytanie, oczekiwany dokument).
QUESTIONS: tuple[tuple[str, str], ...] = (
    ("Ile dni urlopu wypoczynkowego mają pracownicy?", "regulamin-urlopow.txt"),
    ("Co należy zrobić z zaległym urlopem z poprzedniego roku?", "regulamin-urlopow.txt"),
    ("Jaką kaucję trzeba wnieść przy wynajmie lokalu?", "umowa-najmu.txt"),
    ("Jak wypowiedzieć umowę najmu lokalu?", "umowa-najmu.txt"),
    ("Jak często trzeba odnowić szkolenie BHP na magazynie?", "bhp-magazyn.txt"),
    ("Jak dobrać rozmiar kasku ochronnego i gdzie trzymać gaśnice?", "bhp-magazyn.txt"),
    ("Ile dni ma nabywca na zapłatę faktury?", "faktury-ksiegowosc.txt"),
    ("Kiedy księgowa wprowadza korektę faktury po pomyłce?", "faktury-ksiegowosc.txt"),
)

# Pytanie bez pokrycia w korpusie (brief T6 p. 4).
NO_COVERAGE = "Kwantowa chromodynamika gluonów w akceleratorze"


async def ingest_corpus(container: Container, sm: async_sessionmaker[AsyncSession]) -> DatasetRow:
    """Jeden dataset z zingestowanym całym korpusem (brief T6 p. 3)."""
    ds = await seed_dataset(sm)
    for name in CORPUS:
        text = (FIXTURES / name).read_text(encoding="utf-8")
        await ingest_text(container, ds, name, text)
    return ds


async def test_quality_term_mode(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wymaganie 3: co najmniej 7 z 8 pytań trafia oczekiwany dokument w top-3."""
    ds = await ingest_corpus(container, sm)
    owner = principal_for(ds.tenant_id)
    missed: list[tuple[str, str, set[str]]] = []
    for question, expected in QUESTIONS:
        result = await container.retrieval.retrieve(
            owner,
            RetrievalQuery(
                question=question,
                dataset_ids=(ds.id,),
                vector_similarity_weight=0.0,
                page_size=3,
            ),
        )
        names = {chunk.document_name for chunk in result.chunks}
        if expected not in names:
            missed.append((question, expected, sorted(names)))
    hits = len(QUESTIONS) - len(missed)
    assert hits >= len(QUESTIONS) - 1, f"trafienia {hits}/{len(QUESTIONS)}; chybienia: {missed}"


async def test_no_coverage_returns_empty(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wymaganie 4: pytanie spoza korpusu w trybie termowym → pusty wynik."""
    ds = await ingest_corpus(container, sm)
    result = await container.retrieval.retrieve(
        principal_for(ds.tenant_id),
        RetrievalQuery(
            question=NO_COVERAGE,
            dataset_ids=(ds.id,),
            vector_similarity_weight=0.0,
            page_size=3,
        ),
    )
    assert result.total == 0
    assert result.chunks == []
    assert result.doc_aggs == []
