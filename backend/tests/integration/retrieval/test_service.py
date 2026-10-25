"""Testy integracyjne DbRetrievalService na MariaDB + fake-llm (brief T5, kontrakt M6)."""

import re
import unicodedata
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from app.domain.retrieval.types import DocAgg
from app.services.retrieval import RetrievalQuery
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import ingest_text, principal_for, register_rerank

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

# „umowa.txt”: tekst o umowie najmu lokalu w Krakowie; „urlop.txt”: o wnioskach urlopowych.
_UMOWA = (
    "Umowa najmu lokalu użytkowego w Krakowie. Wynajmujący oddaje najemcy lokal przy ulicy "
    "Grodeckiej 7. Najemca płaci czynsz dziesiątego dnia każdego miesiąca. Umowa najmu może "
    "zostać wypowiedziana z zachowaniem trzymiesięcznego okresu wypowiedzenia. Wypowiedzenie "
    "umowy najmu lokalu wymaga formy pisemnej. Po zakończeniu umowy najemca zwraca lokal."
) * 2

_URLOP = (
    "Wnioski urlopowe pracowników. Urlop wypoczynkowy wymaga akceptacji przełożonego. "
    "Wniosek urlopowy składa się najpóźniej na dwa tygodnie przed rozpoczęciem urlopu. "
    "Urlop bezpłatny i urlop okolicznościowy regulują odrębne przepisy kodeksu pracy."
) * 2

_QUESTION = "Jak wypowiedzieć umowę najmu lokalu?"


@pytest.fixture
async def ingested(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> AsyncIterator[tuple[Container, DatasetRow]]:
    """Kontener z zingestowanymi „umowa.txt” i „urlop.txt” oraz dataset."""
    ds = await seed_dataset(sm)
    await ingest_text(container, ds, "umowa.txt", _UMOWA)
    await ingest_text(container, ds, "urlop.txt", _URLOP)
    yield container, ds


async def _set_permission(
    sm: async_sessionmaker[AsyncSession], dataset_id: str, permission: str
) -> None:
    """UPDATE datasets.permission w osobnej transakcji (brief T5, przypadek 4)."""
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET permission = :p WHERE id = :id"),
            {"id": dataset_id, "p": permission},
        )


def _fold_tokens(value: str) -> set[str]:
    """Tokenizacja jak w fake-llm: lower, NFKD, bez diakrytyków, ł→l, [a-z0-9]+."""
    lowered = value.lower().replace("ł", "l")
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z0-9]+", stripped))


def _expected_rerank(question: str, document: str) -> float:
    """Punktacja fake-rerank: udział tokenów zapytania obecnych w dokumencie."""
    query_tokens = _fold_tokens(question)
    return len(query_tokens & _fold_tokens(document)) / max(1, len(query_tokens))


async def test_basic_retrieval(ingested: tuple[Container, DatasetRow]) -> None:
    """Wymaganie 1: dwa dokumenty, pytanie o najem → umowa.txt pierwsza, pola wg R0 p. 13."""
    container, ds = ingested
    owner = principal_for(ds.tenant_id)
    query = RetrievalQuery(question=_QUESTION, dataset_ids=(ds.id,))
    result = await container.retrieval.retrieve(owner, query)
    assert result.total >= 1
    assert result.chunks[0].document_name == "umowa.txt"
    assert isinstance(result.doc_aggs, list)
    assert all(isinstance(agg, DocAgg) for agg in result.doc_aggs)
    assert len(result.doc_aggs) >= 1
    assert result.query_vector is not None
    assert len(result.query_vector) == ds.embedding_dim
    for chunk in result.chunks:
        assert 0 <= chunk.similarity <= 1
        assert 0 <= chunk.vector_similarity <= 1
        assert 0 <= chunk.term_similarity <= 1
        assert chunk.image_id == ""
        assert chunk.url is None
        assert chunk.tag_kwd == []
        assert chunk.content_terms


async def test_empty_question_returns_empty_result(
    ingested: tuple[Container, DatasetRow],
) -> None:
    """Wymaganie 2: puste pytanie ("" i same spacje) → pusty wynik."""
    container, ds = ingested
    owner = principal_for(ds.tenant_id)
    for question in ("", "   "):
        query = RetrievalQuery(question=question, dataset_ids=(ds.id,))
        result = await container.retrieval.retrieve(owner, query)
        assert result.total == 0
        assert result.chunks == []
        assert result.doc_aggs == []


async def test_missing_dataset_not_found(container: Container) -> None:
    """Wymaganie 3: nieistniejący dataset → NotFound z komunikatem jak upstream."""
    missing = uuid.uuid4().hex
    query = RetrievalQuery(question="umowa", dataset_ids=(missing,))
    with pytest.raises(NotFound, match=f"You don't own the dataset {missing}."):
        await container.retrieval.retrieve(principal_for(missing), query)


async def test_permission_me_team_superuser(
    ingested: tuple[Container, DatasetRow], sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wymaganie 4: obcy → PermissionDenied; team → ok; właściciel i superuser → ok."""
    container, ds = ingested
    owner = principal_for(ds.tenant_id)
    query = RetrievalQuery(question="umowa najmu", dataset_ids=(ds.id,))
    stranger = principal_for(uuid.uuid4().hex)
    with pytest.raises(PermissionDenied):
        await container.retrieval.retrieve(stranger, query)
    await _set_permission(sm, ds.id, "team")
    result = await container.retrieval.retrieve(stranger, query)
    assert result.total >= 1
    await _set_permission(sm, ds.id, "me")
    assert (await container.retrieval.retrieve(owner, query)).total >= 1
    admin = principal_for(uuid.uuid4().hex, superuser=True)
    assert (await container.retrieval.retrieve(admin, query)).total >= 1


async def test_different_embedding_models_rejected(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wymaganie 5: datasety z różnymi modelami embeddingu → ValidationFailed (R0 p. 4)."""
    ds1 = await seed_dataset(sm)
    ds2 = await seed_dataset(sm, embedding_model="fake-embed-3072", embedding_dim=3072)
    admin = principal_for(uuid.uuid4().hex, superuser=True)
    query = RetrievalQuery(question="umowa", dataset_ids=(ds1.id, ds2.id))
    with pytest.raises(ValidationFailed) as exc_info:
        await container.retrieval.retrieve(admin, query)
    assert exc_info.value.message.startswith("Datasets use different embedding models")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"dataset_ids": ()}, "`dataset_ids` is required."),
        ({"page": 0}, "`page` must be greater than 0"),
        ({"page_size": 0}, "`page_size` must be greater than 0"),
        ({"top_k": 0}, "`top_k` must be greater than 0"),
        ({"vector_similarity_weight": 1.5}, "`vector_similarity_weight` must be between 0 and 1"),
        ({"rerank_model": "fake-rerank", "page": 2}, "`page` must be 1 when `rerank_id` is set."),
    ],
)
async def test_validation_errors(container: Container, overrides: dict, message: str) -> None:
    """Wymaganie 6: walidacja argumentów przed dostępem do bazy (M6 p. 1)."""
    params: dict = {"question": "umowa", "dataset_ids": (uuid.uuid4().hex,)}
    params.update(overrides)
    with pytest.raises(ValidationFailed, match=re.escape(message)):
        await container.retrieval.retrieve(principal_for("u"), RetrievalQuery(**params))


async def test_rerank_scores_override_vector_similarity(
    ingested: tuple[Container, DatasetRow], sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wymaganie 7: rerank → total >= 1 i vector_similarity równy punktacji fake-rerank."""
    container, ds = ingested
    await register_rerank(sm)
    query = RetrievalQuery(question=_QUESTION, dataset_ids=(ds.id,), rerank_model="fake-rerank")
    result = await container.retrieval.retrieve(principal_for(ds.tenant_id), query)
    assert result.total >= 1
    for chunk in result.chunks:
        assert 0 <= chunk.vector_similarity <= 1
        assert chunk.vector_similarity == pytest.approx(_expected_rerank(_QUESTION, chunk.content))


async def test_keyword_expansion(ingested: tuple[Container, DatasetRow]) -> None:
    """Wymaganie 8: keyword=True (fake-chat) → wynik bez błędu, total >= 1.

    fake-chat zwraca jedynie echo „Odpowiedź testowa: Output:” — dopisane „słowo
    kluczowe” rozcieńcza term_similarity, więc próg użytkownika ustawiony na 0
    (asercja dotyczy rozszerzenia pytania, nie progów).
    """
    container, ds = ingested
    query = RetrievalQuery(
        question="umowa najmu lokalu",
        dataset_ids=(ds.id,),
        keyword=True,
        similarity_threshold=0.0,
    )
    result = await container.retrieval.retrieve(principal_for(ds.tenant_id), query)
    assert result.total >= 1


async def test_highlight_flag(ingested: tuple[Container, DatasetRow]) -> None:
    """Wymaganie 9: highlight=True → <em> w highlight; highlight=False → None."""
    container, ds = ingested
    owner = principal_for(ds.tenant_id)
    on = await container.retrieval.retrieve(
        owner, RetrievalQuery(question="umowa najmu", dataset_ids=(ds.id,), highlight=True)
    )
    assert on.chunks[0].highlight is not None and "<em>" in on.chunks[0].highlight
    off = await container.retrieval.retrieve(
        owner, RetrievalQuery(question="umowa najmu", dataset_ids=(ds.id,), highlight=False)
    )
    assert off.chunks[0].highlight is None


async def test_rrf_fusion(
    migrated_db: Settings, tmp_path: Path, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wymaganie 10: kontener z retrieval_fusion=rrf → chunks[0].similarity == 1.0."""
    instance = await make_container(
        migrated_db.model_copy(update={"retrieval_fusion": "rrf"}), tmp_path
    )
    try:
        ds = await seed_dataset(sm)
        await ingest_text(instance, ds, "umowa.txt", _UMOWA)
        query = RetrievalQuery(question="umowa najmu lokalu", dataset_ids=(ds.id,))
        result = await instance.retrieval.retrieve(principal_for(ds.tenant_id), query)
        assert result.total >= 1
        assert result.chunks[0].similarity == 1.0
        assert all(0 <= chunk.similarity <= 1 for chunk in result.chunks)
    finally:
        await instance.aclose()


async def test_no_coverage_question_returns_empty(
    ingested: tuple[Container, DatasetRow],
) -> None:
    """Wymaganie 11: pytanie bez pokrycia → total == 0 (próg min_vector_sim=0.25)."""
    container, ds = ingested
    query = RetrievalQuery(
        question="kwantowa chromodynamika gluonów",
        dataset_ids=(ds.id,),
        vector_similarity_weight=0.3,
    )
    result = await container.retrieval.retrieve(principal_for(ds.tenant_id), query)
    assert result.total == 0


async def test_aggs_false(ingested: tuple[Container, DatasetRow]) -> None:
    """Wymaganie 12: aggs=False → doc_aggs == []."""
    container, ds = ingested
    query = RetrievalQuery(question="umowa najmu", dataset_ids=(ds.id,), aggs=False)
    result = await container.retrieval.retrieve(principal_for(ds.tenant_id), query)
    assert result.total >= 1
    assert result.doc_aggs == []


async def test_top_k_limits_vector_side(ingested: tuple[Container, DatasetRow]) -> None:
    """M6 p. 8: top_k=1 zawęża stronę wektorową; brakujące cosinusy z vector_scores."""
    container, ds = ingested
    query = RetrievalQuery(question=_QUESTION, dataset_ids=(ds.id,), top_k=1)
    result = await container.retrieval.retrieve(principal_for(ds.tenant_id), query)
    assert result.total >= 1
    assert result.query_vector is not None
    assert len(result.query_vector) == ds.embedding_dim


async def test_container_not_started_and_lazy_property(migrated_db: Settings) -> None:
    """M8: właściwość retrieval zwraca tę samą instancję; bez start() → RuntimeError."""
    instance = Container(migrated_db)
    assert instance.retrieval is instance.retrieval
    query = RetrievalQuery(question="umowa", dataset_ids=(uuid.uuid4().hex,))
    with pytest.raises(RuntimeError, match="container not started"):
        await instance.retrieval.retrieve(principal_for("u"), query)
