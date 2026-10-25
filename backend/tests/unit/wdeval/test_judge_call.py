"""Testy wywolania modelu-sedziego z cache'em — port z bety
(test_eval_judge_call.py) bez test_cache_key_matches_app_implementation
(wd nie ma odpowiednika app/services/llm/cache.py — kontrakt C5).

Wszystko na atrapach — bez sieci, bez bazy, bez importu ``app.*``.
"""

from __future__ import annotations

import pytest

import wdeval.judge as judge_module
from wdeval.judge import JudgeRunner, judge_cache_model_key, judge_extra_body
from wdeval.judge_prompt import VERDICT_KINDS

_PAYLOAD = {
    "question": "Jaka jest stolica Polski?",
    "context": "[Źródło 1] Warszawa jest stolicą Polski.",
    "answer": "Warszawa [1].",
}


class FakeChat:
    def __init__(self, response: str = "TAK") -> None:
        self.response = response
        self.calls: list[dict] = []

    async def __call__(self, model: str, messages: list[dict], **kwargs) -> str:
        self.calls.append({"model": model, "messages": messages, "kwargs": kwargs})
        return self.response

    @property
    def call_count(self) -> int:
        return len(self.calls)


class FakeCache:
    def __init__(self, hit: str | None = None) -> None:
        self.hit = hit
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str, str]] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.hit

    async def set(self, key: str, model: str, response: str) -> None:
        self.set_calls.append((key, model, response))


@pytest.mark.asyncio
async def test_no_cache_path_returns_parsed_verdict():
    chat = FakeChat("TAK")
    runner = JudgeRunner(model_name="qwen3.8-27b-nvfp4", chat=chat)

    verdict = await runner("grounded", _PAYLOAD)

    assert verdict.kind == "grounded"
    assert verdict.value is True
    assert chat.call_count == 1


@pytest.mark.asyncio
async def test_temperature_and_extra_body_reach_chat():
    chat = FakeChat("TAK")
    runner = JudgeRunner(model_name="qwen3.8-27b-nvfp4", chat=chat, mode="medium")

    await runner("grounded", _PAYLOAD)

    kwargs = chat.calls[0]["kwargs"]
    assert kwargs["temperature"] == 0
    assert kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "medium"},
        "reasoning_effort": "medium",
    }


@pytest.mark.asyncio
async def test_model_on_wire_is_model_name_not_alias():
    chat = FakeChat("TAK")
    runner = JudgeRunner(model_name="qwen3.8-27b-nvfp4", chat=chat, mode="medium")

    await runner("grounded", _PAYLOAD)

    assert chat.calls[0]["model"] == "qwen3.8-27b-nvfp4"


@pytest.mark.asyncio
async def test_think_wrapped_nie_then_tak_verdict_from_end():
    # Przykład z briefu T1 (doslownie): fake zwraca "<think>…NIE…</think>TAK" —
    # werdykt brany od konca PO usunieciu bloku <think>, jak w becie.
    chat = FakeChat("<think>rozumowanie zawiera NIE</think>TAK")
    runner = JudgeRunner(model_name="m", chat=chat, mode="medium")

    verdict = await runner("grounded", _PAYLOAD)

    assert verdict.kind == "grounded"
    assert verdict.value is True
    assert verdict.raw == "<think>rozumowanie zawiera NIE</think>TAK"


@pytest.mark.asyncio
async def test_cache_hit_skips_model_call():
    chat = FakeChat("TAK")
    cache = FakeCache(hit="NIE")
    runner = JudgeRunner(
        model_name="qwen3.8-27b-nvfp4",
        chat=chat,
        cache_get=cache.get,
        cache_set=cache.set,
    )

    verdict = await runner("grounded", _PAYLOAD)

    assert chat.call_count == 0
    assert verdict.value is False


@pytest.mark.asyncio
async def test_cache_miss_writes_raw_response_with_cache_model_key():
    chat = FakeChat("TAK")
    cache = FakeCache(hit=None)
    runner = JudgeRunner(
        model_name="qwen3.8-27b-nvfp4",
        chat=chat,
        mode="medium",
        cache_get=cache.get,
        cache_set=cache.set,
    )

    await runner("grounded", _PAYLOAD)

    assert len(cache.set_calls) == 1
    key, model, response = cache.set_calls[0]
    assert key == cache.get_calls[0]
    assert model == judge_cache_model_key("qwen3.8-27b-nvfp4", "medium")
    assert response == "TAK"


@pytest.mark.asyncio
async def test_key_depends_on_mode():
    cache_medium = FakeCache(hit="TAK")
    cache_low = FakeCache(hit="TAK")
    runner_medium = JudgeRunner(
        model_name="qwen3.8-27b-nvfp4",
        chat=FakeChat(),
        mode="medium",
        cache_get=cache_medium.get,
        cache_set=cache_medium.set,
    )
    runner_low = JudgeRunner(
        model_name="qwen3.8-27b-nvfp4",
        chat=FakeChat(),
        mode="low",
        cache_get=cache_low.get,
        cache_set=cache_low.set,
    )

    await runner_medium("grounded", _PAYLOAD)
    await runner_low("grounded", _PAYLOAD)

    assert cache_medium.get_calls[0] != cache_low.get_calls[0]


@pytest.mark.asyncio
async def test_judge_cache_model_key_depends_on_prompt_version(monkeypatch):
    key_v1 = judge_cache_model_key("qwen3.8-27b-nvfp4", "medium")
    assert f"#judge=v{judge_module.JUDGE_PROMPT_VERSION}" in key_v1

    cache = FakeCache(hit="TAK")
    runner = JudgeRunner(
        model_name="qwen3.8-27b-nvfp4",
        chat=FakeChat(),
        cache_get=cache.get,
        cache_set=cache.set,
    )
    await runner("grounded", _PAYLOAD)
    key_before = cache.get_calls[0]

    # judge.py importuje JUDGE_PROMPT_VERSION jako nazwę, więc trzeba
    # przełożyć monkeypatch tam, gdzie została zaimportowana — patchowanie
    # tylko wdeval.judge_prompt nie wystarczy, bo nazwa jest już związana.
    monkeypatch.setattr(judge_module, "JUDGE_PROMPT_VERSION", 999)
    key_v999 = judge_cache_model_key("qwen3.8-27b-nvfp4", "medium")
    assert key_v1 != key_v999
    assert "#judge=v999" in key_v999

    await runner("grounded", _PAYLOAD)
    key_after = cache.get_calls[1]

    assert key_before != key_after


@pytest.mark.asyncio
async def test_key_depends_on_payload_content():
    cache_a = FakeCache(hit="TAK")
    cache_b = FakeCache(hit="TAK")
    runner_a = JudgeRunner(
        model_name="qwen3.8-27b-nvfp4",
        chat=FakeChat(),
        cache_get=cache_a.get,
        cache_set=cache_a.set,
    )
    runner_b = JudgeRunner(
        model_name="qwen3.8-27b-nvfp4",
        chat=FakeChat(),
        cache_get=cache_b.get,
        cache_set=cache_b.set,
    )

    payload_a = dict(_PAYLOAD)
    payload_b = dict(_PAYLOAD, question="Jaka jest stolica Francji?")

    await runner_a("grounded", payload_a)
    await runner_b("grounded", payload_b)

    assert cache_a.get_calls[0] != cache_b.get_calls[0]


@pytest.mark.asyncio
async def test_think_block_response_parsed_and_raw_kept_full():
    raw_response = "<think>rozumowanie</think>\nTAK"
    chat = FakeChat(raw_response)
    runner = JudgeRunner(model_name="qwen3.8-27b-nvfp4", chat=chat)

    verdict = await runner("grounded", _PAYLOAD)

    assert verdict.value is True
    assert verdict.raw == raw_response


@pytest.mark.asyncio
async def test_unknown_kind_raises_value_error_without_calling_chat():
    chat = FakeChat("TAK")
    runner = JudgeRunner(model_name="qwen3.8-27b-nvfp4", chat=chat)

    with pytest.raises(ValueError):
        await runner("nieznany_rodzaj", _PAYLOAD)

    assert chat.call_count == 0


@pytest.mark.asyncio
async def test_without_cache_functions_calls_model_once():
    chat = FakeChat("TAK")
    runner = JudgeRunner(model_name="qwen3.8-27b-nvfp4", chat=chat, cache_get=None, cache_set=None)

    verdict = await runner("grounded", _PAYLOAD)

    assert chat.call_count == 1
    assert verdict.value is True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", VERDICT_KINDS)
async def test_all_verdict_kinds_go_through_full_path(kind):
    chat = FakeChat("TAK")
    runner = JudgeRunner(model_name="qwen3.8-27b-nvfp4", chat=chat)

    verdict = await runner(kind, _PAYLOAD)

    assert verdict.kind == kind
    assert verdict.value is True
    assert chat.call_count == 1


def test_judge_extra_body_shape():
    assert judge_extra_body("medium") == {
        "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "medium"},
        "reasoning_effort": "medium",
    }
    assert judge_extra_body("low") == {
        "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "low"},
        "reasoning_effort": "low",
    }


def test_judge_extra_body_openai_only_reasoning_effort():
    assert judge_extra_body("medium", "openai/gpt-5.4") == {"reasoning_effort": "medium"}


@pytest.mark.asyncio
async def test_openai_judge_sends_no_temperature_and_no_template_kwargs():
    chat = FakeChat("TAK")
    runner = JudgeRunner(model_name="openai/gpt-5.4", chat=chat)

    await runner("grounded", _PAYLOAD)

    kwargs = chat.calls[0]["kwargs"]
    assert kwargs["temperature"] is None
    assert kwargs["extra_body"] == {"reasoning_effort": "medium"}
