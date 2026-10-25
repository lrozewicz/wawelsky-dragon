"""SC-E6-2-02 (K17 §5): klient MCP przez SSE na serwerze WD.

Kroki jak SC-E6-2-01, ale transportem ``/sse`` (event ``endpoint`` → ``/messages/``):
``initialize``, ``list_tools`` (trzy narzędzia), ``ragflow_list_datasets`` (dataset A),
``ragflow_retrieval`` (fragment PL).
"""

from __future__ import annotations

import pytest

from tests.contract.mcp_wd.session_helpers import base_url_of, mcp_session, text_of
from tests.contract.mcp_wd.support import (
    EXPECTED_MARKER,
    EXPECTED_TOOLS,
    QUESTION,
    McpStack,
)

pytestmark = [pytest.mark.contract]


async def test_sc_e6_2_02_sse(mcp_stack: McpStack) -> None:
    """SC-E6-2-02: initialize + list_tools + list_datasets + retrieval przez /sse."""
    headers = {"Authorization": f"Bearer {mcp_stack.api_key}"}
    async with mcp_session(base_url_of(mcp_stack.mcp_url), "sse", headers) as session:
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "ragflow-mcp-server"
        # K17 §2: brak odbicia nagłówków żądania (u upstreamu ``handle_sse`` wyciekał klucz API).
        assert initialized.capabilities.experimental == {}

        tools = await session.list_tools()
        assert sorted(tool.name for tool in tools.tools) == sorted(EXPECTED_TOOLS)

        datasets = await session.call_tool("ragflow_list_datasets", {})
        assert datasets.isError is False
        assert mcp_stack.dataset_id in text_of(datasets)

        retrieved = await session.call_tool("ragflow_retrieval", {"question": QUESTION})
        assert retrieved.isError is False
        assert EXPECTED_MARKER in text_of(retrieved)
