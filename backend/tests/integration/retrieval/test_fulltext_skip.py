"""Przy wadze wektorów 1.0 retrieval nie wykonuje zapytania FULLTEXT (ranking go nie używa)."""

import pytest

from app.db.repositories import retrieval as retrieval_repo
from app.db.uow import transaction
from app.domain.retrieval.query import prepare_query
from app.domain.retrieval.stopwords import STOPWORDS
from app.services import retrieval as retrieval_service
from app.text.fulltext import stem_text
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import insert_chunk, insert_document

pytestmark = pytest.mark.db

QUESTION = "umowa najmu"
N_CHUNKS = 2


async def _collect(sm, monkeypatch, weight: float) -> tuple[int, list[str]]:
    """Wywołuje ``_collect`` z licznikiem wywołań ``fulltext_candidates``."""
    ds = await seed_dataset(sm, embedding_dim=4)
    doc = await insert_document(sm, ds, name="umowy.txt")
    await insert_chunk(
        sm, ds.id, doc, ordinal=0, text="umowa najmu lokalu", vector=[1.0, 0.0, 0.0, 0.0]
    )
    await insert_chunk(sm, ds.id, doc, ordinal=1, text="inny tekst", vector=[0.0, 1.0, 0.0, 0.0])
    calls: list[int] = []
    original = retrieval_repo.fulltext_candidates

    async def counting(*args, **kwargs):
        calls.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(retrieval_service.repo, "fulltext_candidates", counting)
    async with transaction(sm) as session:
        (ds0,) = await retrieval_repo.get_datasets(session, [ds.id])
    q = retrieval_service.RetrievalQuery(
        question=QUESTION, dataset_ids=(ds.id,), vector_similarity_weight=weight
    )
    qt = prepare_query(QUESTION, stopwords=STOPWORDS, stem=stem_text)
    candidates, _ = await retrieval_service._collect(
        sm, q, qt, ds0, docs=None, qv=[1.0, 0.0, 0.0, 0.0]
    )
    return len(calls), [c.chunk_id for c in candidates]


async def test_weight_one_skips_fulltext(sm, monkeypatch) -> None:
    """Waga 1.0: brak zapytania FULLTEXT, kandydaci tylko z wektorów (oba chunki)."""
    calls, ids = await _collect(sm, monkeypatch, 1.0)
    assert calls == 0
    assert len(ids) == N_CHUNKS


async def test_weight_below_one_runs_fulltext(sm, monkeypatch) -> None:
    """Waga < 1.0: FULLTEXT dalej wykonywany (term_similarity wchodzi do fuzji)."""
    calls, ids = await _collect(sm, monkeypatch, 0.9)
    assert calls == 1
    assert len(ids) == N_CHUNKS
