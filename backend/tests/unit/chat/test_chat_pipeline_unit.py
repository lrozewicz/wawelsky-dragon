"""Testy jednostkowe chat_pipeline i chat_steps — kroki czyste, LLM na atrapach (T4)."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.core.container import Container
from app.domain.chat.events import AnswerDelta, ThinkDelta, ThinkEnd, ThinkStart
from app.llm.types import ModelRef, ReasoningDelta, StreamEnd, StreamEvent, TextDelta
from app.services.chat import CompletionRequest, StreamIds
from app.services.chat_pipeline import (
    RunContext,
    RunState,
    _build_prompt,
    _empty_final,
    _reasoning_extra,
    _stream_answer,
)
from app.services.chat_steps import (
    chat_row,
    deps,
    history,
    iso_date,
    keywords,
    pick_questions,
    refine,
)
from tests.fakes.clock import FrozenClock

MODEL = ModelRef(None, "fake-chat", "chat")
FROZEN_MS = 1790157600000
_DEFAULT_MAX_TOKENS = 8192  # chat_pipeline: max_tokens modelu lub 8192

_FAKE_CONTAINER = SimpleNamespace(  # deps() wymaga niepustych zależności, bez I/O
    sessionmaker=object(),
    llm=object(),
    models=object(),
    settings=SimpleNamespace(expose_prompt=True, posthoc_citations=True),
    clock=FrozenClock(),
)


def _ids() -> StreamIds:
    return StreamIds(message_id="m1", session_id=None, chat_id=None)


def _ctx(**overrides: Any) -> RunContext:
    """RunContext dla kroków czystych; chat/solo domyślnie None."""
    values: dict[str, Any] = {
        "container": _FAKE_CONTAINER,
        "req": CompletionRequest(
            chat_id=None,
            session_id=None,
            messages=({"role": "user", "content": "pytanie?"},),
        ),
        "chat": None,
        "prompt_config": {},
        "model": MODEL,
        "dataset_ids": (),
        "session_id": None,
        "ids": _ids(),
        "metadata": None,
    }
    values.update(overrides)
    return RunContext(**values)


class FakeChatGateway:
    """Atrapa LLMGateway dla refine/keywords: kolejne odpowiedzi z listy."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[dict[str, str]]] = []

    async def chat(
        self,
        model: ModelRef,
        messages: Any,
        *,
        temperature: float | None = None,
        cache: bool = False,
    ) -> Any:
        self.calls.append([dict(m) for m in messages])
        return SimpleNamespace(text=self.responses.pop(0), reasoning=None)


class FakeStreamGateway:
    """Atrapa LLMGateway.chat_stream: sekwencja StreamEvent."""

    def __init__(self, events: list[StreamEvent]) -> None:
        self.events = events

    async def chat_stream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[StreamEvent]:
        for event in self.events:
            yield event


def test_deps_raises_without_start() -> None:
    """deps: kontener bez start() → RuntimeError."""
    with pytest.raises(RuntimeError, match="container not started"):
        deps(Container(Settings(env="test")))


def test_chat_row_raises_for_solo() -> None:
    """chat_row: solo (chat=None) → RuntimeError; z czatem → wiersz z kontekstu."""
    with pytest.raises(RuntimeError, match="chat datasets without a chat row"):
        chat_row(_ctx())
    row = object()
    assert chat_row(_ctx(chat=row)) is row  # type: ignore[arg-type]


async def test_history_pass_all_strips_leading_assistant_and_system() -> None:
    """history (pass_all): bez systemu i bez wiodących assistant."""
    req = CompletionRequest(
        chat_id=None,
        session_id=None,
        pass_all_history_messages=True,
        messages=(
            {"role": "assistant", "content": "<think>x</think>a1"},
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u2"},
        ),
    )
    rows = await history(object(), req, "s1")  # type: ignore[arg-type] — pass_all bez bazy
    # historia = req.messages[:-1] (bez bieżącego pytania), bez system i wiodących assistant
    assert rows == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a2"},
    ]


async def test_history_without_session_is_empty() -> None:
    """history: solo (bez sesji) → pusta lista bez SQL."""
    assert await history(object(), _ctx().req, None) == []  # type: ignore[arg-type]


def test_iso_date_offsets() -> None:
    assert iso_date(FROZEN_MS, 0) == "2026-09-23"
    assert iso_date(FROZEN_MS, -1) == "2026-09-22"
    assert iso_date(FROZEN_MS, 1) == "2026-09-24"


async def test_refine_returns_model_answer() -> None:
    """refine: odpowiedź modelu bez **ERROR** → jako pytanie; conversation w prompt system."""
    gateway = FakeChatGateway(["Poprawione pytanie?"])
    conversation = "USER: pierwsze?\nASSISTANT: a1\nUSER: pytanie?"
    result = await refine(gateway, MODEL, _ctx(), FROZEN_MS, conversation)  # type: ignore[arg-type]
    assert result == "Poprawione pytanie?"
    assert conversation in gateway.calls[0][0]["content"]  # pełny dialog trafia do promptu


async def test_refine_falls_back_on_error_marker() -> None:
    """refine: **ERROR** w odpowiedzi → ostatnie pytanie użytkownika."""
    gateway = FakeChatGateway(["**ERROR**: boom"])
    assert await refine(gateway, MODEL, _ctx(), FROZEN_MS, "USER: pytanie?") == "pytanie?"  # type: ignore[arg-type]


async def test_refine_falls_back_on_empty_answer() -> None:
    """refine: pusty wynik → ostatnie pytanie (C12)."""
    gateway = FakeChatGateway([""])
    assert await refine(gateway, MODEL, _ctx(), FROZEN_MS, "USER: pytanie?") == "pytanie?"  # type: ignore[arg-type]


async def test_keywords_appended_with_comma() -> None:
    """keywords: niepuste słowa kluczowe → "pytanie,kw1, kw2"."""
    gateway = FakeChatGateway(["smok, legenda"])
    result = await keywords(gateway, MODEL, "pytanie?")  # type: ignore[arg-type]
    assert result == "pytanie?,smok, legenda"


async def test_keywords_keep_question_when_empty() -> None:
    """keywords: pusty wynik → pytanie bez zmian."""
    gateway = FakeChatGateway([""])
    assert await keywords(gateway, MODEL, "pytanie?") == "pytanie?"  # type: ignore[arg-type]


async def test_pick_questions_single_turn_skips_refine() -> None:
    """Jedno pytanie user → bez refine, bez słów kluczowych."""
    gateway = FakeChatGateway([])
    questions, refine_ms = await pick_questions(gateway, _ctx(), [])  # type: ignore[arg-type]
    assert questions == ["pytanie?"]
    assert refine_ms == 0.0
    assert gateway.calls == []


async def test_pick_questions_multi_turn_refines() -> None:
    """≥ 2 pytania user i refine_multiturn → pełne pytanie z modelu."""
    ctx = _ctx(
        prompt_config={"refine_multiturn": True},
        req=CompletionRequest(
            chat_id=None,
            session_id=None,
            messages=(
                {"role": "user", "content": "pierwsze?"},
                {"role": "assistant", "content": "odpowiedź"},
                {"role": "user", "content": "pytanie?"},
            ),
        ),
    )
    gateway = FakeChatGateway(["pełne pytanie?"])
    rows = [{"role": "user", "content": "pierwsze?"}, {"role": "assistant", "content": "odpowiedź"}]
    questions, refine_ms = await pick_questions(gateway, ctx, rows)  # type: ignore[arg-type]
    assert questions == ["pełne pytanie?"]
    assert refine_ms >= 0.0


async def test_pick_questions_keyword_dialect() -> None:
    """prompt_config.keyword=True → dopisanie słów kluczowych przecinkiem."""
    ctx = _ctx(prompt_config={"keyword": True})
    gateway = FakeChatGateway(["smok"])
    questions, _ = await pick_questions(gateway, ctx, [])  # type: ignore[arg-type]
    assert questions == ["pytanie?,smok"]


def test_run_state_content_composition() -> None:
    """RunState: złożenie delty i myślenia; None gdy myślenie puste."""
    state = RunState()
    assert state.thinking_text is None
    state.thinking.append("myślę ")
    state.answer.append("odp")
    assert state.thinking_text == "myślę "
    assert state.save_content == "<think>myślę </think>odp"


def test_empty_final_with_and_without_prompt(tmp_path: Any) -> None:
    """empty_response: prompt wg expose_prompt; wartości K4 §1.4."""
    ctx = _ctx(prompt_config={"empty_response": "Brak <danych>"})
    final = _empty_final(ctx, ["pytanie?"])
    assert final.empty is True
    assert final.answer == "Brak &lt;danych&gt;"
    assert final.prompt == "\n\n### Query:\npytanie?"
    assert final.created_at is None
    container = SimpleNamespace(
        sessionmaker=object(),
        llm=object(),
        models=object(),
        settings=SimpleNamespace(expose_prompt=False),
        clock=FrozenClock(),
    )
    hidden = _empty_final(_ctx(container=container, prompt_config=ctx.prompt_config), ["pytanie?"])
    assert hidden.prompt == ""


def _reasoning_req(enabled: bool) -> CompletionRequest:
    """Żądanie z req.reasoning wg argumentu (pole CompletionRequest, nie RunContext)."""
    return CompletionRequest(
        chat_id=None,
        session_id=None,
        messages=({"role": "user", "content": "pytanie?"},),
        reasoning=enabled,
    )


def test_reasoning_extra_variants() -> None:
    """reasoning: extra wg supports_reasoning; brak wsparcia → bez zmian."""
    gen = SimpleNamespace(extra={"presence_penalty": 0.4})
    off = _reasoning_extra(_ctx(req=_reasoning_req(False)), gen)  # type: ignore[arg-type]
    assert off == {"presence_penalty": 0.4}
    effort = _reasoning_extra(
        _ctx(
            req=_reasoning_req(True),
            model=ModelRef(None, "m", "chat", extra={"supports_reasoning": "reasoning_effort"}),
        ),
        gen,  # type: ignore[arg-type]
    )
    assert effort["reasoning_effort"] == "medium"
    thinking = _reasoning_extra(
        _ctx(
            req=_reasoning_req(True),
            model=ModelRef(None, "m", "chat", extra={"supports_reasoning": "enable_thinking"}),
        ),
        gen,  # type: ignore[arg-type]
    )
    assert thinking["chat_template_kwargs"] == {"enable_thinking": True}


def test_build_prompt_appends_knowledge_and_budget() -> None:
    """build_prompt: system z blokami, ostatnia wiadomość user, budżet 0.95 max_tokens."""
    ctx = _ctx(
        prompt_config={"system": "Sys {knowledge}", "parameters": []},
        req=CompletionRequest(
            chat_id=None,
            session_id=None,
            messages=({"role": "user", "content": "pytanie?"},),
        ),
    )
    msgs, used_tokens, max_tokens, blocks = _build_prompt(ctx, [], [])
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "pytanie?"}
    assert used_tokens > 0
    assert max_tokens == _DEFAULT_MAX_TOKENS  # model bez max_tokens → domyślne
    assert blocks == []


async def test_stream_answer_splits_think_and_usage() -> None:
    """stream_answer: ReasoningDelta → myślenie, TextDelta → odpowiedź, StreamEnd → usage."""
    gateway = FakeStreamGateway(
        [
            ReasoningDelta(text="rozważam"),
            TextDelta(text="odpowiedź"),
            StreamEnd(tokens_in=11, tokens_out=7, finish_reason="stop"),
        ]
    )
    container = SimpleNamespace(**_FAKE_CONTAINER.__dict__)
    container.llm = gateway
    ctx = _ctx(container=container)
    state = RunState()
    gen = SimpleNamespace(temperature=None, top_p=None, max_tokens=None, extra={})
    deltas = [
        event
        async for event in _stream_answer(ctx, state, [], gen, {})  # type: ignore[arg-type]
    ]
    assert [type(d) for d in deltas] == [ThinkStart, ThinkDelta, ThinkEnd, AnswerDelta]
    assert deltas[1].text == "rozważam"
    assert deltas[3].text == "odpowiedź"
    assert state.thinking_text == "rozważam"
    assert state.answer_text == "odpowiedź"
    assert state.usage == (11, 7)
    assert state.generate_ms >= 0.0
