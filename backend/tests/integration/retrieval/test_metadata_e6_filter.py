"""`meta_data_filter` (method=manual) w /retrieval (K11 §10f p. 5; brief T3a).

Złoto `retrieval/metadata_e6--41/42/45`: `manual` zawęża zbiór dokumentów, brak trafień →
0 chunków (nie „brak filtra"), a obecność klucza `metadata_condition` zeruje filtr.
Dane jak złoto §1a: dokument `a` = author A / year "2020", `b` = author B / year "2021".
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.ragflow.normalize.retrieval import retrieval_query
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

_PROFILE = "ragflow_0_27"
_QUESTION = "smokwawelski"
_CHUNK_TEXT = "Smokwawelski mieszkał w jamie pod Wawelem."
# Tryb termowy: bez wektorów (chunki dim 4) i bez progu trafności — jak testy filtrów T5.
_TERM = {"vector_similarity_weight": 0, "similarity_threshold": 0}


def _manual(entries: list[dict], *, logic: str = "and") -> dict:
    """`meta_data_filter` manual w kształcie ciała API złota `metadata_e6--41/42`."""
    return {"method": "manual", "logic": logic, "manual": entries}


async def _seed_two_docs(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> tuple[DatasetRow, str, str]:
    """Datasety złota §1a: a = {author A, year "2020"}, b = {author B, year "2021"}."""
    ds = await seed_dataset(sm)
    doc_a = await insert_document(sm, ds, name="a.txt", meta={"author": "A", "year": "2020"})
    doc_b = await insert_document(sm, ds, name="b.txt", meta={"author": "B", "year": "2021"})
    await insert_chunk(sm, ds.id, doc_a, ordinal=0, text=_CHUNK_TEXT)
    await insert_chunk(sm, ds.id, doc_b, ordinal=0, text=_CHUNK_TEXT)
    return ds, doc_a, doc_b


async def _retrieve(
    container: Container, ds: DatasetRow, body: dict, *, path_dataset_id: str | None = None
) -> tuple[RetrievalQuery, RetrievalResult]:
    """Normalizuje ciało jak trasa /retrieval, potem retrievuje jako właściciel datasetu."""
    query = retrieval_query(body, _PROFILE, max_size=100, path_dataset_id=path_dataset_id)
    result = await container.retrieval.retrieve(principal_for(ds.tenant_id), query)
    return query, result


async def test_manual_filter_narrows_to_one_doc(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Złoto --41: manual author=A AND year="2020" → chunki tylko dokumentu a."""
    ds, doc_a, doc_b = await _seed_two_docs(container, sm)
    _, result = await _retrieve(
        container,
        ds,
        {
            "question": _QUESTION,
            "dataset_ids": [ds.id],
            **_TERM,
            "meta_data_filter": _manual(
                [
                    {"key": "author", "op": "=", "value": "A"},
                    {"key": "year", "op": "=", "value": "2020"},
                ]
            ),
        },
    )
    assert result.total == 1
    assert [chunk.document_id for chunk in result.chunks] == [doc_a]
    assert doc_b not in [chunk.document_id for chunk in result.chunks]


async def test_manual_filter_no_match_is_empty_not_leak(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Złoto --42: manual author=Z bez trafień → 0 chunków (NIE brak filtra)."""
    ds, _, _ = await _seed_two_docs(container, sm)
    _, result = await _retrieve(
        container,
        ds,
        {
            "question": _QUESTION,
            "dataset_ids": [ds.id],
            **_TERM,
            "meta_data_filter": _manual([{"key": "author", "op": "=", "value": "Z"}]),
        },
    )
    assert result.total == 0
    assert result.chunks == []


async def test_metadata_condition_presence_overrides_filter(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Złoto --45: metadata_condition author=A + meta_data_filter author=B → wygrywa warunek (a)."""
    ds, doc_a, _ = await _seed_two_docs(container, sm)
    _, result = await _retrieve(
        container,
        ds,
        {
            "question": _QUESTION,
            "dataset_ids": [ds.id],
            **_TERM,
            "metadata_condition": {
                "conditions": [{"name": "author", "comparison_operator": "=", "value": "A"}]
            },
            "meta_data_filter": _manual([{"key": "author", "op": "=", "value": "B"}]),
        },
    )
    assert [chunk.document_id for chunk in result.chunks] == [doc_a]


async def test_auto_and_semi_auto_no_narrowing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Złoto --43/44: auto/semi_auto bez zawężenia → oba dokumenty."""
    ds, doc_a, doc_b = await _seed_two_docs(container, sm)
    for method in ("auto", "semi_auto"):
        _, result = await _retrieve(
            container,
            ds,
            {
                "question": _QUESTION,
                "dataset_ids": [ds.id],
                **_TERM,
                "meta_data_filter": {"method": method},
            },
        )
        assert {chunk.document_id for chunk in result.chunks} == {doc_a, doc_b}
