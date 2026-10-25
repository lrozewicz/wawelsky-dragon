"""Testy app.services.meta_filter — prompt, parsowanie i generowanie (T3b E6-1a, K11 §10f p. 5).

Przykłady wejście→wyjście: prompty z liniami czytanymi przez fake-llm (K10 2026-10-11b),
odpowiedzi modelu (JSON, ogrodzenia, puste warunki) i zawężenie ``semi_auto``.
"""

from app.llm.types import ChatResult, ModelRef
from app.services.meta_filter import (
    available_metadata,
    generate_condition,
    parse_filter_response,
    render_filter_prompt,
)

MODEL = ModelRef(None, "fake-chat", "chat")

_METAS = {
    "doc-a": {"author": "A", "year": "2020", "topic": "rag"},
    "doc-b": {"author": "B", "year": "2021", "topic": "web"},
    "doc-c": {"author": "A", "year": "2022", "topic": "rag"},
}


class FakeGateway:
    """Atrapa LLMGateway: zwraca ``response``; zapisuje wywołania."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    async def chat(
        self,
        model: ModelRef,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        cache: bool = False,
    ) -> ChatResult:
        self.calls.append({"model": model, "messages": messages})
        return ChatResult(
            text=self._response, reasoning=None, tokens_in=0, tokens_out=0, finish_reason="stop"
        )


# --- available_metadata ---


def test_available_metadata_dedupes_and_keeps_first_order() -> None:
    assert available_metadata(_METAS) == {
        "author": ["A", "B"],
        "year": ["2020", "2021", "2022"],
        "topic": ["rag", "web"],
    }


def test_available_metadata_expands_lists_and_filters_keys() -> None:
    metas = {"d1": {"tag": ["x", "y"], "other": "z"}}
    assert available_metadata(metas) == {"tag": ["x", "y"], "other": ["z"]}
    assert available_metadata(metas, {"tag"}) == {"tag": ["x", "y"]}


# --- render_filter_prompt ---


def test_render_prompt_has_lines_read_by_fake_llm() -> None:
    available = {"author": ["A"], "year": ["2020"]}
    prompt = render_filter_prompt(available, "raporty z 2020")
    assert '- Dostępne klucze metadanych: {"author": ["A"], "year": ["2020"]}' in prompt
    assert '- Pytanie użytkownika: "raporty z 2020"' in prompt
    # Szablon jinja i placeholdery znikają (render ręczny).
    assert "{%" not in prompt
    assert "{{" not in prompt


def test_render_prompt_constraints_line_when_given() -> None:
    prompt = render_filter_prompt({"author": ["A"]}, "q", {"author": "="})
    assert '- Operator constraints: {"author": "="}' in prompt


# --- parse_filter_response ---


def test_parse_plain_json() -> None:
    text = '{"logic": "and", "conditions": [{"key": "author", "op": "=", "value": "A"}]}'
    condition = parse_filter_response(text)
    assert condition is not None
    assert condition.logic == "and"
    assert condition.conditions[0].name == "author"
    assert condition.conditions[0].op == "="
    assert condition.conditions[0].value == "A"


def test_parse_tolerates_fences_and_think() -> None:
    text = (
        '```json\n{"logic": "or", "conditions": [{"key": "year", "op": "=", "value": "2020"}]}\n```'
    )
    assert parse_filter_response(text) is not None


def test_parse_empty_conditions_is_none() -> None:
    assert parse_filter_response('{"logic": "and", "conditions": []}') is None


def test_parse_non_json_is_none() -> None:
    assert parse_filter_response("zwykły tekst, nie JSON") is None


def test_parse_invalid_condition_is_none() -> None:
    # Brak klucza "op" → całość odrzucona (brak zawężenia).
    assert parse_filter_response('{"conditions": [{"key": "author", "value": "A"}]}') is None


def test_parse_logic_defaults_to_and() -> None:
    condition = parse_filter_response('{"conditions": [{"key": "a", "op": "=", "value": "1"}]}')
    assert condition is not None
    assert condition.logic == "and"


# --- generate_condition ---


async def test_generate_manual_passthrough() -> None:
    spec = {
        "method": "manual",
        "manual": [{"key": "author", "op": "=", "value": "A"}],
    }
    condition = await generate_condition(FakeGateway("{}"), MODEL, _METAS, "q", spec)
    assert condition is not None
    assert condition.conditions[0].name == "author"


async def test_generate_auto_narrows_from_model() -> None:
    answer = '{"logic": "and", "conditions": [{"key": "author", "op": "=", "value": "A"}]}'
    gateway = FakeGateway(answer)
    condition = await generate_condition(gateway, MODEL, _METAS, "pokaż A", {"method": "auto"})
    assert condition is not None
    assert condition.conditions[0].value == "A"
    # Prompt zawiera wszystkie klucze i pytanie (fake-llm rozpoznaje po liniach).
    system = gateway.calls[0]["messages"][0]["content"]  # type: ignore[index]
    assert "- Dostępne klucze metadanych:" in system
    assert '- Pytanie użytkownika: "pokaż A"' in system


async def test_generate_auto_empty_conditions_no_narrowing() -> None:
    condition = await generate_condition(
        FakeGateway('{"logic": "and", "conditions": []}'), MODEL, _METAS, "q", {"method": "auto"}
    )
    assert condition is None


async def test_generate_semi_auto_limits_keys() -> None:
    answer = '{"logic": "and", "conditions": [{"key": "author", "op": "=", "value": "A"}]}'
    gateway = FakeGateway(answer)
    spec = {"method": "semi_auto", "semi_auto": ["author"]}
    condition = await generate_condition(gateway, MODEL, _METAS, "q", spec)
    assert condition is not None
    system = gateway.calls[0]["messages"][0]["content"]  # type: ignore[index]
    # Tylko klucz z `semi_auto` trafia do słownika w prompcie.
    assert '- Dostępne klucze metadanych: {"author": ["A", "B"]}' in system


async def test_generate_semi_auto_without_keys_is_none() -> None:
    condition = await generate_condition(
        FakeGateway("{}"), MODEL, _METAS, "q", {"method": "semi_auto", "semi_auto": []}
    )
    assert condition is None


async def test_generate_auto_without_metadata_is_none() -> None:
    gateway = FakeGateway("{}")
    condition = await generate_condition(gateway, MODEL, {}, "q", {"method": "auto"})
    assert condition is None
    assert gateway.calls == []  # brak metadanych → brak wywołania modelu
