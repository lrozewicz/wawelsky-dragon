"""Filtry i stronicowanie DbRetrievalService w trybie termowym w=0 (brief T5, 13-19).

Dane przez pomocniki T3 (``insert_document``/``insert_chunk``) — bez strony wektorowej:
fake-llm zwraca wektory 1024, a ``insert_chunk`` pisze wymiar 4 (w=0 → brak zapytań
wektorowych). Słowo „umowa” w każdym chunku.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories.datasets import DatasetRow
from app.domain.retrieval.metadata import parse_metadata_condition
from app.domain.retrieval.types import RetrievalResult
from app.services.retrieval import RetrievalQuery
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import insert_chunk, insert_document, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

_CHUNK_TEXT = "Umowa najmu lokalu w Krakowie"


def _q(ds_id: str, **overrides: object) -> RetrievalQuery:
    """RetrievalQuery w trybie termowym (vector_similarity_weight=0), pytanie „umowa”."""
    params: dict = {
        "question": "umowa",
        "dataset_ids": (ds_id,),
        "vector_similarity_weight": 0.0,
    }
    params.update(overrides)
    return RetrievalQuery(**params)


async def _retrieve(container: Container, ds: DatasetRow, **overrides: object) -> RetrievalResult:
    """retrieve w trybie termowym dla właściciela datasetu."""
    query = _q(ds.id, **overrides)
    return await container.retrieval.retrieve(principal_for(ds.tenant_id), query)


async def _seed(container: Container, sm: async_sessionmaker[AsyncSession]) -> DatasetRow:
    """Dataset dla trybu termowego."""
    return await seed_dataset(sm)


async def test_committed_filter(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """Test 13: chunk committed=False nie wraca, bliźniak committed=True wraca (po id)."""
    ds = await _seed(container, sm)
    doc = await insert_document(sm, ds, name="a.txt")
    kept = await insert_chunk(sm, ds.id, doc, ordinal=0, text=_CHUNK_TEXT)
    hidden = await insert_chunk(sm, ds.id, doc, ordinal=1, text=_CHUNK_TEXT, committed=False)
    result = await _retrieve(container, ds)
    ids = [chunk.chunk_id for chunk in result.chunks]
    assert kept in ids
    assert hidden not in ids


async def test_available_filter(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """Test 14: chunk available=False nie wraca, bliźniak available=True wraca."""
    ds = await _seed(container, sm)
    doc = await insert_document(sm, ds, name="a.txt")
    kept = await insert_chunk(sm, ds.id, doc, ordinal=0, text=_CHUNK_TEXT)
    hidden = await insert_chunk(sm, ds.id, doc, ordinal=1, text=_CHUNK_TEXT, available=False)
    result = await _retrieve(container, ds)
    ids = [chunk.chunk_id for chunk in result.chunks]
    assert kept in ids
    assert hidden not in ids


async def test_document_enabled_filter(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Test 15: dokument enabled=False — jego chunki nie wracają."""
    ds = await _seed(container, sm)
    doc_on = await insert_document(sm, ds, name="on.txt")
    doc_off = await insert_document(sm, ds, name="off.txt", enabled=False)
    kept = await insert_chunk(sm, ds.id, doc_on, ordinal=0, text=_CHUNK_TEXT)
    hidden = await insert_chunk(sm, ds.id, doc_off, ordinal=0, text=_CHUNK_TEXT)
    result = await _retrieve(container, ds)
    ids = [chunk.chunk_id for chunk in result.chunks]
    assert kept in ids
    assert hidden not in ids


async def test_document_ids_filter(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Test 16: document_ids zawęża do podanych dokumentów; () → total == 0."""
    ds = await _seed(container, sm)
    doc_a = await insert_document(sm, ds, name="a.txt")
    doc_b = await insert_document(sm, ds, name="b.txt")
    chunk_a = await insert_chunk(sm, ds.id, doc_a, ordinal=0, text=_CHUNK_TEXT)
    await insert_chunk(sm, ds.id, doc_b, ordinal=0, text=_CHUNK_TEXT)
    result = await _retrieve(container, ds, document_ids=(doc_a,))
    assert [chunk.chunk_id for chunk in result.chunks] == [chunk_a]
    empty = await _retrieve(container, ds, document_ids=())
    assert empty.total == 0
    assert empty.chunks == []


async def test_metadata_condition_filter(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Test 17: warunek metadanych author=jan → tylko dokument Jana; bez dopasowań → 0."""
    ds = await _seed(container, sm)
    jan = await insert_document(sm, ds, name="jan.txt", meta={"author": "Jan"})
    anna = await insert_document(sm, ds, name="anna.txt", meta={"author": "Anna"})
    chunk_jan = await insert_chunk(sm, ds.id, jan, ordinal=0, text=_CHUNK_TEXT)
    await insert_chunk(sm, ds.id, anna, ordinal=0, text=_CHUNK_TEXT)
    condition = parse_metadata_condition(
        {"conditions": [{"name": "author", "comparison_operator": "is", "value": "jan"}]}
    )
    result = await _retrieve(container, ds, metadata_condition=condition)
    assert [chunk.chunk_id for chunk in result.chunks] == [chunk_jan]
    assert result.chunks[0].document_metadata == {"author": "Jan"}
    no_match = parse_metadata_condition(
        {"conditions": [{"name": "author", "comparison_operator": "is", "value": "kim"}]}
    )
    empty = await _retrieve(container, ds, metadata_condition=no_match)
    assert empty.total == 0
    assert empty.chunks == []
    combined = await _retrieve(container, ds, metadata_condition=condition, document_ids=(jan,))
    assert [chunk.chunk_id for chunk in combined.chunks] == [chunk_jan]


async def test_document_metadata_null_without_metadata(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dokument bez metadanych (meta_fields={}) → document_metadata None (złoto upstream)."""
    ds = await _seed(container, sm)
    doc = await insert_document(sm, ds, name="bez-meta.txt")
    await insert_chunk(sm, ds.id, doc, ordinal=0, text=_CHUNK_TEXT)
    result = await _retrieve(container, ds)
    assert result.chunks[0].document_metadata is None


async def test_pagination(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """Test 18: 7 chunków, page_size=3 → strony 3/3/1, total==7, rozłączne zbiory."""
    ds = await _seed(container, sm)
    doc = await insert_document(sm, ds, name="pag.txt")
    inserted = [
        await insert_chunk(
            sm, ds.id, doc, ordinal=ordinal, text=f"Umowa najmu mieszkania numer {ordinal}"
        )
        for ordinal in range(7)
    ]
    pages: list[list[str]] = []
    for page in (1, 2, 3, 4):
        result = await _retrieve(container, ds, page_size=3, page=page)
        assert result.total == len(inserted)
        pages.append([chunk.chunk_id for chunk in result.chunks])
    assert [len(chunk_ids) for chunk_ids in pages[:3]] == [3, 3, 1]
    assert pages[3] == []
    union = [chunk_id for chunk_ids in pages[:3] for chunk_id in chunk_ids]
    assert len(union) == len(set(union))
    assert set(union) == set(inserted)
    single = await _retrieve(container, ds, page_size=1, page=7)
    assert single.total == len(inserted)
    assert len(single.chunks) == 1


async def test_stem_flexion_hits_via_content_stem(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Test 19: „Tatrach” → total == 1 wyłącznie przez content_stem (fleksja)."""
    ds = await _seed(container, sm)
    doc = await insert_document(sm, ds, name="tatry.txt")
    await insert_chunk(sm, ds.id, doc, ordinal=0, text="Wysokie Tatry zimą są piękne.")
    query = RetrievalQuery(
        question="Tatrach",
        dataset_ids=(ds.id,),
        vector_similarity_weight=0.0,
    )
    result = await container.retrieval.retrieve(principal_for(ds.tenant_id), query)
    assert result.total == 1
    assert result.chunks[0].term_similarity > 0
