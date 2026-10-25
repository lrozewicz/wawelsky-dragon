"""Testy etapu LLM korekty diakrytyków (CONTRACT WP E5-H4b §3)."""

from __future__ import annotations

import json
import re

from app.llm.errors import LLMUnavailable
from app.llm.types import ChatResult, ModelRef
from app.parsing.diacritics_llm import (
    CHUNK_MAX_SEGMENTS,
    SYSTEM_PROMPT,
    LlmDiacriticsCorrector,
)

_MODEL = ModelRef(None, "fake-llm", "chat")
_TAG_RE = re.compile(r"<[^>]+>")

# Liczba segmentów w teście porcjowania (3 porcje po 40 + reszta).
_CHUNK_SEGMENTS = 100
# Liczba segmentów do dwóch porcji w teście tokenów.
_TOKEN_SEGMENTS = 41
# Długość segmentu w teście porcjowania (20 znaków, mieści się w CHUNK_MAX_CHARS).
_SEGMENT_LEN = 20
# Oczekiwana liczba wywołań: 100 segmentów / limit 40 na porcję = 3 porcje.
_CHUNK_CALLS_MIN = 3
# Oczekiwana liczba wywołań dla 41 segmentów (2 porcje) i sumy tokenów z obu odpowiedzi.
_TOKEN_CALLS = 2
_TOKENS_IN_TOTAL = 17
_TOKENS_OUT_TOTAL = 8


def _result(text: str, *, tokens_in: int = 0, tokens_out: int = 0) -> ChatResult:
    """Buduje :class:`ChatResult` z zadanym tekstem i zużyciem tokenów."""
    return ChatResult(
        text=text,
        reasoning=None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        finish_reason="stop",
    )


def _object(payload: dict[str, str], *, tokens_in: int = 0, tokens_out: int = 0) -> ChatResult:
    """Buduje odpowiedź modelu jako obiekt JSON ``{id: tekst}``."""
    return _result(
        json.dumps(payload, ensure_ascii=False), tokens_in=tokens_in, tokens_out=tokens_out
    )


class FakeGateway:
    """Atrapa ``LLMGateway.chat``: kolejne odpowiedzi z listy, zapis wszystkich kwargs.

    Rejestruje kwargs dosłownie, więc test może sprawdzić, że ``temperature``/``top_p``
    nie zostały przekazane w ogóle (zamiast tylko przyjąć wartość ``None``).
    """

    def __init__(self, responses: list[ChatResult | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def chat(
        self,
        model: ModelRef,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> ChatResult:
        self.calls.append({"model": model, "messages": messages, **kwargs})
        response = self._responses.pop(0) if self._responses else _result("{}")
        if isinstance(response, Exception):
            raise response
        return response


def _sent_payload(call: dict[str, object]) -> dict[str, str]:
    """Wyciąga obiekt JSON wysłany do modelu (treść wiadomości ``user``)."""
    messages = call["messages"]
    assert isinstance(messages, list)
    user = messages[1]
    assert isinstance(user, dict)
    content = user["content"]
    assert isinstance(content, str)
    parsed = json.loads(content)
    assert isinstance(parsed, dict)
    return parsed


async def test_accepts_valid_correction() -> None:
    gateway = FakeGateway([_object({"0": "Ogółem"})])
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    out = await corrector.correct("<td>Ogólem</td><td>10,8</td>", page=1)
    assert out == "<td>Ogółem</td><td>10,8</td>"
    assert corrector.rejections == []
    assert _sent_payload(gateway.calls[0]) == {"0": "Ogólem"}


async def test_rejects_changed_number() -> None:
    gateway = FakeGateway([_object({"0": "ogółem 11,8"})])
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    out = await corrector.correct("<td>ogólem 10,8</td>", page=3)
    assert out == "<td>ogólem 10,8</td>"
    assert corrector.rejections == ["page 3: diacritics chunk rejected (numbers)"]


async def test_bad_json_rejected() -> None:
    gateway = FakeGateway([_result("to nie json")])
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    out = await corrector.correct("<td>Ogólem</td>", page=2)
    assert out == "<td>Ogólem</td>"
    assert corrector.rejections == ["page 2: diacritics chunk rejected (missing)"]


async def test_gateway_error_rejected() -> None:
    gateway = FakeGateway([LLMUnavailable("brak modelu")])
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    out = await corrector.correct("<td>Ogólem</td>", page=4)
    assert out == "<td>Ogólem</td>"
    assert corrector.rejections == ["page 4: diacritics chunk rejected (llm_error)"]


async def test_numeric_segments_not_sent() -> None:
    gateway = FakeGateway([_object({"0": "x"})])
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    out = await corrector.correct("<td>10,8</td>", page=1)
    assert out == "<td>10,8</td>"
    assert gateway.calls == []
    assert corrector.rejections == []


async def test_chunking_limits() -> None:
    segments = [f"{'a' * (_SEGMENT_LEN - 2)}{index:02d}" for index in range(_CHUNK_SEGMENTS)]
    text = "".join(f"<td>{segment}</td>" for segment in segments)
    gateway = FakeGateway([])
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    out = await corrector.correct(text, page=1)
    assert out == text
    assert len(gateway.calls) >= _CHUNK_CALLS_MIN
    key_count = 0
    for call in gateway.calls:
        payload = _sent_payload(call)
        assert len(payload) <= CHUNK_MAX_SEGMENTS
        key_count += len(payload)
    assert key_count == _CHUNK_SEGMENTS


async def test_request_has_no_sampling_params() -> None:
    gateway = FakeGateway([_object({"0": "Ogółem"})])
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    await corrector.correct("<td>Ogólem</td>", page=1)
    call = gateway.calls[0]
    assert "temperature" not in call
    assert "top_p" not in call
    assert call["extra"] == {"response_format": {"type": "json_object"}}
    extra = call["extra"]
    assert isinstance(extra, dict)
    for key in ("presence_penalty", "frequency_penalty", "temperature"):
        assert key not in extra
    assert call["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"0": "Ogólem"}, ensure_ascii=False)},
    ]


async def test_tokens_accumulated() -> None:
    text = "".join(["<td>ogólem</td>"] * _TOKEN_SEGMENTS)
    gateway = FakeGateway(
        [
            _object({"0": "ogółem"}, tokens_in=10, tokens_out=5),
            _object({"0": "ogółem"}, tokens_in=7, tokens_out=3),
        ]
    )
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    await corrector.correct(text, page=1)
    assert len(gateway.calls) == _TOKEN_CALLS
    assert corrector.tokens_in == _TOKENS_IN_TOTAL
    assert corrector.tokens_out == _TOKENS_OUT_TOTAL


async def test_tags_preserved_bitwise() -> None:
    text = "<table><tr><td>Ogólem</td><td>10,8</td></tr></table>"
    gateway = FakeGateway([_object({"0": "Ogółem"})])
    corrector = LlmDiacriticsCorrector(gateway, _MODEL)
    out = await corrector.correct(text, page=1)
    assert out == "<table><tr><td>Ogółem</td><td>10,8</td></tr></table>"
    assert _TAG_RE.findall(out) == _TAG_RE.findall(text)
