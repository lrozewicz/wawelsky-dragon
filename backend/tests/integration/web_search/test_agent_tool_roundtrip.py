"""Pętla narzędzia: fake-llm `tool_calls` → `SearxngProvider` → odpowiedź `tool` (SC-04).

Żądanie do fake-llm z `tools=[search]` → `tool_calls` (K10 „Poprawka 2026-10-11c"); narzędzie
wykonane przez `SearxngProvider` przeciw `fake-searx`; wiadomość `role: "tool"` → odpowiedź
końcowa zaczynająca się od „Na podstawie narzędzi: [call_fake_".
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
import pytest

from app.services.web_search.searxng import SearxngProvider

#: Model czatu fake-llm i definicja narzędzia w formacie OpenAI (K10 2026-10-11c).
MODEL = "fake-chat"
QUERY = "kot"
TOP_N = 3
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Wyszukiwanie w sieci",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def _llm_base_url() -> str | None:
    """Bazowy URL fake-llm stosu testowego: `WD_LLM_BASE_URL` albo `WD_TEST_LLM_PORT` (§C4)."""
    if url := os.environ.get("WD_LLM_BASE_URL"):
        return url
    port = os.environ.get("WD_TEST_LLM_PORT")
    if not port:
        return None
    host = os.environ.get("WD_HOST", "host.docker.internal")
    return f"http://{host}:{port}/v1"


pytestmark = [
    pytest.mark.fakellm,
    pytest.mark.skipif(
        _llm_base_url() is None, reason="fakellm: brak WD_LLM_BASE_URL / WD_TEST_LLM_PORT"
    ),
]


async def test_tool_call_roundtrip(fake_searx: str) -> None:
    """`tools` → `tool_calls`; wykonanie w fake-searx; `tool` → odpowiedź końcowa (SC-04)."""
    root = _llm_base_url()
    assert root is not None
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Bez globalnego `stats/reset` (T8): zerowałoby wspólny stan fake-llm testom równoległym
        # (m.in. licznik `max_concurrent` w test_concurrency.py). Liczymy przyrost `tool_calls`.
        before = (await client.get(f"{root}/fake/stats")).json()["tool_calls"]
        first = await _chat(client, root, [{"role": "user", "content": QUERY}])
        assert first["choices"][0]["finish_reason"] == "tool_calls"
        call = first["choices"][0]["message"]["tool_calls"][0]
        assert re.match(r"^call_fake_\d+$", call["id"]) is not None
        assert call["function"]["name"] == "search"
        assert json.loads(call["function"]["arguments"]) == {"query": QUERY}
        # Licznik `tool_calls` w stats rośnie po wygenerowaniu wywołania (K10 (4)); inne testy
        # mogą dorzucać własne wywołania, więc sprawdzamy przyrost, a nie wartość dokładną.
        after = (await client.get(f"{root}/fake/stats")).json()["tool_calls"]
        assert after >= before + 1

        provider = SearxngProvider(fake_searx)
        results = await provider.search(QUERY, top_n=TOP_N)
        assert len(results) == TOP_N

        tool_content = json.dumps(
            [{"title": result.title, "url": result.url} for result in results], ensure_ascii=False
        )
        second = await _chat(
            client,
            root,
            [
                {"role": "user", "content": QUERY},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": first["choices"][0]["message"]["tool_calls"],
                },
                {"role": "tool", "tool_call_id": call["id"], "content": tool_content},
            ],
        )
        final = second["choices"][0]["message"]["content"]
        assert final.startswith("Na podstawie narzędzi: [call_fake_")


async def _chat(
    client: httpx.AsyncClient, root: str, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Jedno żądanie `chat/completions` z narzędziami; zwraca JSON odpowiedzi (K10)."""
    response = await client.post(
        f"{root}/chat/completions", json={"model": MODEL, "messages": messages, "tools": TOOLS}
    )
    response.raise_for_status()
    return response.json()
