"""Testy typów modułu LLM (kontrakt C2, K5 §3.2)."""

import dataclasses

import pytest
from pydantic import SecretStr

from app.llm.types import ChatResult, ModelRef, ReasoningDelta, StreamEnd, TextDelta


def test_model_ref_extra_default_empty_dict() -> None:
    assert ModelRef(id=None, name="x", model_type="chat").extra == {}


def test_model_ref_extra_not_shared_between_instances() -> None:
    a = ModelRef(id=None, name="a", model_type="chat")
    b = ModelRef(id=None, name="b", model_type="chat")
    assert a.extra is not b.extra


def test_model_ref_defaults() -> None:
    ref = ModelRef(id="0197abcdef", name="qwen3", model_type="embedding")
    assert ref.base_url is None
    assert ref.api_key is None
    assert ref.dimension is None
    assert ref.max_tokens is None


def test_model_ref_full() -> None:
    ref = ModelRef(
        id="0197abcdef",
        name="qwen3",
        model_type="chat",
        base_url="http://fake:8000/v1",
        api_key=SecretStr("sk-x"),
        dimension=1024,
        max_tokens=4096,
        extra={"extra_body": {"temperature": 0}},
    )
    assert ref.api_key is not None
    assert ref.api_key.get_secret_value() == "sk-x"
    assert ref.extra == {"extra_body": {"temperature": 0}}


@pytest.mark.parametrize(
    "instance",
    [
        ModelRef(id=None, name="x", model_type="chat"),
        ChatResult(text="a", reasoning=None, tokens_in=1, tokens_out=2, finish_reason="stop"),
        TextDelta(text="a"),
        ReasoningDelta(text="r"),
        StreamEnd(tokens_in=1, tokens_out=2, finish_reason="stop"),
    ],
    ids=["ModelRef", "ChatResult", "TextDelta", "ReasoningDelta", "StreamEnd"],
)
def test_frozen_dataclasses(instance: object) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.text = "b"
