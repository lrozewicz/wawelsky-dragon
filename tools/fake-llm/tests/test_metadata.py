"""Testy promptów metadanych: auto-metadane i filtr (K10 „Poprawka 2026-10-11b")."""

import json
from typing import Any

import httpx

from fake_llm.answers import ChatMessage
from fake_llm.metadata import metadata_content

HTTP_OK = 200
CHAT_MODEL = "fake-chat"
VISION_MODEL = "fake-vision"

AUTO_HEADER = "## Rola: specjalista od wyciągania metadanych."
FILTER_HEADER = "Jesteś generatorem warunków filtrowania metadanych."
SCHEMA_HEADER = "## Schemat wyciągu:"
CONTENT_HEADER = "## Treść dokumentu:"
KEYS_PREFIX = "- Dostępne klucze metadanych:"
QUERY_PREFIX = "- Pytanie użytkownika:"

# Schemat jak z upstream `turn2jsonschema`: `typ` ma enum, `rok` zwykłe pole.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "typ": {"description": "", "enum": ["raport", "rocznik", "ustawa"], "type": "string"},
        "rok": {"description": ""},
    },
    "additionalProperties": False,
}


def _system(text: str) -> ChatMessage:
    return ChatMessage(role="system", content=text)


def _message(text: str) -> dict[str, Any]:
    return _system(text).model_dump()


def _auto_prompt(schema: dict[str, Any], content: str, render: str = "json") -> str:
    """Wiadomość system auto-metadanych; `render` = `json` (dumps) lub `repr` (upstream `str()`)."""
    schema_text = json.dumps(schema) if render == "json" else str(schema)
    return (
        AUTO_HEADER + "\n"
        "## Rules:\n - Output ONLY a valid JSON string. No Markdown, no notes.\n\n"
        f"{SCHEMA_HEADER}\n{schema_text}\n\n"
        f"{CONTENT_HEADER}\n{content}\n"
    )


def _filter_prompt(keys: dict[str, Any], query: str, constraints: bool = False) -> str:
    """Pełny kształt szablonu: sekcje przykładów PRZED `**Bieżące zadanie**`.

    Przykłady zawierają własne linie `- Pytanie użytkownika:` — właściwe pytanie jest dopiero
    na końcu.
    """
    lines = [
        FILTER_HEADER + ". Analyze the user's question and available document metadata.",
        "",
        "6. **Example A**:",
        f'{QUERY_PREFIX} "new products from July, not blue, only shoes and hats"',
        '- Metadata: { "color": {...}, "listing_date": {...} }',
        "",
        "7. **Example B**:",
        f'{QUERY_PREFIX} "It must be from China or India. Otherwise, it must not be blue or red."',
        '- Metadata: { "color": {...}, "country": {...} }',
        "",
        "**Bieżące zadanie**:",
        "- Today's date: 2026-10-11",
        f"{KEYS_PREFIX} {json.dumps(keys)}",
        f'{QUERY_PREFIX} "{query}"',
    ]
    if constraints:
        lines.append('- Operator constraints: {"rok": "="}')
    return "\n".join(lines)


def _auto_body(content: str, model: str = CHAT_MODEL, stream: bool = False) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            _message(_auto_prompt(SCHEMA, content)),
            {"role": "user", "content": "Output: "},
        ],
        "stream": stream,
    }


def _auto_answer(content: str) -> str:
    prompt = _auto_prompt(SCHEMA, content)
    answer = metadata_content([_system(prompt)])
    assert answer is not None
    return answer


# --- testy jednostkowe modułu `fake_llm.metadata` ---


def test_auto_enum_match_case_insensitive() -> None:
    assert _auto_answer("To jest Raport roczny") == '{"typ":"raport"}'


def test_auto_line_field_match() -> None:
    assert _auto_answer("rok: 2023\nTo jest ustawa") == '{"typ":"ustawa","rok":"2023"}'


def test_auto_no_match_empty_object() -> None:
    assert _auto_answer("Dowolny tekst bez danych") == "{}"


def test_auto_enum_word_boundary() -> None:
    """„raporty” nie trafia w enum `raport` (granice słów)."""
    assert _auto_answer("To są raporty roczne") == "{}"


def test_auto_schema_rendered_as_python_repr() -> None:
    """Upstream renderuje schemat przez `str()` — Python-literal, nie JSON."""
    prompt = _auto_prompt(SCHEMA, "To jest Raport roczny", render="repr")
    assert metadata_content([_system(prompt)]) == '{"typ":"raport"}'


def test_auto_invalid_marker() -> None:
    assert _auto_answer("To jest FAKE_METADATA_INVALID raport") == "not a json"


def test_filter_matches_value_word() -> None:
    keys = {"rok": ["2022", "2023"], "typ": ["raport"]}
    answer = metadata_content([_system(_filter_prompt(keys, "raporty z 2023"))])
    assert json.loads(answer or "") == {
        "logic": "and",
        "conditions": [{"key": "rok", "value": "2023", "op": "="}],
    }


def test_filter_uses_last_query_line_not_example() -> None:
    """Wartość obecna tylko w przykładowej linii `- Pytanie użytkownika:` nie trafia do warunków."""
    keys = {"kraj": ["china"], "rok": ["2023"]}
    # W przykładzie B jest "China", w pytaniu użytkownika nie ma — warunek `kraj` musi zniknąć.
    answer = metadata_content([_system(_filter_prompt(keys, "raport z 2023"))])
    assert json.loads(answer or "")["conditions"] == [{"key": "rok", "value": "2023", "op": "="}]


def test_filter_conditions_follow_dictionary_order() -> None:
    keys = {"rok": ["2023"], "typ": ["raport"]}
    answer = metadata_content([_system(_filter_prompt(keys, "raport z 2023"))])
    assert json.loads(answer or "")["conditions"] == [
        {"key": "rok", "value": "2023", "op": "="},
        {"key": "typ", "value": "raport", "op": "="},
    ]


def test_filter_word_boundary_excludes_raporty() -> None:
    """„raporty” NIE trafia w wartość `raport`, mimo że podciąg pasuje."""
    answer = metadata_content([_system(_filter_prompt({"typ": ["raport"]}, "raporty roczne"))])
    assert json.loads(answer or "") == {"logic": "and", "conditions": []}


def test_filter_no_match_empty_conditions() -> None:
    keys = {"rok": ["2022"], "typ": ["raport"]}
    answer = metadata_content([_system(_filter_prompt(keys, "nie wiem o co chodzi"))])
    assert json.loads(answer or "") == {"logic": "and", "conditions": []}


def test_filter_ignores_operator_constraints() -> None:
    keys = {"rok": ["2023"]}
    prompt = _filter_prompt(keys, "raport z 2023", constraints=True)
    answer = metadata_content([_system(prompt)])
    assert json.loads(answer or "")["conditions"] == [{"key": "rok", "value": "2023", "op": "="}]


def test_auto_invalid_schema_falls_back_to_empty() -> None:
    """Nieparsowalny schemat → `{}`, nie wyjątek (atrapa nie może paść 500)."""
    prompt = f"{AUTO_HEADER}\n\n{SCHEMA_HEADER}\nnot-json-at-all\n\n{CONTENT_HEADER}\nrok: 2023\n"
    assert metadata_content([_system(prompt)]) == "{}"


def test_auto_property_without_dict_spec() -> None:
    """Właściwość bez dict-opisu nie ma enum — trafienie idzie ścieżką linii treści."""
    schema = {"type": "object", "properties": {"rok": None}}
    prompt = _auto_prompt(schema, "rok: 2023")
    assert metadata_content([_system(prompt)]) == '{"rok":"2023"}'


def test_filter_without_keys_or_query() -> None:
    prompt = FILTER_HEADER + "\n**Bieżące zadanie**:\n"
    assert json.loads(metadata_content([_system(prompt)]) or "") == {
        "logic": "and",
        "conditions": [],
    }


def test_filter_skips_non_list_values() -> None:
    keys = {"rok": "2023", "typ": ["raport"]}
    answer = metadata_content([_system(_filter_prompt(keys, "raport z 2023"))])
    assert json.loads(answer or "")["conditions"] == [{"key": "typ", "value": "raport", "op": "="}]


def test_plain_prompt_is_not_metadata() -> None:
    assert metadata_content([_system("Kontekst:\nID: 1\ncokolwiek")]) is None
    assert metadata_content([_system("Inny prompt")]) is None


def test_non_system_message_ignored() -> None:
    prompt = _auto_prompt(SCHEMA, "To jest Raport roczny")
    assert metadata_content([ChatMessage(role="user", content=prompt)]) is None


# --- testy HTTP `POST /v1/chat/completions` ---


async def test_http_auto_metadata(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/chat/completions", json=_auto_body("To jest Raport roczny"))
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["choices"][0]["message"]["content"] == '{"typ":"raport"}'
    assert body["choices"][0]["finish_reason"] == "stop"


async def test_http_filter_metadata(client: httpx.AsyncClient) -> None:
    body = {
        "model": CHAT_MODEL,
        "messages": [
            _message(_filter_prompt({"rok": ["2023"]}, "raport z 2023")),
            {"role": "user", "content": "Generate filters:"},
        ],
    }
    response = await client.post("/v1/chat/completions", json=body)
    assert response.status_code == HTTP_OK
    content = json.loads(response.json()["choices"][0]["message"]["content"])
    assert content["conditions"] == [{"key": "rok", "value": "2023", "op": "="}]


async def test_http_metadata_wins_for_vision_model(client: httpx.AsyncClient) -> None:
    """Rozpoznanie przed scenariuszami czatu: prompt metadanych działa też dla `fake-vision`."""
    response = await client.post(
        "/v1/chat/completions", json=_auto_body("To jest Raport roczny", model=VISION_MODEL)
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == '{"typ":"raport"}'


async def test_http_metadata_stream(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_auto_body("To jest Raport roczny", stream=True)
    )
    assert response.status_code == HTTP_OK
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [frame for frame in response.text.split("\n\n") if frame]
    assert frames[-1] == "data: [DONE]"
    chunks = [json.loads(frame[len("data: ") :]) for frame in frames[:-1]]
    deltas = [chunk["choices"][0]["delta"].get("content", "") for chunk in chunks[1:-1]]
    assert "".join(deltas) == '{"typ":"raport"}'
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


async def test_http_metadata_counted_in_stats(client: httpx.AsyncClient) -> None:
    await client.post("/v1/fake/stats/reset")
    await client.post("/v1/chat/completions", json=_auto_body("To jest Raport roczny"))
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["chat_completions"]["fake-chat"] == 1


async def test_http_plain_chat_unaffected(client: httpx.AsyncClient) -> None:
    body = {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "Jaka jest stolica?"}]}
    response = await client.post("/v1/chat/completions", json=body)
    assert response.status_code == HTTP_OK
    assert (
        response.json()["choices"][0]["message"]["content"]
        == "Odpowiedź testowa: Jaka jest stolica?"
    )
