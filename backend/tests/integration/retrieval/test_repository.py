"""Testy repozytorium retrievalu na prawdziwej MariaDB (brief T3, kontrakt M7)."""

import pytest

from app.db.repositories import retrieval as retrieval_repo
from app.db.uow import transaction
from app.text.fulltext import ft_text, stem_text
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import insert_chunk, insert_document

pytestmark = pytest.mark.db


async def _seed_abc(sm) -> tuple[str, str, str, str]:
    """Dataset dim=4, dokument i chunki A/B/C z wektorami; zwraca (dataset_id, id_a, id_b, id_c)."""
    ds = await seed_dataset(sm, embedding_dim=4)
    doc = await insert_document(sm, ds, name="wektory.txt")
    a = await insert_chunk(sm, ds.id, doc, ordinal=0, text="A", vector=[1.0, 0.0, 0.0, 0.0])
    b = await insert_chunk(sm, ds.id, doc, ordinal=1, text="B", vector=[0.8, 0.6, 0.0, 0.0])
    c = await insert_chunk(sm, ds.id, doc, ordinal=2, text="C", vector=[0.0, 1.0, 0.0, 0.0])
    return ds.id, a, b, c


async def test_get_datasets_returns_info_and_skips_missing(sm) -> None:
    """get_datasets: DatasetInfo (permission 'me' domyślnie, model/dim z seeda); braki pominięte."""
    ds = await seed_dataset(sm, embedding_model="fake-embed-4", embedding_dim=4)
    async with transaction(sm) as session:
        info = await retrieval_repo.get_datasets(session, [ds.id, "f" * 32])
    assert info == [
        retrieval_repo.DatasetInfo(
            id=ds.id,
            tenant_id=ds.tenant_id,
            permission="me",
            embedding_model="fake-embed-4",
            embedding_dim=4,
        )
    ]


async def test_empty_inputs_return_empty_without_sql(sm) -> None:
    """Puste wejścia → [] / {} bez wykonywania SQL (wymaganie 2 briefu)."""
    ds = await seed_dataset(sm, embedding_dim=4)
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,), document_ids=())
    async with transaction(sm) as session:
        assert await retrieval_repo.get_datasets(session, []) == []
        assert await retrieval_repo.document_metas(session, []) == {}
        got_vec = await retrieval_repo.vector_candidates(session, 4, [1.0, 0.0, 0.0, 0.0], scope, 5)
        assert got_vec == []
        assert await retrieval_repo.fulltext_candidates(session, "umowa", "", scope, 5) == []
        assert await retrieval_repo.vector_scores(session, 4, [1.0, 0.0, 0.0, 0.0], []) == {}
        assert await retrieval_repo.load_chunks(session, []) == []


async def test_document_metas_only_enabled(sm) -> None:
    """document_metas: tylko dokumenty enabled=1, meta_fields jako dict (przypadek 2)."""
    ds = await seed_dataset(sm)
    enabled_id = await insert_document(sm, ds, name="a.txt", meta={"author": "Jan"})
    await insert_document(sm, ds, name="b.txt", enabled=False, meta={"author": "Off"})
    async with transaction(sm) as session:
        metas = await retrieval_repo.document_metas(session, [ds.id])
    assert metas == {enabled_id: {"author": "Jan"}}


async def test_vector_candidates_ranks_by_cosine(sm) -> None:
    """vector_candidates: ranking po podobieństwie cosinusowym (przypadek 3)."""
    ds_id, a, b, c = await _seed_abc(sm)
    scope = retrieval_repo.Scope(dataset_ids=(ds_id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.vector_candidates(session, 4, [1.0, 0.0, 0.0, 0.0], scope, 10)
    assert got == [
        (a, pytest.approx(1.0, abs=1e-5)),
        (b, pytest.approx(0.8, abs=1e-5)),
        (c, pytest.approx(0.0, abs=1e-5)),
    ]


async def test_vector_candidates_limit_truncates(sm) -> None:
    """vector_candidates: LIMIT obcina do dwóch pierwszych (przypadek 3)."""
    ds_id, a, b, _c = await _seed_abc(sm)
    scope = retrieval_repo.Scope(dataset_ids=(ds_id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.vector_candidates(session, 4, [1.0, 0.0, 0.0, 0.0], scope, 2)
    assert [chunk_id for chunk_id, _ in got] == [a, b]


async def test_vector_without_table_returns_empty(sm) -> None:
    """Brak tabeli wektorów (dim=8) → [] i {} (przypadek 5)."""
    ds = await seed_dataset(sm, embedding_model="fake-embed-8", embedding_dim=8)
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        assert await retrieval_repo.vector_candidates(session, 8, [1.0] * 8, scope, 10) == []
        assert await retrieval_repo.vector_scores(session, 8, [1.0] * 8, ["c" * 16]) == {}


async def test_vector_scores_for_ids(sm) -> None:
    """vector_scores: dict z podobieństwami dla podanych id (przypadek 6)."""
    _, a, b, c = await _seed_abc(sm)
    async with transaction(sm) as session:
        scores = await retrieval_repo.vector_scores(session, 4, [1.0, 0.0, 0.0, 0.0], [a, b, c])
    assert scores == {
        a: pytest.approx(1.0, abs=1e-5),
        b: pytest.approx(0.8, abs=1e-5),
        c: pytest.approx(0.0, abs=1e-5),
    }


async def test_filter_committed_zero_excluded(sm) -> None:
    """Chunk committed=0 nie wraca — wektor i FULLTEXT (przypadek 4)."""
    ds = await seed_dataset(sm, embedding_dim=4)
    doc = await insert_document(sm, ds, name="f.txt")
    await insert_chunk(
        sm,
        ds.id,
        doc,
        ordinal=0,
        text="umowa najmu",
        committed=False,
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got_vec = await retrieval_repo.vector_candidates(
            session, 4, [1.0, 0.0, 0.0, 0.0], scope, 10
        )
        got_ft = await retrieval_repo.fulltext_candidates(session, "umowa", "", scope, 10)
    assert got_vec == []
    assert got_ft == []


async def test_filter_available_zero_excluded(sm) -> None:
    """Chunk available=0 nie wraca — wektor i FULLTEXT (przypadek 4)."""
    ds = await seed_dataset(sm, embedding_dim=4)
    doc = await insert_document(sm, ds, name="f.txt")
    await insert_chunk(
        sm,
        ds.id,
        doc,
        ordinal=0,
        text="umowa najmu",
        available=False,
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got_vec = await retrieval_repo.vector_candidates(
            session, 4, [1.0, 0.0, 0.0, 0.0], scope, 10
        )
        got_ft = await retrieval_repo.fulltext_candidates(session, "umowa", "", scope, 10)
    assert got_vec == []
    assert got_ft == []


async def test_filter_document_disabled_excluded(sm) -> None:
    """Dokument enabled=0 nie wraca — wektor i FULLTEXT (przypadek 4)."""
    ds = await seed_dataset(sm, embedding_dim=4)
    doc = await insert_document(sm, ds, name="f.txt", enabled=False)
    await insert_chunk(sm, ds.id, doc, ordinal=0, text="umowa najmu", vector=[1.0, 0.0, 0.0, 0.0])
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got_vec = await retrieval_repo.vector_candidates(
            session, 4, [1.0, 0.0, 0.0, 0.0], scope, 10
        )
        got_ft = await retrieval_repo.fulltext_candidates(session, "umowa", "", scope, 10)
    assert got_vec == []
    assert got_ft == []


async def test_filter_other_dataset_excluded(sm) -> None:
    """Chunk innego datasetu nie wraca — wektor i FULLTEXT (przypadek 4)."""
    ds1 = await seed_dataset(sm, embedding_dim=4)
    ds2 = await seed_dataset(sm, embedding_dim=4)
    doc2 = await insert_document(sm, ds2, name="inny.txt")
    await insert_chunk(sm, ds2.id, doc2, ordinal=0, text="umowa najmu", vector=[1.0, 0.0, 0.0, 0.0])
    scope = retrieval_repo.Scope(dataset_ids=(ds1.id,))
    async with transaction(sm) as session:
        got_vec = await retrieval_repo.vector_candidates(
            session, 4, [1.0, 0.0, 0.0, 0.0], scope, 10
        )
        got_ft = await retrieval_repo.fulltext_candidates(session, "umowa", "", scope, 10)
    assert got_vec == []
    assert got_ft == []


async def test_filter_document_ids_scope(sm) -> None:
    """Scope z document_ids=(docA,) zwraca tylko chunki docA — wektor i FULLTEXT (przypadek 4)."""
    ds = await seed_dataset(sm, embedding_dim=4)
    doc_a = await insert_document(sm, ds, name="a.txt")
    doc_b = await insert_document(sm, ds, name="b.txt")
    chunk_a = await insert_chunk(
        sm, ds.id, doc_a, ordinal=0, text="umowa najmu", vector=[1.0, 0.0, 0.0, 0.0]
    )
    await insert_chunk(sm, ds.id, doc_b, ordinal=0, text="umowa najmu", vector=[1.0, 0.0, 0.0, 0.0])
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,), document_ids=(doc_a,))
    async with transaction(sm) as session:
        got_vec = await retrieval_repo.vector_candidates(
            session, 4, [1.0, 0.0, 0.0, 0.0], scope, 10
        )
        got_ft = await retrieval_repo.fulltext_candidates(session, "umowa", "", scope, 10)
    assert [chunk_id for chunk_id, _ in got_vec] == [chunk_a]
    assert got_ft == [chunk_a]


async def test_fulltext_raw_hits_content(sm) -> None:
    """fulltext_candidates: q_raw trafia w content_ft (przypadek 7)."""
    ds = await seed_dataset(sm)
    doc = await insert_document(sm, ds, name="umowa.txt")
    najem = await insert_chunk(sm, ds.id, doc, ordinal=0, text="Umowa najmu lokalu w Krakowie")
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.fulltext_candidates(session, "umowa", "", scope, 10)
    assert got == [najem]


async def test_fulltext_stem_flexion_hits_via_content_stem(sm) -> None:
    """Fleksja: „tatrach” po stemie („tatra”) trafia w content_stem (przypadek 7)."""
    ds = await seed_dataset(sm)
    doc = await insert_document(sm, ds, name="tatry.txt")
    tatry = await insert_chunk(sm, ds.id, doc, ordinal=0, text="Wysokie Tatry zimą")
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.fulltext_candidates(
            session, "tatrach", stem_text("tatrach"), scope, 10
        )
    assert got == [tatry]


async def test_fulltext_empty_stem_misses_flexion(sm) -> None:
    """q_raw bez trafienia i pusty q_stem → brak wyniku (dowód działania content_stem)."""
    ds = await seed_dataset(sm)
    doc = await insert_document(sm, ds, name="tatry.txt")
    await insert_chunk(sm, ds.id, doc, ordinal=0, text="Wysokie Tatry zimą")
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.fulltext_candidates(session, "tatrach", "", scope, 10)
    assert got == []


async def test_fulltext_keywords_boost_ranks_first(sm) -> None:
    """Słowo z keywords (important_ft, waga 30) wyprzedza to samo słowo w treści (przypadek 8)."""
    ds = await seed_dataset(sm)
    doc = await insert_document(sm, ds, name="r.txt")
    with_kwd = await insert_chunk(
        sm, ds.id, doc, ordinal=0, text="Pies w ogrodzie", keywords=("kot",)
    )
    in_content = await insert_chunk(sm, ds.id, doc, ordinal=1, text="Kot na płocie")
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.fulltext_candidates(session, "kot", "", scope, 10)
    assert got == [with_kwd, in_content]


async def test_fulltext_boolean_operators_sanitized(sm) -> None:
    """Łańcuch z operatorami boolean nie powoduje błędu SQL (przypadek 9)."""
    ds = await seed_dataset(sm)
    doc = await insert_document(sm, ds, name="o.txt")
    najem = await insert_chunk(sm, ds.id, doc, ordinal=0, text="Umowa najmu lokalu")
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        got = await retrieval_repo.fulltext_candidates(session, '+umowa -"x" (y)*', "", scope, 10)
    assert got == [najem]


async def test_fulltext_both_chains_empty_returns_empty(sm) -> None:
    """Oba łańcuchy puste → [] bez SQL (przypadek 9)."""
    ds = await seed_dataset(sm)
    scope = retrieval_repo.Scope(dataset_ids=(ds.id,))
    async with transaction(sm) as session:
        assert await retrieval_repo.fulltext_candidates(session, "", "", scope, 10) == []


async def test_load_chunks_order_and_fields(sm) -> None:
    """load_chunks: kolejność id, meta dokumentu, JSON-y, positions NULL → [] (przypadek 10)."""
    ds = await seed_dataset(sm)
    doc = await insert_document(sm, ds, name="raport.txt", meta={"author": "Jan"})
    first = await insert_chunk(
        sm,
        ds.id,
        doc,
        ordinal=0,
        text="Pierwszy paragraf",
        title="Tytuł",
        keywords=("kot",),
        questions=("Co to?",),
    )
    second = await insert_chunk(sm, ds.id, doc, ordinal=1, text="Drugi paragraf")
    async with transaction(sm) as session:
        rows = await retrieval_repo.load_chunks(session, [second, first])
    assert [row.id for row in rows] == [second, first]
    row = rows[1]
    assert row.document_id == doc
    assert row.dataset_id == ds.id
    assert row.document_name == "raport.txt"
    assert row.document_meta == {"author": "Jan"}
    assert row.content == "Pierwszy paragraf"
    assert row.content_llm is None
    assert row.content_stem == stem_text(ft_text("Pierwszy paragraf"))
    assert row.title_ft == "Tytuł"
    assert row.important_ft == "kot"
    assert row.question_ft == "Co to?"
    assert row.keywords == ["kot"]
    assert row.questions == ["Co to?"]
    assert row.positions == []
    assert row.chunk_type == "text"
