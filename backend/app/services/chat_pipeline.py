"""Generator zdarzeń czatu (K4 §4, CONTRACT C12): orkiestracja pipeline i finalize.

Kolejność kroków jak 06 §5: historia + pytanie, refine, słowa kluczowe, retrieval,
pusta odpowiedź, bloki wiedzy, system, dopasowanie budżetu, strumień LLM przez
``split_think``, finalize (cytowania, referencja, tekst promptu) i zapis sesji.
Pojedyncze kroki (historia, refine, retrieval, post-hoc, zapis) — w ``chat_steps``.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from app.core.timeutil import from_ms
from app.domain.chat.citations import (
    api_key_hint,
    build_reference,
    find_citations,
    has_citation_marker,
    repair_citations,
)
from app.domain.chat.config import (
    ASK_RETRIEVAL,
    GenerationParams,
    RetrievalDefaults,
    generation_params,
)
from app.domain.chat.events import (
    AnswerDelta,
    ChatEvent,
    ErrorEvent,
    Final,
    ThinkDelta,
    error_message,
)
from app.domain.chat.kb_overview import (
    build_catalog_section,
    build_map_section,
    is_kb_overview_question,
)
from app.domain.chat.prompts import (
    Timings,
    build_kb_blocks,
    build_messages,
    build_prompt_text,
    build_system,
    citation_prompt,
    empty_prompt_text,
    fit_messages,
)
from app.domain.chat.think import split_think
from app.domain.retrieval.metadata import MetadataCondition
from app.domain.retrieval.types import RetrievedChunk
from app.llm.tokens import count_tokens, truncate_tokens
from app.llm.types import ModelRef, ReasoningDelta, StreamEnd, StreamEvent, TextDelta
from app.prompts import load_prompt
from app.services.chat_steps import (
    deps,
    history,
    load_catalog,
    pick_questions,
    posthoc,
    retrieve,
    save_progress,
)

if TYPE_CHECKING:
    from app.core.container import Container
    from app.db.repositories.chats import ChatRow
    from app.db.repositories.document_profiles import CatalogDoc
    from app.domain.chat.events import StreamIds
    from app.services.chat import CompletionRequest

logger = logging.getLogger(__name__)


@dataclass
class RunState:
    """Akumulacja strumienia: delty, usage, Final — do finalize, zapisu i complete_once."""

    answer: list[str] = field(default_factory=list)
    thinking: list[str] = field(default_factory=list)
    usage: tuple[int, int] = (0, 0)
    final: Final | None = None
    generate_ms: float = 0.0  # mierzone w _stream_answer (do Timings)

    @property
    def answer_text(self) -> str:
        """Surowa odpowiedź modelu: złożenie AnswerDelta (K4 §1.3)."""
        return "".join(self.answer)

    @property
    def thinking_text(self) -> str | None:
        """Złożone myślenie; None gdy puste (K4 §3.3)."""
        return "".join(self.thinking) or None

    @property
    def save_content(self) -> str:
        """Treść wiadomości asystenta do zapisu: "<think>T</think>A" gdy było myślenie."""
        answer = self.answer_text
        thinking = "".join(self.thinking)
        return f"<think>{thinking}</think>{answer}" if thinking else answer


@dataclass(frozen=True)
class RunContext:
    """Wszystko, czego pipeline potrzebuje po walidacji w ``DbChatService._prepare``."""

    container: Container
    req: CompletionRequest
    chat: ChatRow | None  # None = solo chat
    prompt_config: dict[str, Any]
    model: ModelRef
    dataset_ids: tuple[str, ...]
    session_id: str | None
    ids: StreamIds
    metadata: MetadataCondition | None
    # ``meta_data_filter`` czatu/wyszukiwarki z ``method: auto|semi_auto`` — warunki generuje
    # model w kroku retrievalu (K11 §10f p. 5); ``manual`` wchodzi przez ``metadata``.
    meta_data_filter: Mapping[str, Any] | None = None
    # Ścieżki bez czatu (completion wyszukiwarki, E4-4a §D7): parametry retrievalu i model
    # rerankera. ``None`` zachowuje dotychczasowe zachowanie (``ASK_RETRIEVAL``, bez rerankera).
    retrieval: RetrievalDefaults | None = None
    rerank_model: str | None = None


def safe_events(ctx: RunContext) -> AsyncIterator[ChatEvent]:
    """Strumień dla ``start`` (K4 §3.3): błąd → log + ErrorEvent, nic nie rzuca poza anulowaniem."""
    state = RunState()

    async def gen() -> AsyncIterator[ChatEvent]:
        try:
            async for event in run_events(ctx, state):
                yield event
        except (GeneratorExit, asyncio.CancelledError):
            raise
        except BaseException as exc:  # rzuca tylko zapis w run_events — tu zamieniamy na zdarzenie
            logger.exception("chat_stream_failed")
            yield ErrorEvent(error_message(exc))

    return gen()


async def run_events(ctx: RunContext, state: RunState) -> AsyncIterator[ChatEvent]:
    """Surowy pipeline (complete_once iteruje bez ErrorEvent); zapis przy błędzie/anulowaniu."""
    try:
        async for event in _pipeline(ctx, state):
            yield event
    except (GeneratorExit, asyncio.CancelledError):
        await save_progress(ctx, state, error_suffix=None)
        raise
    except BaseException as exc:
        await save_progress(ctx, state, error_suffix=error_message(exc))
        raise


def _empty_final(ctx: RunContext, questions: list[str]) -> Final:
    """Zdarzenie pustej odpowiedzi (K4 §1.4); expose_prompt=false → prompt "" (R0 p. 5)."""
    _, _, _, settings = deps(ctx.container)
    escaped = html.escape(str(ctx.prompt_config.get("empty_response") or ""))
    return Final(
        answer=escaped,
        reference={"total": 0, "chunks": [], "doc_aggs": []},
        prompt=empty_prompt_text(questions) if settings.expose_prompt else "",
        created_at=None,
        final_answer=escaped,
        thinking=None,
        usage=(0, 0),
        empty=True,
    )


def _build_prompt(
    ctx: RunContext,
    history_rows: list[dict[str, Any]],
    chunks: list[RetrievedChunk],
    section: str = "",
) -> tuple[list[dict[str, str]], int, int, list[str]]:
    """Bloki wiedzy, system, wiadomości i budżet; zwraca (msgs, used_tokens, model_max, blocks).

    Tokeny sekcji katalogu/mapy (K21 §3 p. 5) są rezerwowane w budżecie (95 % `max_tokens`).
    """
    max_tokens = ctx.model.max_tokens or 8192
    blocks = build_kb_blocks(chunks, max_tokens, count_tokens=count_tokens)
    system = build_system(
        str(ctx.prompt_config["system"]),
        blocks,
        ctx.prompt_config.get("parameters", []),
        {"date": from_ms(ctx.container.clock.now_ms()).strftime("%Y-%m-%d %H:%M:%S")},
    )
    msgs = build_messages(system, history_rows)
    msgs.append({"role": "user", "content": str(ctx.req.messages[-1]["content"])})
    budget = int(max_tokens * 0.95)
    reserve = count_tokens(section) if section else 0
    used_tokens, msgs = fit_messages(
        msgs, max(0, budget - reserve), count_tokens=count_tokens, truncate_tokens=truncate_tokens
    )
    return msgs, used_tokens + reserve, max_tokens, blocks


def _kb_section(
    catalog: list[CatalogDoc],
    *,
    kb_overview: bool,
    catalog_tokens: int,
    map_tokens: int,
    model_max_tokens: int,
) -> str:
    """Mapa przy pytaniu o bazę (limit `min(map_tokens, 0.3 * max_tokens modelu)`, K21 §4 p. 2),
    inaczej katalog (K21 §3)."""
    if not catalog:
        return ""
    if kb_overview and map_tokens > 0:
        limit = min(map_tokens, int(model_max_tokens * 0.3))
        return build_map_section(catalog, max_tokens=limit, count_tokens=count_tokens)
    return build_catalog_section(catalog, max_tokens=catalog_tokens, count_tokens=count_tokens)


def _reasoning_extra(ctx: RunContext, gen: GenerationParams) -> dict[str, Any]:
    """Extra LLM wg models.extra.supports_reasoning (06 §8; brak wsparcia → ignorowane)."""
    extra: dict[str, Any] = dict(gen.extra)
    if not ctx.req.reasoning:
        return extra
    mode = ctx.model.extra.get("supports_reasoning")
    if mode == "reasoning_effort":
        extra["reasoning_effort"] = "medium"
    elif mode == "enable_thinking":
        extra["chat_template_kwargs"] = {"enable_thinking": True}
    return extra


async def _stream_answer(
    ctx: RunContext,
    state: RunState,
    llm_messages: list[dict[str, str]],
    gen: GenerationParams,
    extra: dict[str, Any],
) -> AsyncIterator[ChatEvent]:
    """Strumień LLM → adapter par → split_think → delty; mierzy czas generowania w state."""
    _, llm, _, _ = deps(ctx.container)
    started = time.perf_counter()
    # bramka zwraca w runtime async generator; typ portu deklaruje sam AsyncIterator (K5 §3.3)
    stream = cast(
        AsyncGenerator[StreamEvent],
        llm.chat_stream(
            ctx.model,
            llm_messages,
            temperature=gen.temperature,
            top_p=gen.top_p,
            max_tokens=gen.max_tokens,
            extra=extra or None,
        ),
    )
    async with contextlib.aclosing(stream) as events:

        async def pairs() -> AsyncIterator[tuple[bool, str]]:
            """Adapter StreamEvent → pary (is_reasoning, text); StreamEnd → usage (R0 p. 1)."""
            async for event in events:
                if isinstance(event, ReasoningDelta):
                    yield (True, event.text)
                elif isinstance(event, TextDelta):
                    yield (False, event.text)
                elif isinstance(event, StreamEnd):
                    state.usage = (event.tokens_in, event.tokens_out)

        async for delta in split_think(pairs(), count_tokens=count_tokens):
            if isinstance(delta, ThinkDelta):
                state.thinking.append(delta.text)
            elif isinstance(delta, AnswerDelta):
                state.answer.append(delta.text)
            yield delta
    state.generate_ms = (time.perf_counter() - started) * 1000


async def _cited_answer(
    ctx: RunContext, answer: str, with_citations: bool, chunks: list[RetrievedChunk]
) -> tuple[str, set[int], float]:
    """Finalize cytowań (DS decorate_answer): post-hoc/find, repair, api_key_hint."""
    _, _, _, settings = deps(ctx.container)
    bind_ms = 0.0
    cited: set[int] = set()
    if with_citations:
        if not has_citation_marker(answer) and settings.posthoc_citations:
            # Brak czatu (ask) → waga wektorowa z stałych upstream async_ask (C4).
            weight = (
                ctx.chat.vector_similarity_weight
                if ctx.chat is not None
                else ASK_RETRIEVAL.vector_similarity_weight
            )
            answer, cited, bind_ms = await posthoc(ctx.container, ctx, answer, chunks, weight)
        else:
            cited = find_citations(answer, len(chunks))
        answer, cited = repair_citations(answer, len(chunks), cited)
    return api_key_hint(answer), cited, bind_ms


async def _pipeline(ctx: RunContext, state: RunState) -> AsyncIterator[ChatEvent]:
    """Algorytm K4 §4 krok po kroku; zapis sesji w ścieżkach empty i Final (K4 §3.4)."""
    container = ctx.container
    sessionmaker, llm, _, settings = deps(container)
    started = time.perf_counter()
    # Sekcja katalogu/mapy dotyczy wyłącznie czatu (K21 §4 p. 5). `/sessions/ask` i completion
    # wyszukiwarki (Search) idą tym samym pipeline bez wiersza czatu (`chat=None`) — bez sekcji.
    chat_paths = ctx.chat is not None
    # Rozpoznanie pytania o bazę na SUROWYM ostatnim pytaniu, PRZED refine (K21 §4 p. 1).
    kb_overview = chat_paths and is_kb_overview_question(str(ctx.req.messages[-1]["content"]))
    catalog = await load_catalog(ctx) if chat_paths else []
    history_rows = await history(sessionmaker, ctx.req, ctx.session_id)
    questions, refine_ms = await pick_questions(llm, ctx, history_rows)
    total, chunks, doc_aggs, retrieval_ms = await retrieve(ctx, questions)
    # Przy pytaniu o bazę skrót `empty_response` nie obowiązuje, gdy mapa ma ≥ 1 dokument
    # (K21 §4 p. 3); przy wyłączonej mapie (`0`) pytanie idzie zwykłą ścieżką (K21 §4 p. 4).
    map_present = kb_overview and settings.chat_kb_map_tokens > 0 and bool(catalog)
    if (
        ctx.dataset_ids
        and not chunks
        and ctx.prompt_config.get("empty_response")
        and not map_present
    ):
        final = _empty_final(ctx, questions)
        state.final = final
        # C1 (WP E5-H6e): tekst empty_response jest odpowiedzią asystenta w sesji (K4 §3.4).
        state.answer.append(final.answer)
        yield final
        await save_progress(ctx, state, error_suffix=None)
        return
    max_tokens = ctx.model.max_tokens or 8192
    section = _kb_section(
        catalog,
        kb_overview=kb_overview,
        catalog_tokens=settings.chat_kb_catalog_tokens,
        map_tokens=settings.chat_kb_map_tokens,
        model_max_tokens=max_tokens,
    )
    msgs, used_tokens, max_tokens, blocks = _build_prompt(ctx, history_rows, chunks, section)
    quote = bool(ctx.prompt_config.get("quote", True)) and ctx.req.quote
    # Sekcja katalogu/mapy na KOŃCU wiadomości systemowej, po citation_prompt (K21 §3 p. 2);
    # do pola `prompt` wchodzi bez citation_prompt (jak dotąd — numeracja ID: n bez zmian).
    prompt_system = msgs[0]["content"] + (("\n\n" + section) if section else "")
    llm_messages = list(msgs)
    if quote and blocks:
        llm_messages[0] = {
            "role": "system",
            "content": msgs[0]["content"] + citation_prompt(load_prompt("citation_prompt")),
        }
    if section:
        llm_messages[0] = {
            "role": "system",
            "content": llm_messages[0]["content"] + "\n\n" + section,
        }
    gen = generation_params(
        ctx.chat.llm_setting if ctx.chat is not None else {},
        ctx.req.llm_setting,
        model_max_tokens=max_tokens,
        used_tokens=used_tokens,
    )
    async for delta in _stream_answer(ctx, state, llm_messages, gen, _reasoning_extra(ctx, gen)):
        yield delta
    answer = state.answer_text
    thinking = state.thinking_text
    if not answer and not thinking:
        await save_progress(ctx, state, error_suffix=None)
        return
    answer, cited, bind_ms = await _cited_answer(ctx, answer, quote and bool(blocks), chunks)
    reference = (
        build_reference(chunks, doc_aggs, total, cited) if quote and blocks else {"chunks": []}
    )
    prompt = ""
    if settings.expose_prompt:
        timings = Timings(
            total_ms=(time.perf_counter() - started) * 1000,
            # resolve modelu czatu dzieje się w start (przed strumieniem) — pomiar 0.0
            check_llm_ms=0.0,
            bind_models_ms=bind_ms,
            refine_ms=refine_ms,
            retrieval_ms=retrieval_ms,
            generate_ms=state.generate_ms,
        )
        prompt = build_prompt_text(
            prompt_system, questions, timings, count_tokens((thinking or "") + answer)
        )
    final = Final(
        answer="",
        reference=reference,
        prompt=prompt,
        created_at=container.clock.now_ms() / 1000,
        final_answer=answer,
        thinking=thinking,
        usage=state.usage,
        empty=False,
    )
    state.final = final
    yield final
    await save_progress(ctx, state, error_suffix=None)
