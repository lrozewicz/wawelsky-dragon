"""Pomocnik sesji klienta MCP dla testów scenariuszowych (SC-E6-2-02…07, K17 §5).

Otwiera sesję ``ClientSession`` na wybranym transporcie serwera WD (``/mcp`` streamable HTTP,
``/sse`` SSE) — te same ścieżki i te same klienty pakietu ``mcp``, których używał recorder
(``tools/contract-recorder/mcp_runner.py``). ``text_of`` skleja bloki ``TextContent`` wyniku
``call_tool`` (jak ``test_sc01_streamable_http.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

_ENDPOINTS = {"streamable_http": "/mcp", "sse": "/sse"}
# Jawny hojny timeout klienta MCP (T7): domyślny read timeout httpx to 5 s, a retrieval pod
# obciążeniem (xdist -n 8) trwa dłużej — flak ``sha_retrieval_dataset_ids``/``sc_e6_2_03``.
_MCP_REQUEST_TIMEOUT_S = 60.0


@asynccontextmanager
async def mcp_session(
    base_url: str, transport: str, headers: Mapping[str, str]
) -> AsyncIterator[ClientSession]:
    """Sesja ``ClientSession`` na ``base_url`` (bez ``/mcp``) w danym transporcie.

    Nie woła ``initialize`` — testy robią to jawnie (kroki protokołu są treścią scenariuszy).
    """
    url = base_url.rstrip("/") + _ENDPOINTS[transport]
    if transport == "streamable_http":
        async with (
            httpx.AsyncClient(
                headers=dict(headers), timeout=httpx.Timeout(_MCP_REQUEST_TIMEOUT_S)
            ) as client,
            streamable_http_client(url, http_client=client) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            yield session
    else:
        async with (
            sse_client(url, headers=dict(headers), timeout=_MCP_REQUEST_TIMEOUT_S) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            yield session


def base_url_of(mcp_stack_url: str) -> str:
    """Bazowy URL serwera MCP (bez ścieżki ``/mcp``) z ``McpStack.mcp_url``."""
    return mcp_stack_url.rsplit("/mcp", 1)[0]


def text_of(result: object) -> str:
    """Skleja teksty bloków ``TextContent`` z wyniku ``call_tool``."""
    content = getattr(result, "content", [])
    return "".join(block.text for block in content if getattr(block, "type", None) == "text")
