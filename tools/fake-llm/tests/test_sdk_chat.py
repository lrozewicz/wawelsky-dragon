"""Testy czatu przez prawdziwe SDK openai 3.x na httpx2 (C1 [R-1], K10 §4, C5)."""

import openai
import pytest

CHAT_MODEL = "fake-chat"
STREAM_USER_TEXT = "Jaka jest stolica?"
EXPECTED_CONTENT = "Odpowiedź testowa: Jaka jest stolica?"


async def test_sdk_chat_completion(sdk: openai.AsyncOpenAI) -> None:
    result = await sdk.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": STREAM_USER_TEXT}],
        stream=False,
    )
    assert result.choices[0].message.content == EXPECTED_CONTENT
    assert result.usage is not None
    assert result.usage.total_tokens > 0


async def test_sdk_chat_stream(sdk: openai.AsyncOpenAI) -> None:
    messages: list[dict[str, str]] = [{"role": "user", "content": STREAM_USER_TEXT}]
    stream = await sdk.chat.completions.create(model=CHAT_MODEL, messages=messages, stream=True)
    chunks = [chunk async for chunk in stream]
    joined = "".join(chunk.choices[0].delta.content or "" for chunk in chunks if chunk.choices)
    assert joined == EXPECTED_CONTENT
    assert chunks[-1].usage is not None


async def test_sdk_error_500(sdk: openai.AsyncOpenAI) -> None:
    with pytest.raises(openai.InternalServerError):
        await sdk.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": "x"}],
            extra_headers={"X-Fake-Scenario": "error_500"},
        )


async def test_sdk_error_429(sdk: openai.AsyncOpenAI) -> None:
    with pytest.raises(openai.RateLimitError):
        await sdk.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": "x"}],
            extra_headers={"X-Fake-Scenario": "error_429"},
        )
