"""Testy app.services.auto_metadata — schemat, prompt, parsowanie i scalanie (brief T4).

Przykłady wejście→wyjście z briefu T4 (SC-E6-1a-01/02/07) przepisane dosłownie.
"""

import pytest

from app.llm.errors import LLMUnavailable
from app.llm.types import ChatResult, ModelRef
from app.services.auto_metadata import (
    AutoMetadataError,
    extract_auto_metadata,
    merge_metadata,
    metadata_schema,
    parse_metadata,
    render_prompt,
)

MODEL = ModelRef(None, "fake-chat", "chat")

FIELDS: list[dict[str, object]] = [
    {"key": "rok", "type": "string", "description": "Rok, którego dotyczą dane"},
    {"key": "typ", "type": "string", "enum": ["raport", "rocznik", "ustawa"]},
]


class FakeGateway:
    """Atrapa LLMGateway: zwraca ``response`` albo rzuca wyjątek; zapisuje wywołania."""

    def __init__(self, response: str | Exception) -> None:
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
        self.calls.append({"model": model, "messages": messages, "cache": cache})
        if isinstance(self._response, Exception):
            raise self._response
        return ChatResult(
            text=self._response, reasoning=None, tokens_in=0, tokens_out=0, finish_reason="stop"
        )


# --- metadata_schema (K11 §10f p.4; brief T4 p. 1-3) ---


def test_schema_none_when_disabled() -> None:
    assert metadata_schema({"enable_metadata": False, "metadata": FIELDS}) is None


def test_schema_none_without_fields() -> None:
    assert metadata_schema({"enable_metadata": True}) is None


def test_schema_from_field_list() -> None:
    schema = metadata_schema({"enable_metadata": True, "metadata": FIELDS})
    assert schema is not None
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    props = schema["properties"]
    assert props["rok"] == {"type": "string", "description": "Rok, którego dotyczą dane"}
    assert props["typ"] == {"type": "string", "enum": ["raport", "rocznik", "ustawa"]}


def test_schema_type_mapping() -> None:
    fields = [
        {"key": "autorzy", "type": "list"},
        {"key": "data", "type": "time"},
        {"key": "stron", "type": "number"},
    ]
    schema = metadata_schema({"enable_metadata": True, "metadata": fields})
    assert schema is not None
    props = schema["properties"]
    assert props["autorzy"] == {"type": "array", "items": {"type": "string"}}
    assert props["data"] == {"type": "string"}
    assert props["stron"] == {"type": "number"}


def test_schema_accepts_ready_json_schema() -> None:
    ready = {"type": "object", "properties": {"rok": {"type": "string"}}}
    schema = metadata_schema({"enable_metadata": True, "metadata": ready})
    assert schema is not None
    assert schema["properties"]["rok"] == {"type": "string"}


def test_schema_merges_built_in_metadata() -> None:
    pc = {
        "enable_metadata": True,
        "metadata": FIELDS,
        "built_in_metadata": [{"key": "jezyk", "type": "string"}],
    }
    schema = metadata_schema(pc)
    assert schema is not None
    assert set(schema["properties"]) == {"rok", "typ", "jezyk"}


# --- render_prompt (nagłówki DOSŁOWNIE — fake-llm rozpoznaje po nich) ---


def test_render_prompt_headers_and_content() -> None:
    schema = {"type": "object", "properties": {"rok": {"type": "string"}}}
    out = render_prompt(schema, "rok: 2023")
    assert out.startswith("## Rola: specjalista od wyciągania metadanych.")
    assert "## Schemat wyciągu:" in out
    assert "## Treść dokumentu:" in out
    assert '"rok"' in out
    assert out.rstrip().endswith("rok: 2023")


# --- parse_metadata (brief T4: json.loads, ogrodzenia, pierwszy {…}; bez json_repair) ---


def test_parse_plain_json() -> None:
    assert parse_metadata('{"rok": "2023", "typ": "raport"}') == {"rok": "2023", "typ": "raport"}


def test_parse_fenced_json() -> None:
    assert parse_metadata('```json\n{"rok": "2023"}\n```') == {"rok": "2023"}


def test_parse_with_surrounding_text() -> None:
    assert parse_metadata('Oto wynik: {"rok": "2023"} — gotowe') == {"rok": "2023"}


def test_parse_non_json_returns_empty() -> None:
    assert parse_metadata("not a json") == {}


def test_parse_json_array_returns_empty() -> None:
    assert parse_metadata('["rok"]') == {}


# --- extract_auto_metadata ---


async def test_extract_returns_dict_and_uses_gateway() -> None:
    gateway = FakeGateway('{"rok": "2023", "typ": "raport"}')
    schema = metadata_schema({"enable_metadata": True, "metadata": FIELDS})
    assert schema is not None
    result = await extract_auto_metadata(gateway, MODEL, schema, ["rok: 2023", "typ: raport"])
    assert result == {"rok": "2023", "typ": "raport"}
    assert gateway.calls[0]["cache"] is True
    messages = gateway.calls[0]["messages"]
    assert messages[0]["role"] == "system"  # type: ignore[index]
    assert "rok: 2023\ntyp: raport" in messages[0]["content"]  # type: ignore[index]


async def test_extract_non_json_returns_empty() -> None:
    gateway = FakeGateway("not a json")
    assert await extract_auto_metadata(gateway, MODEL, {"properties": {}}, ["x"]) == {}


async def test_extract_model_error_wrapped() -> None:
    gateway = FakeGateway(LLMUnavailable("LLM server error"))
    with pytest.raises(AutoMetadataError):
        await extract_auto_metadata(gateway, MODEL, {"properties": {}}, ["x"])


# --- merge_metadata (SC-E6-1a-01/07) ---


def _schema() -> dict[str, object]:
    return {"type": "object", "properties": {"rok": {"type": "string"}, "typ": {"type": "string"}}}


def test_merge_adds_new_fields() -> None:
    merged, changed = merge_metadata({}, {"rok": "2023", "typ": "raport"}, _schema())
    assert merged == {"rok": "2023", "typ": "raport"}
    assert changed == 2  # noqa: PLR2004 — log `Auto metadata: 2 fields`


def test_merge_preserves_existing_keys() -> None:
    existing = {"wd_source": "x", "rok": "2020"}
    merged, changed = merge_metadata(existing, {"rok": "2023"}, _schema())
    assert merged == {"wd_source": "x", "rok": "2023"}
    assert changed == 1


def test_merge_empty_value_keeps_existing() -> None:
    merged, changed = merge_metadata({"rok": "2020"}, {"rok": ""}, _schema())
    assert merged == {"rok": "2020"}
    assert changed == 0


def test_merge_rejects_keys_outside_schema() -> None:
    merged, changed = merge_metadata({}, {"rok": "2023", "obcy": "x"}, _schema())
    assert merged == {"rok": "2023"}
    assert changed == 1


def test_merge_unknown_schema_ignores_everything() -> None:
    merged, changed = merge_metadata({"rok": "2020"}, {"rok": "2023"}, {"properties": {}})
    assert merged == {"rok": "2020"}
    assert changed == 0
