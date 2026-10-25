"""Testy app.services.enrich — renderowanie własnych promptów i parsowanie odpowiedzi (brief T5)."""

import asyncio

import pytest

from app.llm.errors import LLMUnavailable
from app.llm.types import ChatResult, ModelRef
from app.services.enrich import (
    KEYWORD_PROMPT,
    QUESTION_PROMPT,
    Enrichment,
    enrich_chunks,
    parse_keywords,
    parse_questions,
    render,
)
from app.worker.errors import TaskCancelled

MODEL = ModelRef(None, "fake-chat", "chat")

_KEYWORD_MARK = "extract keywords"  # fragment KEYWORD_PROMPT rozróżniający rodzaj wywołania
_QUESTION_MARK = "write questions"  # fragment QUESTION_PROMPT rozróżniający rodzaj wywołania


class FakeGateway:
    """Atrapa LLMGateway: odpowiedzi z list per rodzaj promptu, zapis wywołań i równoległości."""

    def __init__(self, *, delay_s: float = 0.0) -> None:
        self.keyword_responses: list[str | Exception] = []
        self.question_responses: list[str | Exception] = []
        self._delay_s = delay_s
        self.calls: list[dict[str, object]] = []
        self.active = 0
        self.max_active = 0

    async def chat(
        self,
        model: ModelRef,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        cache: bool = False,
    ) -> ChatResult:
        self.calls.append(
            {"model": model, "messages": messages, "temperature": temperature, "cache": cache}
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self._delay_s)
            prompt = messages[0]["content"]
            queue = self.keyword_responses if _KEYWORD_MARK in prompt else self.question_responses
            response: str | Exception = queue.pop(0) if queue else ""
            if isinstance(response, Exception):
                raise response
            return ChatResult(
                text=response, reasoning=None, tokens_in=0, tokens_out=0, finish_reason="stop"
            )
        finally:
            self.active -= 1


def _is_keyword_call(call: dict[str, object]) -> bool:
    messages = call["messages"]
    return _KEYWORD_MARK in messages[0]["content"]  # type: ignore[operator]


# --- render (przykłady z briefu T5) ---


def test_render_substitutes_topn_and_content() -> None:
    out = render(KEYWORD_PROMPT, topn=3, content="Ala {{ topn }}")
    assert "at most 3 keywords" in out
    assert out.endswith("Ala {{ topn }}")


def test_render_question_prompt_template() -> None:
    out = render(QUESTION_PROMPT, topn=2, content="Treść")
    assert out.startswith("## Instruction")
    assert "at most 2 questions" in out
    assert out.endswith("Treść")


# --- parse_keywords (przykłady z briefu T5) ---


def test_parse_keywords_dedup_and_fullwidth_comma() -> None:
    # pełna szerokość przecinka celowa — wejście dosłownie z przykładu w briefie
    assert parse_keywords("umowa, najem ,lokal，Umowa", 10) == [  # noqa: RUF001
        "umowa",
        "najem",
        "lokal",
    ]


def test_parse_keywords_think_prefix_and_topn() -> None:
    assert parse_keywords("<think>hmm</think>a, b, c", 2) == ["a", "b"]


def test_parse_keywords_error_marker() -> None:
    assert parse_keywords("**ERROR**: x", 5) == []


def test_parse_keywords_strips_quotes_and_dots() -> None:
    assert parse_keywords("\"umowa\", 'najem', \\\\lokal. ,.", 3) == ["umowa", "najem", "lokal"]


# --- parse_questions (przykłady z briefu T5) ---


def test_parse_questions_numbering_and_bullets() -> None:
    assert parse_questions("1. Co to jest?\n2) Kto?\n\n- Kiedy?\nco to jest?", 10) == [
        "Co to jest?",
        "Kto?",
        "Kiedy?",
    ]


def test_parse_questions_error_marker_and_topn() -> None:
    assert parse_questions("**ERROR**: x\na?\nb?", 1) == []


# --- enrich_chunks ---


async def test_enrich_chunks_keywords_and_questions() -> None:
    llm = FakeGateway()
    llm.keyword_responses = ["a, b"]
    llm.question_responses = ["Pytanie 1?\nPytanie 2?"]
    results, warnings = await enrich_chunks(
        llm, MODEL, ["tekst"], auto_keywords=2, auto_questions=1
    )
    assert results == [Enrichment(keywords=("a", "b"), questions=("Pytanie 1?",))]
    assert warnings == []
    assert len(llm.calls) == 2  # noqa: PLR2004 — jedno wywołanie na rodzaj
    for call in llm.calls:
        assert call["temperature"] == 0.2  # noqa: PLR2004 — wartość kontraktowa (C5)
        assert call["cache"] is True
        messages = call["messages"]
        assert messages[1] == {"role": "user", "content": "Output: "}  # type: ignore[index]
    kinds = [_is_keyword_call(call) for call in llm.calls]
    assert kinds == [True, False]


async def test_enrich_chunks_disabled_makes_no_calls() -> None:
    llm = FakeGateway()
    results, warnings = await enrich_chunks(
        llm, MODEL, ["a", "b"], auto_keywords=0, auto_questions=0
    )
    assert results == [Enrichment(), Enrichment()]
    assert warnings == []
    assert llm.calls == []


async def test_enrich_chunks_wd_error_only_one_kind_and_text() -> None:
    llm = FakeGateway()
    llm.keyword_responses = ["a", "c"]
    llm.question_responses = ["Q1?", LLMUnavailable("down")]
    results, warnings = await enrich_chunks(
        llm, MODEL, ["t0", "t1"], auto_keywords=1, auto_questions=1
    )
    assert results == [
        Enrichment(keywords=("a",), questions=("Q1?",)),
        Enrichment(keywords=("c",), questions=()),
    ]
    assert warnings == ["chunk 1: questions failed (LLMUnavailable)"]


async def test_enrich_chunks_wd_error_keywords_warning() -> None:
    llm = FakeGateway()
    llm.keyword_responses = [LLMUnavailable("kw-down")]
    llm.question_responses = ["Q1?"]
    results, warnings = await enrich_chunks(llm, MODEL, ["t0"], auto_keywords=1, auto_questions=1)
    assert results == [Enrichment(keywords=(), questions=("Q1?",))]
    assert warnings == ["chunk 0: keywords failed (LLMUnavailable)"]


async def test_enrich_chunks_questions_only_skips_keyword_calls() -> None:
    llm = FakeGateway()
    llm.question_responses = ["Q?"] * 2
    results, warnings = await enrich_chunks(
        llm, MODEL, ["a", "b"], auto_keywords=0, auto_questions=1
    )
    assert results == [Enrichment(questions=("Q?",)), Enrichment(questions=("Q?",))]
    assert warnings == []
    assert len(llm.calls) == 2  # noqa: PLR2004 — po jednym na tekst
    assert all(not _is_keyword_call(call) for call in llm.calls)


async def test_enrich_chunks_non_wd_error_propagates() -> None:
    llm = FakeGateway()
    llm.keyword_responses = [RuntimeError("boom")]
    with pytest.raises(RuntimeError):
        await enrich_chunks(llm, MODEL, ["t"], auto_keywords=1, auto_questions=0)


async def test_enrich_chunks_respects_concurrency() -> None:
    llm = FakeGateway(delay_s=0.01)
    llm.keyword_responses = ["k"] * 6
    results, warnings = await enrich_chunks(
        llm, MODEL, ["t"] * 6, auto_keywords=1, auto_questions=0, concurrency=2
    )
    assert results == [Enrichment(keywords=("k",))] * 6
    assert warnings == []
    assert llm.max_active <= 2  # noqa: PLR2004 — limit z concurrency=2


# --- check_cancel (brief T7, usterka U5 / DEC-255) ---


async def test_enrich_chunks_stops_on_cancel_between_calls() -> None:
    """check_cancel rzuca po 3. wywołaniu — przerwanie po kilku chunkach, nie po 50."""
    llm = FakeGateway(delay_s=0.05)
    calls = 0

    async def check_cancel() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:  # noqa: PLR2004 — po dwóch akceptacjach trzecie sprawdzenie anuluje
            raise TaskCancelled("t")

    with pytest.raises(TaskCancelled):
        await enrich_chunks(
            llm,
            MODEL,
            [f"tekst {i}" for i in range(50)],
            auto_keywords=1,
            auto_questions=0,
            concurrency=2,
            check_cancel=check_cancel,
        )
    assert len(llm.calls) < 10  # noqa: PLR2004 — anulowanie przerywa w kilka sekund, nie po 50


async def test_enrich_chunks_check_cancel_none_behaves_as_before() -> None:
    """Jawne check_cancel=None nie zmienia zachowania (jak istniejące testy bez argumentu)."""
    llm = FakeGateway()
    llm.keyword_responses = ["a, b"]
    results, warnings = await enrich_chunks(
        llm, MODEL, ["tekst"], auto_keywords=2, auto_questions=0, check_cancel=None
    )
    assert results == [Enrichment(keywords=("a", "b"))]
    assert warnings == []
