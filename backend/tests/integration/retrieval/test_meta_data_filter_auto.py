"""Testy ``meta_data_filter`` auto/semi_auto w DbRetrievalService (brief T3b E6-1a, K11 §10f p. 5).

Scenariusz SC-E6-1a-05: pytanie zawiera rok obecny w metadanych → fake-llm generuje warunek
``rok = 2023`` i retrieval zawęża się do dopasowanego dokumentu; pytanie bez wartości metadanych
→ puste warunki → brak zawężenia. Tryb termowy (w=0), żeby nie wołać strony wektorowej.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories.datasets import DatasetRow
from app.domain.retrieval.types import RetrievalResult
from app.services.retrieval import RetrievalQuery
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import insert_chunk, insert_document, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

_CHUNK_TEXT = "Raport roczny o smokach wawelskich"
# Oba dokumenty mają po jednym chunku → brak zawężenia zwraca dwa trafienia.
_ALL_CHUNKS = 2


def _q(ds_id: str, question: str, **overrides: object) -> RetrievalQuery:
    """RetrievalQuery w trybie termowym z podanym pytaniem (bez strony wektorowej)."""
    params: dict = {
        "question": question,
        "dataset_ids": (ds_id,),
        "vector_similarity_weight": 0.0,
    }
    params.update(overrides)
    return RetrievalQuery(**params)


async def _retrieve(container: Container, ds: DatasetRow, question: str, **overrides: object):
    return await container.retrieval.retrieve(
        principal_for(ds.tenant_id), _q(ds.id, question, **overrides)
    )


async def _seed_two_docs(sm: async_sessionmaker[AsyncSession], container: Container) -> DatasetRow:
    """Dataset + dwa dokumenty z ``rok`` 2023/2024, każdy z jednym chunkiem „Raport…"."""
    ds = await seed_dataset(sm)
    old = await insert_document(sm, ds, name="old.txt", meta={"rok": "2023"})
    new = await insert_document(sm, ds, name="new.txt", meta={"rok": "2024"})
    await insert_chunk(sm, ds.id, old, ordinal=0, text=_CHUNK_TEXT)
    await insert_chunk(sm, ds.id, new, ordinal=0, text=_CHUNK_TEXT)
    return ds


async def test_auto_narrows_to_matching_year(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """SC-05: pytanie „raporty z 2023" → auto zawęża do dokumentu z ``rok: 2023``."""
    ds = await _seed_two_docs(sm, container)
    result = await _retrieve(container, ds, "raport z 2023", meta_data_filter={"method": "auto"})
    assert isinstance(result, RetrievalResult)
    assert result.total == 1


async def test_auto_without_metadata_hit_no_narrowing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Pytanie bez wartości metadanych → puste warunki → brak zawężenia (oba chunki)."""
    ds = await _seed_two_docs(sm, container)
    result = await _retrieve(container, ds, "raport roczny", meta_data_filter={"method": "auto"})
    assert result.total == _ALL_CHUNKS


async def test_semi_auto_uses_selected_key(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``semi_auto: [rok]`` generuje warunek z klucza ``rok`` (zawężenie do jednego dokumentu)."""
    ds = await _seed_two_docs(sm, container)
    result = await _retrieve(
        container,
        ds,
        "raport z 2024",
        meta_data_filter={"method": "semi_auto", "semi_auto": ["rok"]},
    )
    assert result.total == 1
