"""Testy budowy korektora diakrytyków z ``parser_config`` (CONTRACT E5-H4b §4, DEC-249)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import NotFound
from app.llm.types import ModelRef
from app.parsing.diacritics_llm import LlmDiacriticsCorrector
from app.parsing.diacritics_stage import WORDFREQ_DEFAULT, StageCorrector
from app.services.ingest_diacritics import build_diacritics
from app.worker.errors import PermanentError

_CHAT = ModelRef(id="m1", name="gpt-5.4-mini", model_type="chat")


class FakeModelRegistry:
    """Atrapa ``ModelRegistry``: notuje wywołania ``resolve`` i zwraca zadany model albo błąd."""

    def __init__(self, *, result: ModelRef | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str | None, str]] = []
        self._result = result
        self._error = error

    async def resolve(self, ref: str | None, model_type: str) -> ModelRef:
        self.calls.append((ref, model_type))
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class FakeGateway:
    """Atrapa ``LLMGateway`` — w tych testach nigdy nie jest wołana."""


async def _build(
    pc: dict[str, Any],
    *,
    registry: FakeModelRegistry | None = None,
) -> Any:
    models = registry if registry is not None else FakeModelRegistry()
    return await build_diacritics(models, FakeGateway(), pc)  # type: ignore[arg-type]


async def test_missing_key_default_options() -> None:
    registry = FakeModelRegistry()
    corrector = await _build({}, registry=registry)
    assert isinstance(corrector, StageCorrector)
    assert corrector.options.layer is True
    assert corrector.options.wordfreq is WORDFREQ_DEFAULT
    assert corrector.options.llm is None
    assert registry.calls == []


async def test_none_value_default_options() -> None:
    registry = FakeModelRegistry()
    corrector = await _build({"diacritics": None}, registry=registry)
    assert isinstance(corrector, StageCorrector)
    assert corrector.options.layer is True
    assert corrector.options.wordfreq is WORDFREQ_DEFAULT
    assert registry.calls == []


async def test_flags_applied() -> None:
    registry = FakeModelRegistry()
    corrector = await _build({"diacritics": {"layer": False, "wordfreq": True}}, registry=registry)
    assert isinstance(corrector, StageCorrector)
    assert corrector.options.layer is False
    assert corrector.options.wordfreq is True
    assert corrector.options.llm is None
    assert registry.calls == []


async def test_none_flags_use_defaults() -> None:
    corrector = await _build({"diacritics": {"layer": None, "wordfreq": None}})
    assert isinstance(corrector, StageCorrector)
    assert corrector.options.layer is True
    assert corrector.options.wordfreq is WORDFREQ_DEFAULT


async def test_model_resolved_as_chat() -> None:
    registry = FakeModelRegistry(result=_CHAT)
    corrector = await _build({"diacritics": {"model": "gpt-5.4-mini"}}, registry=registry)
    assert isinstance(corrector, StageCorrector)
    assert isinstance(corrector.options.llm, LlmDiacriticsCorrector)
    assert corrector.options.llm.model == _CHAT
    assert registry.calls == [("gpt-5.4-mini", "chat")]


async def test_empty_model_does_not_resolve() -> None:
    registry = FakeModelRegistry()
    for model in ("", "   "):
        corrector = await _build({"diacritics": {"model": model}}, registry=registry)
        assert isinstance(corrector, StageCorrector)
        assert corrector.options.llm is None
    assert registry.calls == []


async def test_unknown_model_permanent_error() -> None:
    registry = FakeModelRegistry(error=NotFound("model not found: nieistnieje"))
    with pytest.raises(PermanentError) as excinfo:
        await _build({"diacritics": {"model": "nieistnieje"}}, registry=registry)
    assert str(excinfo.value) == "diacritics model not found: nieistnieje"
    assert registry.calls == [("nieistnieje", "chat")]


@pytest.mark.parametrize(
    ("pc", "key"),
    [
        ({"diacritics": "tak"}, "diacritics"),
        ({"diacritics": {"layer": "false"}}, "layer"),
        ({"diacritics": {"wordfreq": 1}}, "wordfreq"),
        ({"diacritics": {"model": 5}}, "model"),
    ],
)
async def test_invalid_types_permanent_error(pc: dict[str, Any], key: str) -> None:
    with pytest.raises(PermanentError) as excinfo:
        await _build(pc)
    assert str(excinfo.value) == f"invalid parser_config.diacritics: {key}"


async def test_unknown_keys_ignored() -> None:
    registry = FakeModelRegistry()
    corrector = await _build({"diacritics": {"nieznany": 1}}, registry=registry)
    assert isinstance(corrector, StageCorrector)
    assert corrector.options.layer is True
    assert corrector.options.wordfreq is WORDFREQ_DEFAULT
    assert corrector.options.llm is None
    assert registry.calls == []
