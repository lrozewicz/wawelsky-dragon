"""Testy konfiguracji czatu: scalanie prompt_config i parametry generacji (brief T2)."""

from app.domain.chat.config import (
    DEFAULT_DIRECT_CHAT_PROMPT_CONFIG,
    DEFAULT_PROMPT_CONFIG,
    LLM_SETTING_FALLBACK,
    GenerationParams,
    generation_params,
    merge_prompt_config,
)

CHAT_SETTING = {"temperature": 0.5, "max_tokens": 512, "top_p_enabled": False, "top_p": 0.9}


def test_merge_prompt_config() -> None:
    merged = merge_prompt_config({"quote": False})
    assert merged["prologue"] == "Hi! I'm your assistant. What can I do for you?"
    assert merged["quote"] is False


def test_merge_prompt_config_defaults_untouched() -> None:
    merged = merge_prompt_config({})
    assert merged == dict(DEFAULT_PROMPT_CONFIG)
    assert merged is not DEFAULT_PROMPT_CONFIG
    assert DEFAULT_PROMPT_CONFIG["quote"] is True


def test_direct_chat_defaults() -> None:
    assert DEFAULT_DIRECT_CHAT_PROMPT_CONFIG["quote"] is False
    assert DEFAULT_DIRECT_CHAT_PROMPT_CONFIG["system"] == ""
    assert DEFAULT_DIRECT_CHAT_PROMPT_CONFIG["refine_multiturn"] is True


def test_llm_setting_fallback() -> None:
    assert LLM_SETTING_FALLBACK == {
        "temperature": 0.1,
        "top_p": 0.3,
        "frequency_penalty": 0.7,
        "presence_penalty": 0.4,
    }


def test_generation_params_full() -> None:
    params = generation_params(CHAT_SETTING, None, model_max_tokens=8192, used_tokens=8000)
    assert params == GenerationParams(
        temperature=0.5,
        top_p=None,
        max_tokens=192,
        extra={"frequency_penalty": 0.7, "presence_penalty": 0.4},
    )


def test_generation_params_no_max_tokens() -> None:
    params = generation_params({}, None, model_max_tokens=8192, used_tokens=0)
    assert params.max_tokens is None
    assert params.temperature == 0.1  # noqa: PLR2004 — fallback kontraktowy
    assert params.top_p == 0.3  # noqa: PLR2004 — fallback kontraktowy
    assert params.extra == {"frequency_penalty": 0.7, "presence_penalty": 0.4}


def test_generation_params_override_wins() -> None:
    params = generation_params(
        CHAT_SETTING, {"temperature": 0.9}, model_max_tokens=8192, used_tokens=8000
    )
    assert params.temperature == 0.9  # noqa: PLR2004 — wartość override


def test_generation_params_enabled_flags_skip_keys() -> None:
    params = generation_params(
        {"temperature_enabled": False, "presence_penalty_enabled": False},
        None,
        model_max_tokens=100,
        used_tokens=10,
    )
    assert params.temperature is None
    assert params.top_p == 0.3  # noqa: PLR2004 — fallback kontraktowy
    assert params.extra == {"frequency_penalty": 0.7}


def test_generation_params_max_tokens_disabled() -> None:
    params = generation_params(
        {"max_tokens": 512, "max_tokens_enabled": False},
        None,
        model_max_tokens=8192,
        used_tokens=0,
    )
    assert params.max_tokens is None
