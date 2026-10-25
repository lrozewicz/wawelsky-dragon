"""Testy `tools`/`tool_calls` — wiersz tabeli briefu = test (K10 „Poprawka 2026-10-11c", C5)."""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from fake_llm import stats

HTTP_OK = 200
CHAT_MODEL = "fake-chat"
COMPLETION_ID = "chatcmpl-fake"
CHUNK_CHARS = 5
TOOL_CONTENT_LIMIT = 200
LEGACY_PREFIX = "Odpowiedź testowa: "
TOOLS_PREFIX = "Na podstawie narzędzi: "
ALL_TOOLS_CALLS = 2

_SEARCH = {
    "type": "function",
    "function": {
        "name": "search",
        "description": "wyszukiwanie w sieci",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
}
_OTHER = {
    "type": "function",
    "function": {
        "name": "other",
        "description": "inne narzędzie",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
}
TOOLS = [_SEARCH, _OTHER]
QUERY = "znajdź kota"


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Zeruje liczniki przed i po każdym teście (stan modułowy, też licznik `call_fake_<n>`)."""
    stats.reset()
    yield
    stats.reset()


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _body(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = TOOLS,
    stream: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {"model": CHAT_MODEL, "messages": messages, "stream": stream}
    if tools is not None:
        body["tools"] = tools
    return body


def _choice(response: httpx.Response) -> dict[str, Any]:
    return response.json()["choices"][0]


def _calls(response: httpx.Response) -> list[dict[str, Any]]:
    return _choice(response)["message"]["tool_calls"]


def _chunks(response: httpx.Response) -> list[dict[str, Any]]:
    frames = [frame for frame in response.text.split("\n\n") if frame]
    assert frames[-1] == "data: [DONE]"
    return [json.loads(frame[len("data: ") :]) for frame in frames[:-1]]


async def test_tools_emit_first_tool_call(client: httpx.AsyncClient) -> None:
    """`tools` bez znacznika → jedno wywołanie pierwszego narzędzia, `finish_reason=tool_calls`."""
    response = await client.post("/v1/chat/completions", json=_body([_user(QUERY)]))
    assert response.status_code == HTTP_OK
    choice = _choice(response)
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] is None
    calls = choice["message"]["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["id"] == "call_fake_1"
    assert calls[0]["type"] == "function"
    assert calls[0]["function"]["name"] == "search"
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": QUERY}


async def test_tool_marker_selects_named_tool_without_marker_in_query(
    client: httpx.AsyncClient,
) -> None:
    """Znacznik `[[tool:other]]` wybiera `other`, a `query` nie zawiera znacznika."""
    text = f"{QUERY} [[tool:other]]"
    response = await client.post("/v1/chat/completions", json=_body([_user(text)]))
    assert response.status_code == HTTP_OK
    calls = _calls(response)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "other"
    assert json.loads(calls[0]["function"]["arguments"]) == {"query": QUERY}


async def test_tools_all_marker_emits_every_tool_in_order(client: httpx.AsyncClient) -> None:
    """`[[tools:all]]` → jedno wywołanie każdego narzędzia w kolejności listy."""
    text = f"{QUERY} [[tools:all]]"
    response = await client.post("/v1/chat/completions", json=_body([_user(text)]))
    assert response.status_code == HTTP_OK
    calls = _calls(response)
    assert [call["function"]["name"] for call in calls] == ["search", "other"]
    assert [call["id"] for call in calls] == ["call_fake_1", "call_fake_2"]
    for call in calls:
        assert json.loads(call["function"]["arguments"]) == {"query": QUERY}


async def test_tool_role_message_produces_final_answer(client: httpx.AsyncClient) -> None:
    """Wiadomość `role: tool` po ostatniej `user` → `stop` i treść z `tool_call_id`."""
    messages = [
        _user(QUERY),
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_fake_1"}]},
        {"role": "tool", "tool_call_id": "call_fake_1", "content": "Kot jest w ogrodzie"},
    ]
    response = await client.post("/v1/chat/completions", json=_body(messages))
    assert response.status_code == HTTP_OK
    choice = _choice(response)
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == (f"{TOOLS_PREFIX}[call_fake_1] Kot jest w ogrodzie")


async def test_multiple_tool_messages_joined_and_truncated(client: httpx.AsyncClient) -> None:
    """Wiele wiadomości `tool` rozdzielone `; `, content przycięty do 200 znaków."""
    long_content = "x" * (TOOL_CONTENT_LIMIT + 50)
    messages = [
        _user(QUERY),
        {"role": "tool", "tool_call_id": "call_fake_1", "content": "pierwsza"},
        {"role": "tool", "tool_call_id": "call_fake_2", "content": long_content},
    ]
    response = await client.post("/v1/chat/completions", json=_body(messages))
    assert response.status_code == HTTP_OK
    content = _choice(response)["message"]["content"]
    assert content == (
        f"{TOOLS_PREFIX}[call_fake_1] pierwsza; [call_fake_2] {'x' * TOOL_CONTENT_LIMIT}"
    )


async def test_tool_messages_before_last_user_ignored(client: httpx.AsyncClient) -> None:
    """Wiadomość `tool` przed ostatnią `user` nie liczy się → nadal wywołanie narzędzia."""
    messages = [
        _user("stare pytanie"),
        {"role": "tool", "tool_call_id": "call_fake_0", "content": "stara odpowiedź"},
        _user(QUERY),
    ]
    response = await client.post("/v1/chat/completions", json=_body(messages))
    assert response.status_code == HTTP_OK
    assert _choice(response)["finish_reason"] == "tool_calls"


async def test_no_tool_marker_keeps_legacy_behaviour(client: httpx.AsyncClient) -> None:
    """`[[no-tool]]` → zachowanie dotychczasowe (zwykła odpowiedź czatu)."""
    text = "pytanie [[no-tool]]"
    response = await client.post("/v1/chat/completions", json=_body([_user(text)]))
    assert response.status_code == HTTP_OK
    choice = _choice(response)
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == LEGACY_PREFIX + text
    assert "tool_calls" not in choice["message"]


async def test_missing_or_empty_tools_keep_legacy_behaviour(client: httpx.AsyncClient) -> None:
    """Brak `tools` albo pusta lista → zachowanie dotychczasowe."""
    for tools in (None, []):
        json_body = _body([_user(QUERY)], tools=tools)
        response = await client.post("/v1/chat/completions", json=json_body)
        assert response.status_code == HTTP_OK
        choice = _choice(response)
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["content"] == LEGACY_PREFIX + QUERY


async def test_usage_present_for_tool_calls(client: httpx.AsyncClient) -> None:
    """`usage` obecne i spójne jak w zwykłym czacie."""
    response = await client.post("/v1/chat/completions", json=_body([_user(QUERY)]))
    usage = response.json()["usage"]
    assert set(usage) == {"prompt_tokens", "completion_tokens", "total_tokens"}
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


async def test_call_ids_increment_across_requests(client: httpx.AsyncClient) -> None:
    """Numer `call_fake_<n>` rośnie z każdym żądaniem w procesie."""
    first = await client.post("/v1/chat/completions", json=_body([_user("pierwsze")]))
    second = await client.post("/v1/chat/completions", json=_body([_user("drugie")]))
    assert _calls(first)[0]["id"] == "call_fake_1"
    assert _calls(second)[0]["id"] == "call_fake_2"


async def test_stream_tool_calls_frames(client: httpx.AsyncClient) -> None:
    """Strumień `tool_calls`: nagłówek z `id`/`type`/`name`, fragmenty `arguments`, stop."""
    response = await client.post("/v1/chat/completions", json=_body([_user(QUERY)], stream=True))
    assert response.status_code == HTTP_OK
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = _chunks(response)
    first = chunks[0]["choices"][0]["delta"]
    assert first["role"] == "assistant"
    assert first["content"] is None
    header = first["tool_calls"][0]
    assert header["id"] == "call_fake_1"
    assert header["type"] == "function"
    assert header["function"]["name"] == "search"
    fragments = [
        chunk["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
        for chunk in chunks[1:-1]
    ]
    assert "".join(fragments) == json.dumps({"query": QUERY}, ensure_ascii=False)
    assert all(len(fragment) <= CHUNK_CHARS for fragment in fragments)
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


async def test_stream_final_answer_after_tool(client: httpx.AsyncClient) -> None:
    """Odpowiedź końcowa po `role: tool` strumieniowana porcjami jak zwykły czat."""
    messages = [
        _user(QUERY),
        {"role": "tool", "tool_call_id": "call_fake_1", "content": "Kot jest w ogrodzie"},
    ]
    response = await client.post("/v1/chat/completions", json=_body(messages, stream=True))
    assert response.status_code == HTTP_OK
    chunks = _chunks(response)
    deltas = [chunk["choices"][0]["delta"].get("content", "") for chunk in chunks[1:-1]]
    assert "".join(deltas) == f"{TOOLS_PREFIX}[call_fake_1] Kot jest w ogrodzie"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


async def test_stats_count_and_reset_tool_calls(client: httpx.AsyncClient) -> None:
    """`GET /v1/fake/stats` liczy wygenerowane wywołania; reset zeruje licznik i numerację."""
    await client.post("/v1/chat/completions", json=_body([_user(f"{QUERY} [[tools:all]]")]))
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["tool_calls"] == ALL_TOOLS_CALLS
    assert (await client.post("/v1/fake/stats/reset")).json()["tool_calls"] == 0
    assert (await client.get("/v1/fake/stats")).json()["tool_calls"] == 0
    after = await client.post("/v1/chat/completions", json=_body([_user("nowe")]))
    assert _calls(after)[0]["id"] == "call_fake_1"
