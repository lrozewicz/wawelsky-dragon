"""Testy split_think (CONTRACT C2, K4 §1.3)."""

from collections.abc import AsyncIterator

from app.domain.chat.events import AnswerDelta, ThinkDelta, ThinkEnd, ThinkStart
from app.domain.chat.think import split_think

Split = ThinkStart | ThinkDelta | ThinkEnd | AnswerDelta


async def _run(
    pairs: list[tuple[bool, str]], *, min_tokens: int = 16
) -> list[ThinkStart | ThinkDelta | ThinkEnd | AnswerDelta]:
    """Konsumuje split_think na parach (is_reasoning, text), count_tokens=len."""

    async def stream() -> AsyncIterator[tuple[bool, str]]:
        for pair in pairs:
            yield pair

    events: list[Split] = [
        ev async for ev in split_think(stream(), count_tokens=len, min_tokens=min_tokens)
    ]
    return events


async def test_think_then_answer_buffered() -> None:
    events = await _run([(True, "a"), (True, "b"), (False, "x"), (False, "y")])
    assert events == [ThinkStart(), ThinkDelta("a"), ThinkDelta("b"), ThinkEnd(), AnswerDelta("xy")]


async def test_answer_emits_when_buffer_reaches_min_tokens() -> None:
    events = await _run([(False, "0123456789abcdef"), (False, "Z")])
    assert events == [AnswerDelta("0123456789abcdef"), AnswerDelta("Z")]


async def test_reasoning_after_text_flushes_buffer_then_think_start() -> None:
    events = await _run([(False, "ab"), (True, "t")])
    assert events == [AnswerDelta("ab"), ThinkStart(), ThinkDelta("t"), ThinkEnd()]


async def test_stream_ending_in_think_emits_think_end() -> None:
    events = await _run([(True, "t")])
    assert events == [ThinkStart(), ThinkDelta("t"), ThinkEnd()]


async def test_empty_texts_are_skipped() -> None:
    events = await _run([(True, ""), (True, "a"), (False, ""), (False, "b")])
    assert events == [ThinkStart(), ThinkDelta("a"), ThinkEnd(), AnswerDelta("b")]


async def test_all_empty_stream_yields_nothing() -> None:
    assert await _run([(True, ""), (False, "")]) == []
