"""Obsługa `tools` → `tool_calls` oraz odpowiedzi po `role: "tool"` (K10 „Poprawka 2026-10-11c").

Moduł samodzielny: numer `call_fake_<n>` jest proces-globalny, a liczba wygenerowanych wywołań
(`TOOL_CALLS`) trafia do `GET /v1/fake/stats` i zeruje się razem ze statystykami. Strumień
`tool_calls` buduje tu własne ramki SSE (struktura jak w `chat._chunk_frame`).
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import StreamingResponse

from fake_llm.answers import ChatMessage, message_text

# Długość fragmentu `function.arguments` w strumieniu (spójna z resztą fake-llm).
CHUNK_CHARS = 5
# Limit treści jednej wiadomości `tool` w odpowiedzi końcowej (K10 (2)).
TOOL_CONTENT_LIMIT = 200
# Znaczniki sterujące w treści ostatniej wiadomości `user` (K10 (1)/(4)).
NO_TOOL_MARKER = "[[no-tool]]"
ALL_TOOLS_MARKER = "[[tools:all]]"
_TOOLS_PREFIX = "Na podstawie narzędzi: "
_COMPLETION_ID = "chatcmpl-fake"
_TOOL_MARKER_RE = re.compile(r"\[\[tool:([^\]]+)\]\]")
_MARKER_RE = re.compile(r"\[\[[^\]]*\]\]")

# Numer kolejny wywołania w procesie (`call_fake_<n>` od 1); zerowany z licznikami statystyk.
_TOOL_CALL_COUNTER = 0
# Liczba wygenerowanych wywołań — klucz `tool_calls` w `GET /v1/fake/stats` (K10 (4)).
TOOL_CALLS = 0


@dataclass(frozen=True)
class ToolResult:
    """Wynik obsługi `tools`: wywołania (`tool_calls`) albo odpowiedź po `role: tool` (K10)."""

    model: str
    finish_reason: str
    content: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)


def reset() -> None:
    """Zeruje numerację `call_fake_<n>` i liczbę wywołań (razem ze statystykami, K10 (4))."""
    global _TOOL_CALL_COUNTER, TOOL_CALLS  # noqa: PLW0603 — stan modułowy sterowany w locie (K10)
    _TOOL_CALL_COUNTER = 0
    TOOL_CALLS = 0


def _last_user_index(messages: list[ChatMessage]) -> int | None:
    """Indeks ostatniej wiadomości `user` (szukanie od końca) albo None (K10 wskazówka)."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return index
    return None


def _strip_markers(text: str) -> str:
    """Treść `user` bez znaczników `[[…]]` — `query` wywołania (K10 (1))."""
    return _MARKER_RE.sub("", text).strip()


def _tool_names(text: str, tools: list[dict[str, Any]]) -> list[str]:
    """Nazwy narzędzi: `[[tools:all]]` → wszystkie, `[[tool:<n>]]` → jedno, inaczej pierwsze."""
    if ALL_TOOLS_MARKER in text:
        return [str(tool["function"]["name"]) for tool in tools]
    match = _TOOL_MARKER_RE.search(text)
    if match is not None:
        return [match.group(1)]
    return [str(tools[0]["function"]["name"])]


def _build_call(name: str, query: str) -> dict[str, Any]:
    """Jedno wywołanie `call_fake_<n>` z `arguments` jako JSON-string (numeracja procesowa)."""
    global _TOOL_CALL_COUNTER, TOOL_CALLS  # noqa: PLW0603 — stan modułowy sterowany w locie (K10)
    _TOOL_CALL_COUNTER += 1
    TOOL_CALLS += 1
    return {
        "id": f"call_fake_{_TOOL_CALL_COUNTER}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps({"query": query}, ensure_ascii=False),
        },
    }


def _final_content(tool_messages: list[ChatMessage]) -> str:
    """Treść odpowiedzi po `role: tool` (K10 (2)): `[<id>] <≤200 znaków>`, rozdzielone `; `."""
    parts = [
        f"[{message.tool_call_id or ''}] {message_text(message)[:TOOL_CONTENT_LIMIT]}"
        for message in tool_messages
    ]
    return _TOOLS_PREFIX + "; ".join(parts)


def resolve(
    model: str, messages: list[ChatMessage], tools: list[dict[str, Any]] | None
) -> ToolResult | None:
    """Rozstrzyga `tools` wg K10 (1)/(2)/(4); None = zachowanie dotychczasowe.

    Priorytet: wiadomości `tool` po ostatniej `user` → odpowiedź końcowa (2); znacznik `[[no-tool]]`
    albo brak `tools` → None (4); inaczej wywołania narzędzi (1).
    """
    if not tools:
        return None
    index = _last_user_index(messages)
    if index is None:
        return None
    tool_messages = [message for message in messages[index + 1 :] if message.role == "tool"]
    if tool_messages:
        return ToolResult(model=model, finish_reason="stop", content=_final_content(tool_messages))
    text = message_text(messages[index])
    if NO_TOOL_MARKER in text:
        return None
    query = _strip_markers(text)
    calls = [_build_call(name, query) for name in _tool_names(text, tools)]
    return ToolResult(model=model, finish_reason="tool_calls", calls=calls)


def _chunk_frame(
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None,
    usage_obj: dict[str, int] | None = None,
) -> str:
    """Ramka SSE `chat.completion.chunk` dla strumienia `tool_calls` (K10 (3))."""
    chunk: dict[str, Any] = {
        "id": _COMPLETION_ID,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage_obj is not None:
        chunk["usage"] = usage_obj
    return "data: " + json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def _tool_frames(
    model: str, calls: list[dict[str, Any]], usage_obj: dict[str, int]
) -> Iterator[str]:
    """Ramki strumienia `tool_calls`: nagłówek `id`/`type`/`name`, fragmenty `arguments`, stop."""
    yield _chunk_frame(
        model,
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "index": index,
                    "id": call["id"],
                    "type": call["type"],
                    "function": {"name": call["function"]["name"], "arguments": ""},
                }
                for index, call in enumerate(calls)
            ],
        },
        None,
    )
    for index, call in enumerate(calls):
        arguments = call["function"]["arguments"]
        for start in range(0, len(arguments), CHUNK_CHARS):
            yield _chunk_frame(
                model,
                {
                    "tool_calls": [
                        {
                            "index": index,
                            "function": {"arguments": arguments[start : start + CHUNK_CHARS]},
                        }
                    ]
                },
                None,
            )
    yield _chunk_frame(model, {}, "tool_calls", usage_obj)
    yield "data: [DONE]\n\n"


def respond(
    model: str, calls: list[dict[str, Any]], usage_obj: dict[str, int], stream: bool
) -> StreamingResponse | dict[str, Any]:
    """Odpowiedź `tool_calls` (K10 (1)/(3)): JSON (`content: null`) albo strumień SSE."""
    if stream:
        return StreamingResponse(
            _tool_frames(model, calls, usage_obj), media_type="text/event-stream"
        )
    return {
        "id": _COMPLETION_ID,
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": calls},
                "finish_reason": "tool_calls",
            }
        ],
        "usage": usage_obj,
    }
