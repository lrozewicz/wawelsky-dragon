"""Testy deterministycznego klucza wtórnego remisów w retrievalu (brief D3, kontrakt C3).

Klucz wtórny: ``(documents.name ASC, ordinal chunku ASC, chunks.id ASC)`` — w SQL i w
sortowaniu domenowym ``rank_key``. Wszystkie chunki mają ten sam tekst i wektor (remis
score), a nazwy dokumentów nadawane są ODWROTNIE do porządku losowych ``chunks.id`` —
dzięki temu test rozstrzyga o kluczu wtórnym, a nie o przypadkowej kolejności id.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import retrieval as retrieval_repo
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from app.services.retrieval import RetrievalQuery
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import insert_chunk, insert_document, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

# Identyczna treść i identyczne wektory → identyczny score wszystkich chunków.
_TIE_TEXT = "Umowa najmu lokalu w Krakowie"
_QUESTION = "umowa najmu lokalu"
# Oczekiwana kolejność wyniku: a.txt#0, a.txt#1, b.txt#0, c.txt#0.
_EXPECTED_NAMES = ["a.txt", "a.txt", "b.txt", "c.txt"]
_EXPECTED_ORDINALS = [0, 1, 0, 0]


async def _seed_ties(
    sm: async_sessionmaker[AsyncSession], *, dim: int
) -> tuple[DatasetRow, list[str]]:
    """Trzy dokumenty z identycznymi chunkami; nazwy odwrotnie do porządku ``chunks.id``.

    Dokument z największym id pierwszego chunku dostaje ``a.txt``, a z najmniejszym
    ``c.txt``, więc stary klucz wtórny (samo ``chunks.id``) dawałby kolejność odwrotną do
    oczekiwanej. Dokument ``a.txt`` ma dwa chunki (ordinal 0 i 1). Zwraca ``(dataset, id
    chunków w oczekiwanej kolejności wyniku)``.
    """
    ds = await seed_dataset(sm, embedding_dim=dim)
    vector = [1.0] + [0.0] * (dim - 1)
    docs = [await insert_document(sm, ds, name=f"p{index}.txt") for index in range(3)]
    first: dict[str, str] = {}
    for doc in docs:
        first[doc] = await insert_chunk(
            sm, ds.id, doc, ordinal=0, text=_TIE_TEXT, vector=vector, dim=dim
        )
    by_id = sorted(docs, key=lambda doc: first[doc])
    named = dict(zip(reversed(["a.txt", "b.txt", "c.txt"]), by_id, strict=True))
    async with transaction(sm) as session:
        for name, doc_id in named.items():
            await session.execute(
                text("UPDATE documents SET name = :n, suffix = :s WHERE id = :id"),
                {"n": name, "s": name.rsplit(".", 1)[-1], "id": doc_id},
            )
    second = await insert_chunk(
        sm, ds.id, named["a.txt"], ordinal=1, text=_TIE_TEXT, vector=vector, dim=dim
    )
    ids = [
        first[named["a.txt"]],
        second,
        first[named["b.txt"]],
        first[named["c.txt"]],
    ]
    return ds, ids


async def test_vector_candidates_tie_order_doc_name_then_ordinal(sm) -> None:
    """Remis dystansu → documents.name ASC, ordinal ASC, chunks.id ASC (C3)."""
    ds, expected = await _seed_ties(sm, dim=4)
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.vector_candidates(session, 4, [1.0, 0.0, 0.0, 0.0], scope, 10)
    assert [chunk_id for chunk_id, _ in got] == expected


async def test_fulltext_candidates_tie_order_doc_name_then_ordinal(sm) -> None:
    """Remis rankingu FULLTEXT → documents.name ASC, ordinal ASC, chunks.id ASC (C3)."""
    ds, expected = await _seed_ties(sm, dim=4)
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.fulltext_candidates(session, "umowa", "", scope, 10)
    assert got == expected


async def test_load_chunks_carries_ordinal(sm) -> None:
    """ChunkRow niesie ordinal chunku — klucz wtórny domeny (C3)."""
    _ds, expected = await _seed_ties(sm, dim=4)
    async with transaction(sm) as session:
        rows = await retrieval_repo.load_chunks(session, list(reversed(expected)))
    assert [row.id for row in rows] == list(reversed(expected))
    by_id = {row.id: row for row in rows}
    got = [(by_id[chunk_id].document_name, by_id[chunk_id].ordinal) for chunk_id in expected]
    assert got == list(zip(_EXPECTED_NAMES, _EXPECTED_ORDINALS, strict=True))


async def test_service_tie_order_end_to_end(container, sm) -> None:
    """Wynik usługi przy remisie score: a.txt#0, a.txt#1, b.txt#0, c.txt#0 (C3)."""
    ds, expected = await _seed_ties(sm, dim=1024)
    query = RetrievalQuery(question=_QUESTION, dataset_ids=(ds.id,), similarity_threshold=0.0)
    result = await container.retrieval.retrieve(principal_for(ds.tenant_id), query)
    assert [chunk.chunk_id for chunk in result.chunks] == expected
    assert [chunk.document_name for chunk in result.chunks] == _EXPECTED_NAMES
