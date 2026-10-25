"""Usługa retrievalu (kontrakt WP E1-7 M6): domena + repozytorium + LLM + polityka.

Składa ``prepare_query``, scoring, repozytorium (M7), bramkę LLM i politykę dostępu
w ``RetrievalResult``. Wywołania LLM (chat, embed_query, rerank) poza transakcjami
bazy: transakcja 1 — datasety i metadane, potem LLM; transakcja 2 — kandydaci,
wiersze; potem rerank i fuzja (wymaganie 1 briefu T5).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import ceil
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound, ValidationFailed
from app.db.repositories import retrieval as repo
from app.db.repositories.retrieval import ChunkRow, DatasetInfo, Scope
from app.db.uow import transaction
from app.domain.policy import Action, ResourceRef, require
from app.domain.policy.principal import Principal
from app.domain.retrieval.highlight import highlight
from app.domain.retrieval.metadata import MetadataCondition
from app.domain.retrieval.query import prepare_query
from app.domain.retrieval.scoring import (
    apply_thresholds,
    chunk_terms,
    doc_aggs,
    fuse,
    term_similarity,
)
from app.domain.retrieval.stopwords import STOPWORDS
from app.domain.retrieval.types import (
    Candidate,
    QueryTerms,
    RetrievalResult,
    RetrievedChunk,
    Scored,
    ThresholdConfig,
)
from app.llm.errors import LLMError
from app.prompts import load_prompt
from app.services.enrich import KEYWORD_PROMPT, parse_keywords, render
from app.services.meta_filter import document_scope, resolve_filter
from app.text.fulltext import stem_text

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.core.container import Container
    from app.llm.gateway import LLMGateway
    from app.llm.registry import ModelRegistry

logger = logging.getLogger(__name__)

# Kolumna datasets.permission jest ENUM('me','team') — tak czyta ją repozytorium (M7).
_Permission = Literal["me", "team"]
_ERROR_MARKER = "**ERROR**"


@dataclass(frozen=True)
class RetrievalQuery:
    """Parametry wyszukiwania (06 §14 dosłownie)."""

    question: str
    dataset_ids: tuple[str, ...]
    document_ids: tuple[str, ...] | None = None
    page: int = 1
    page_size: int = 30
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3
    top_k: int = 1024
    rerank_candidates_count: int = 64
    rerank_model: str | None = None
    keyword: bool = False
    cross_languages: tuple[str, ...] = ()
    highlight: bool = False
    metadata_condition: MetadataCondition | None = None
    # ``meta_data_filter`` (auto/semi_auto) wymaga modelu — rozwiązuje go usługa (K11 §10f p. 5).
    meta_data_filter: Mapping[str, Any] | None = None
    aggs: bool = True


class RetrievalService(Protocol):
    """Port usługi retrievalu (M6)."""

    async def retrieve(self, principal: Principal, q: RetrievalQuery) -> RetrievalResult: ...

    async def retrieve_trusted(self, q: RetrievalQuery) -> RetrievalResult: ...


def _validate(q: RetrievalQuery) -> None:
    """Walidacja argumentów (M6 p. 1); komunikaty wg upstream chunk_api i R0 p. 3."""
    if not q.dataset_ids:
        raise ValidationFailed("`dataset_ids` is required.")
    if q.page < 1:
        raise ValidationFailed("`page` must be greater than 0")
    if q.page_size < 1:
        raise ValidationFailed("`page_size` must be greater than 0")
    if q.top_k <= 0:
        raise ValidationFailed("`top_k` must be greater than 0")
    if not 0 <= q.vector_similarity_weight <= 1:
        raise ValidationFailed("`vector_similarity_weight` must be between 0 and 1")
    if q.rerank_model and q.page > 1:
        raise ValidationFailed("`page` must be 1 when `rerank_id` is set.")


def _window(page_size: int, n: int, top: int) -> int:
    """Okno kandydatów — port Dealer._rerank_window (search.py:538-560) z 64 → n (R0 p. 2)."""
    if page_size <= 1:
        return min(30, top) if top > 0 else 30
    window = ceil(n / page_size) * page_size
    if top > 0:
        window = min(window, ceil(top / page_size) * page_size)
    return window


def _limit(q: RetrievalQuery) -> int:
    """Blok kandydatów obejmujący żądaną stronę (R0 p. 2)."""
    top = q.top_k if q.rerank_model else 0
    window = _window(q.page_size, q.rerank_candidates_count, top)
    return window * ((q.page - 1) * q.page_size // window + 1)


def _union(vec: Sequence[tuple[str, float]], ft: Sequence[str]) -> list[str]:
    """Unia id kandydatów po dedup: najpierw wektorowi, potem FULLTEXT (R0 p. 2)."""
    ids: list[str] = []
    seen: set[str] = set()
    for chunk_id in [chunk_id for chunk_id, _ in vec] + list(ft):
        if chunk_id not in seen:
            seen.add(chunk_id)
            ids.append(chunk_id)
    return ids


def _empty() -> RetrievalResult:
    """Pusty wynik retrievalu (M6 p. 4 i p. 6)."""
    return RetrievalResult(total=0, chunks=[], doc_aggs=[])


def _check_datasets(
    principal: Principal | None, q: RetrievalQuery, datasets: Sequence[DatasetInfo]
) -> DatasetInfo:
    """Istnienie i polityka w kolejności dataset_ids, potem spójność embeddingu (M6 p. 2-3).

    ``principal=None`` (retrieve_trusted, C10) pomija pętlę require(READ) — czat ma USE,
    więc wybór datasetów jest zaufany; pozostałe błędy bez zmian.
    """
    by_id = {d.id: d for d in datasets}
    ordered: list[DatasetInfo] = []
    for dataset_id in q.dataset_ids:
        ds = by_id.get(dataset_id)
        if ds is None:
            raise NotFound(f"You don't own the dataset {dataset_id}.")
        if principal is not None:
            require(
                principal,
                Action.READ,
                ResourceRef(
                    kind="dataset",
                    owner_id=ds.tenant_id,
                    permission=cast(_Permission, ds.permission),
                    id=ds.id,
                ),
            )
        ordered.append(ds)
    ds0 = ordered[0]
    for ds in ordered[1:]:
        if (ds.embedding_model, ds.embedding_dim) != (ds0.embedding_model, ds0.embedding_dim):
            raise ValidationFailed(
                f"Datasets use different embedding models: {[d.embedding_model for d in ordered]}"
            )
    return ds0


async def _expand_keywords(llm: LLMGateway, models: ModelRegistry, question: str) -> str:
    """Słowa kluczowe od modelu czatu (M6 p. 5, R0 p. 11); wiadomości jak enrich._chat."""
    chat_model = await models.resolve(None, "chat")
    messages: Sequence[dict[str, str]] = [
        {"role": "system", "content": render(KEYWORD_PROMPT, topn=3, content=question)},
        {"role": "user", "content": "Output: "},
    ]
    result = await llm.chat(chat_model, messages, temperature=0.2, cache=True)
    keywords = parse_keywords(result.text, 3)
    if not keywords:
        return question
    return question + " " + " ".join(keywords)


async def _cross_languages(
    llm: LLMGateway, models: ModelRegistry, question: str, languages: tuple[str, ...]
) -> str:
    """Przepisuje pytanie jednym wywołaniem modelu czatu (port generator.cross_languages, C3).

    Render ręczny bez jinja2: najpierw języki, potem pytanie (może zawierać ``{{``). Błąd
    bramki LLM albo ``**ERROR**`` w odpowiedzi → oryginalne pytanie (log info), jak upstream.
    """
    chat_model = await models.resolve(None, "chat")
    user = load_prompt("cross_languages_user_prompt")
    user = user.replace("{{ languages | join(', ') }}", ", ".join(languages))
    messages: Sequence[dict[str, str]] = [
        {"role": "system", "content": load_prompt("cross_languages_sys_prompt")},
        {"role": "user", "content": user.replace("{{ query }}", question)},
    ]
    try:
        result = await llm.chat(chat_model, messages, temperature=0.2, cache=True)
    except LLMError as exc:
        logger.info("[cross_languages] %s, falling back to original query", type(exc).__name__)
        return question
    if _ERROR_MARKER in result.text:
        logger.info("[cross_languages] LLM returned error, falling back to original query")
        return question
    cleaned = re.sub(r"(^Output:|\n+)", "", result.text, flags=re.DOTALL)
    return "\n".join(part for part in cleaned.split("===") if part.strip())


async def _collect(  # noqa: PLR0913 — kształt kroków 7-8 z kontraktu M6
    sessionmaker: async_sessionmaker[AsyncSession],
    q: RetrievalQuery,
    qt: QueryTerms,
    ds0: DatasetInfo,
    *,
    docs: tuple[str, ...] | None,
    qv: list[float] | None,
) -> tuple[list[Candidate], list[ChunkRow]]:
    """Transakcja 2: kandydaci, brakujące cosinusy, wiersze, term_similarity (M6 p. 7-8).

    Tryb termowy (``qv is None``, R0 p. 1): strona wektorowa pominięta, cosinusy 0.0.
    Stem tytułu liczony raz na dokument (słownik lokalny).
    """
    scope = Scope(dataset_ids=q.dataset_ids, document_ids=docs)
    limit = _limit(q)
    async with transaction(sessionmaker) as session:
        vec: list[tuple[str, float]] = []
        if qv is not None:
            vec = await repo.vector_candidates(
                session, ds0.embedding_dim, qv, scope, min(q.top_k, limit)
            )
        ft = await repo.fulltext_candidates(session, qt.ft_raw, qt.ft_stem, scope, limit)
        ids = _union(vec, ft)
        have = {chunk_id for chunk_id, _ in vec}
        missing = [chunk_id for chunk_id in ids if chunk_id not in have]
        scores = (
            await repo.vector_scores(session, ds0.embedding_dim, qv, missing)
            if qv is not None and missing
            else {}
        )
        rows = await repo.load_chunks(session, ids)
    similarity = dict(vec) | scores
    title_stems: dict[str, str] = {}
    candidates: list[Candidate] = []
    for row in rows:
        title = title_stems.get(row.document_id)
        if title is None:
            title = stem_text(row.title_ft)
            title_stems[row.document_id] = title
        ts = term_similarity(
            qt,
            chunk_terms(
                row.content_stem,
                title,
                stem_text(row.important_ft),
                stem_text(row.question_ft),
            ),
        )
        candidates.append(
            Candidate(
                chunk_id=row.id,
                document_id=row.document_id,
                document_name=row.document_name,
                ordinal=row.ordinal,
                vector_similarity=similarity.get(row.id, 0.0),
                term_similarity=ts,
            )
        )
    return candidates, rows


def _to_chunk(
    scored: Scored, row: ChunkRow, qt: QueryTerms, with_highlight: bool
) -> RetrievedChunk:
    """Mapowanie Scored + ChunkRow → RetrievedChunk (R0 p. 13)."""
    c = scored.candidate
    terms = qt.raw_terms + tuple(term for term, _ in qt.terms)
    return RetrievedChunk(
        chunk_id=c.chunk_id,
        content=row.content,
        content_llm=row.content_llm or row.content,
        content_terms=row.content_stem,
        document_id=c.document_id,
        document_name=c.document_name,
        dataset_id=row.dataset_id,
        image_id="",
        important_keywords=row.keywords,
        questions=row.questions,
        tag_kwd=[],
        positions=row.positions,
        similarity=scored.similarity,
        vector_similarity=c.rerank_score if c.rerank_score is not None else c.vector_similarity,
        term_similarity=c.term_similarity,
        highlight=highlight(row.content, terms) if with_highlight else None,
        doc_type=row.chunk_type if row.chunk_type in ("table", "image") else "",
        url=None,
        # Brak metadanych ({}) → None: złoto upstream (chunks_format, l. 62) daje null,
        # bo document_metadata pojawia się tylko przy wzbogacaniu metadanymi (dług E2-1).
        document_metadata=row.document_meta or None,
    )


class DbRetrievalService:
    """Retrieval na MariaDB (M6): zależności czytane z kontenera w chwili wywołania (C4)."""

    def __init__(self, container: Container) -> None:
        """Zapamiętuje kontener; bez I/O — właściwość Container.retrieval może powstać
        przed start()."""
        self._container = container

    def _deps(self) -> tuple[async_sessionmaker[AsyncSession], LLMGateway, ModelRegistry, Settings]:
        """Zależności z kontenera; kontener nie wystartował → RuntimeError (C4)."""
        sessionmaker = self._container.sessionmaker
        llm = self._container.llm
        models = self._container.models
        if sessionmaker is None or llm is None or models is None:
            raise RuntimeError("container not started")
        return sessionmaker, llm, models, self._container.settings

    async def retrieve(self, principal: Principal, q: RetrievalQuery) -> RetrievalResult:
        """Wyszukanie wg algorytmu M6: walidacja → datasety → require(READ) → retrieve_trusted."""
        sessionmaker = self._deps()[0]
        _validate(q)
        async with transaction(sessionmaker) as session:
            datasets = await repo.get_datasets(session, q.dataset_ids)
        _check_datasets(principal, q, datasets)
        return await self.retrieve_trusted(q)

    async def retrieve_trusted(self, q: RetrievalQuery) -> RetrievalResult:
        """Retrieval bez sprawdzania READ (C10): czat ma USE, wybór datasetów zaufany."""
        sessionmaker, llm, models, settings = self._deps()
        _validate(q)
        needs_metas = q.metadata_condition is not None or q.meta_data_filter is not None
        async with transaction(sessionmaker) as session:
            datasets = await repo.get_datasets(session, q.dataset_ids)
            metas = await repo.document_metas(session, q.dataset_ids) if needs_metas else {}
        ds0 = _check_datasets(None, q, datasets)
        question = q.question.strip()
        if not question:
            return _empty()
        condition = q.metadata_condition
        # auto/semi_auto: warunki generuje model (K11 §10f p. 5), poza transakcją bazy.
        if condition is None and q.meta_data_filter is not None:
            condition = await resolve_filter(llm, models, metas, question, q.meta_data_filter)
        if q.cross_languages:
            question = await _cross_languages(llm, models, question, q.cross_languages)
        if q.keyword:
            question = await _expand_keywords(llm, models, question)
        docs = document_scope(metas, condition, q.document_ids)
        if docs == ():
            return _empty()
        qt = prepare_query(question, stopwords=STOPWORDS, stem=stem_text)
        w = q.vector_similarity_weight
        qv: list[float] | None = None
        if w > 0:
            model = await models.resolve(ds0.embedding_model, "embedding")
            qv = await llm.embed_query(model, question)
        candidates, rows = await _collect(sessionmaker, q, qt, ds0, docs=docs, qv=qv)
        if q.rerank_model:
            reranker = await models.resolve(q.rerank_model, "rerank")
            scores = await llm.rerank(reranker, question, [row.content for row in rows])
            candidates = [
                replace(c, rerank_score=score) for c, score in zip(candidates, scores, strict=True)
            ]
        scored = fuse(candidates, w, settings.retrieval_fusion)
        valid = apply_thresholds(
            scored,
            ThresholdConfig(
                min_vector_sim=settings.min_vector_sim,
                min_rerank_score=settings.min_rerank_score,
            ),
            w,
            q.similarity_threshold,
        )
        by_id = {row.id: row for row in rows}
        page = valid[(q.page - 1) * q.page_size : q.page * q.page_size]
        return RetrievalResult(
            total=len(valid),
            chunks=[_to_chunk(s, by_id[s.candidate.chunk_id], qt, q.highlight) for s in page],
            doc_aggs=doc_aggs(valid) if q.aggs else [],
            query_vector=qv,
        )
