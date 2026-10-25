"""Kroki pipeline czatu (K4 §4, CONTRACT C12): historia, refine, retrieval, post-hoc, zapis.

Wydzielone z ``chat_pipeline`` (limit 400 linii): funkcje pojedynczych kroków —
bez zmiany logiki. Wywołania LLM poza transakcjami bazy; zapis sesji w jednej
transakcji z blokadą wiersza sesji (K4 §3.4).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.timeutil import from_ms
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories import chat_sessions as chat_sessions_repo
from app.db.repositories import document_profiles as document_profiles_repo
from app.db.repositories import retrieval as retrieval_repo
from app.db.repositories.chat_messages import MessageRow
from app.db.repositories.document_profiles import CatalogDoc
from app.db.uow import transaction
from app.domain.chat.citations import answer_pieces, hybrid_similarity, place_citations
from app.domain.chat.config import ASK_RETRIEVAL, RetrievalDefaults
from app.domain.chat.prompts import clean_history_content, conversation_text, render_full_question
from app.domain.retrieval.query import prepare_query
from app.domain.retrieval.scoring import chunk_terms, term_similarity
from app.domain.retrieval.stopwords import STOPWORDS
from app.domain.retrieval.types import DocAgg, RetrievedChunk
from app.llm.gateway import LLMGateway
from app.llm.registry import ModelRegistry
from app.llm.types import ModelRef
from app.prompts import load_prompt
from app.services.enrich import KEYWORD_PROMPT, parse_keywords, render
from app.services.retrieval import RetrievalQuery
from app.text.fulltext import stem_text

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.core.container import Container
    from app.db.repositories.chats import ChatRow
    from app.services.chat import CompletionRequest
    from app.services.chat_pipeline import RunContext, RunState

# Liczba słów kluczowych dopisywanych do pytania (jak _expand_keywords w retrievalu).
KEYWORD_TOPN = 3
# Maksymalna długość id wiadomości user przekazanego w żądaniu (K4 §3.3: 36 znaków ASCII).
MESSAGE_ID_MAX_LEN = 36


def deps(
    container: Container,
) -> tuple[async_sessionmaker[AsyncSession], LLMGateway, ModelRegistry, Settings]:
    """Zależności z kontenera; kontener nie wystartował → RuntimeError (jak w retrievalu)."""
    sessionmaker = container.sessionmaker
    llm = container.llm
    models = container.models
    if sessionmaker is None or llm is None or models is None:
        raise RuntimeError("container not started")
    return sessionmaker, llm, models, container.settings


def chat_row(ctx: RunContext) -> ChatRow:
    """Wiersz czatu dla kroków wymagających datasetów; solo nigdy tu nie trafia."""
    if ctx.chat is None:
        raise RuntimeError("chat datasets without a chat row")
    return ctx.chat


async def history(
    sessionmaker: async_sessionmaker[AsyncSession], req: CompletionRequest, session_id: str | None
) -> list[dict[str, Any]]:
    """Historia do LLM (K4 §3.4): bez system, bez wiodących assistant; assistant czyszczony."""
    if req.pass_all_history_messages:
        rows: list[dict[str, Any]] = [dict(m) for m in req.messages[:-1]]
    elif session_id is None:
        rows = []
    else:
        async with transaction(sessionmaker) as session:
            rows = [
                {
                    "role": m.role,
                    "content": clean_history_content(m.content)
                    if m.role == "assistant"
                    else m.content,
                }
                for m in await chat_messages_repo.list_by_session(session, session_id)
            ]
    while rows and rows[0]["role"] == "assistant":
        rows.pop(0)
    return [r for r in rows if r["role"] != "system"]


def iso_date(now_ms: int, offset_days: int) -> str:
    """Data ISO dla render_full_question (upstream: date.today ± 1 dzień)."""
    return (from_ms(now_ms) + timedelta(days=offset_days)).date().isoformat()


async def refine(
    llm: LLMGateway, model: ModelRef, ctx: RunContext, now_ms: int, conversation: str
) -> str:
    """Przepisanie pytania wieloturowego (GEN full_question); fallback na ostatnie pytanie.

    ``conversation`` — pełny dialog (historia + bieżące pytanie, GEN l. 268-273); przy
    domyślnej ścieżce historia sesji leży w bazie, więc pełne ``req.messages`` nie wystarczą.
    """
    messages: Sequence[dict[str, str]] = [
        {
            "role": "system",
            "content": render_full_question(
                load_prompt("full_question_prompt"),
                today=iso_date(now_ms, 0),
                yesterday=iso_date(now_ms, -1),
                tomorrow=iso_date(now_ms, 1),
                language=None,
                conversation=conversation,
            ),
        },
        {"role": "user", "content": "Output: "},
    ]
    result = await llm.chat(model, messages, temperature=0.2, cache=True)
    if result.text and "**ERROR**" not in result.text:
        return result.text
    return str(ctx.req.messages[-1]["content"])


async def keywords(llm: LLMGateway, model: ModelRef, question: str) -> str:
    """Dopisanie słów kluczowych (prompt E1-6/E1-7); pusty wynik → pytanie bez zmian."""
    messages: Sequence[dict[str, str]] = [
        {"role": "system", "content": render(KEYWORD_PROMPT, topn=KEYWORD_TOPN, content=question)},
        {"role": "user", "content": "Output: "},
    ]
    result = await llm.chat(model, messages, temperature=0.2, cache=True)
    parsed = parse_keywords(result.text, KEYWORD_TOPN)
    if not parsed:
        return question
    return question + "," + ", ".join(parsed)


async def pick_questions(
    llm: LLMGateway, ctx: RunContext, history_rows: list[dict[str, Any]]
) -> tuple[list[str], float]:
    """Pytanie do retrievalu i promptu: refine wieloturowy (opcjonalnie) + słowa kluczowe."""
    current: dict[str, Any] = {"role": "user", "content": ctx.req.messages[-1]["content"]}
    past = [str(m["content"]) for m in [*history_rows, current] if m["role"] == "user"]
    refine_ms = 0.0
    if len(past) > 1 and ctx.prompt_config.get("refine_multiturn"):
        refine_started = time.perf_counter()
        # conversation z pełnego dialogu (historia + bieżące) — jak upstream msg (GEN l. 268-273)
        conversation = conversation_text([*history_rows, current])
        questions = [await refine(llm, ctx.model, ctx, ctx.container.clock.now_ms(), conversation)]
        refine_ms = (time.perf_counter() - refine_started) * 1000
    else:
        questions = past[-1:]
    if ctx.prompt_config.get("keyword", False):
        questions[-1] = await keywords(llm, ctx.model, questions[-1])
    return questions, refine_ms


async def load_catalog(ctx: RunContext) -> list[CatalogDoc]:
    """Katalog dokumentów datasetów zapytania (K21 §3 p. 1); bez datasetów → [] (bez SQL).

    Ten sam zakres co retrieval — katalog nie wycieka dokumentów spoza `ctx.dataset_ids`.
    """
    if not ctx.dataset_ids:
        return []
    sessionmaker, _, _, _ = deps(ctx.container)
    async with transaction(sessionmaker) as session:
        return await document_profiles_repo.list_catalog(session, ctx.dataset_ids)


async def retrieve(
    ctx: RunContext, questions: list[str]
) -> tuple[int, list[RetrievedChunk], list[DocAgg], float]:
    """Retrieval przez czat (R0 p. 3): bez datasetów pusto; brak czatu (ask) → stałe upstream."""
    if not ctx.dataset_ids:
        return 0, [], [], 0.0
    started = time.perf_counter()
    if ctx.chat is None:  # /sessions/ask i completion wyszukiwarek: wartości ścieżki bez czatu
        cfg: RetrievalDefaults = ctx.retrieval or ASK_RETRIEVAL
        rerank_model = ctx.rerank_model
    else:
        cfg = RetrievalDefaults(
            page_size=ctx.chat.top_n,
            similarity_threshold=ctx.chat.similarity_threshold,
            vector_similarity_weight=ctx.chat.vector_similarity_weight,
            top_k=ctx.chat.top_k,
            rerank_candidates_count=ctx.chat.rerank_candidates_count,
        )
        rerank_model = ctx.chat.rerank_id or None
    result = await ctx.container.retrieval.retrieve_trusted(
        RetrievalQuery(
            question=questions[-1],
            dataset_ids=ctx.dataset_ids,
            document_ids=ctx.req.doc_ids,
            page=1,
            page_size=cfg.page_size,
            similarity_threshold=cfg.similarity_threshold,
            vector_similarity_weight=cfg.vector_similarity_weight,
            top_k=cfg.top_k,
            rerank_candidates_count=cfg.rerank_candidates_count,
            rerank_model=rerank_model,
            metadata_condition=ctx.metadata,
            meta_data_filter=ctx.meta_data_filter,
        )
    )
    elapsed = (time.perf_counter() - started) * 1000
    # Wzbogacanie metadanymi (upstream ``reference_metadata``) jest domyślnie WYŁĄCZONE, więc
    # ``document_metadata`` w chunku referencji i bloku wiedzy jest ``None`` — WD nie implementuje
    # jeszcze żądania wzbogacenia (dług E2-1), a ``_to_chunk`` populuje pole z ``meta_fields``
    # (K11 §10b p. 8, złoto ``metadata_e6--47``: ``document_metadata: null``).
    chunks = [
        replace(chunk, document_metadata=None) if chunk.document_metadata else chunk
        for chunk in result.chunks
    ]
    return result.total, chunks, result.doc_aggs, elapsed


async def posthoc(
    container: Container,
    ctx: RunContext,
    answer: str,
    chunks: Sequence[RetrievedChunk],
    w: float,
) -> tuple[str, set[int], float]:
    """Cytowania post-hoc (R0 p. 11): embed kawałków, wektor + token-similarity, place_citations."""
    pieces, eligible = answer_pieces(answer)
    if not chunks or not eligible:
        return "".join(pieces), set(), 0.0
    sessionmaker, llm, models, _ = deps(container)
    started = time.perf_counter()
    async with transaction(sessionmaker) as session:
        datasets = await retrieval_repo.get_datasets(session, ctx.dataset_ids)
    by_id = {d.id: d for d in datasets}
    ds0 = next(by_id[d] for d in ctx.dataset_ids if d in by_id)
    embedding_model = await models.resolve(ds0.embedding_model, "embedding")
    bind_ms = (time.perf_counter() - started) * 1000
    vecs = await llm.embed(embedding_model, [pieces[i] for i in eligible])
    chunk_ids = [c.chunk_id for c in chunks]
    chunk_token_sets = [chunk_terms(c.content_terms, "", "", "") for c in chunks]
    token_sims = [
        [
            term_similarity(
                prepare_query(pieces[piece_idx], stopwords=STOPWORDS, stem=stem_text), terms
            )
            for terms in chunk_token_sets
        ]
        for piece_idx in eligible
    ]
    async with transaction(sessionmaker) as session:
        vec_sims = []
        for vec in vecs:
            scores = await retrieval_repo.vector_scores(session, ds0.embedding_dim, vec, chunk_ids)
            vec_sims.append([scores.get(chunk_id, 0.0) for chunk_id in chunk_ids])
    sims = [
        hybrid_similarity(vrow, trow, tkweight=1 - w, vtweight=w)
        for vrow, trow in zip(vec_sims, token_sims, strict=True)
    ]
    result, cited = place_citations(pieces, eligible, sims)
    return result, cited, bind_ms


async def save_progress(
    ctx: RunContext,
    state: RunState,
    *,
    error_suffix: str | None,
) -> None:
    """Zapis sesji (K4 §3.4): user + assistant w jednej transakcji z blokadą wiersza sesji."""
    chat = ctx.chat
    if chat is None or not ctx.req.store_history_messages or ctx.session_id is None:
        return
    container = ctx.container
    sessionmaker, _, _, _ = deps(container)
    now_ms = container.clock.now_ms()
    content = state.save_content
    if error_suffix is not None:
        content += "**ERROR**: " + error_suffix
    reference = dict(state.final.reference) if state.final is not None else None
    async with transaction(sessionmaker) as session:
        await chat_sessions_repo.lock(session, ctx.session_id)
        seq = await chat_messages_repo.next_seq(session, ctx.session_id)
        await chat_messages_repo.insert(
            session,
            MessageRow(
                id=await user_message_id(session, ctx.req),
                session_id=ctx.session_id,
                seq=seq,
                role="user",
                content=str(ctx.req.messages[-1]["content"]),
                reference=None,
                prompt_tokens=None,
                completion_tokens=None,
                created_at=now_ms / 1000,
                create_time=now_ms,
            ),
        )
        await chat_messages_repo.insert(
            session,
            MessageRow(
                id=ctx.ids.message_id,
                session_id=ctx.session_id,
                seq=seq + 1,
                role="assistant",
                content=content,
                reference=reference,
                prompt_tokens=state.usage[0],
                completion_tokens=state.usage[1],
                created_at=now_ms / 1000,
                create_time=now_ms,
            ),
        )
        await chat_sessions_repo.bump(session, ctx.session_id, added=2, now_ms=now_ms)


async def user_message_id(session: AsyncSession, req: CompletionRequest) -> str:
    """Id wiadomości user (K4 §3.3): podane, krótkie, ASCII i wolne — inaczej nowe UUID4."""
    raw = req.messages[-1].get("id")
    if (
        isinstance(raw, str)
        and len(raw) <= MESSAGE_ID_MAX_LEN
        and raw.isascii()
        and not await chat_messages_repo.exists(session, raw)
    ):
        return raw
    return str(uuid.uuid4())
