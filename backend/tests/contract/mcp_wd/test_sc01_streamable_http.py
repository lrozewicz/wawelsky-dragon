"""SC-E6-2-01 (K17 §5): klient MCP przez streamable HTTP na serwerze WD.

Kroki: ``initialize`` (serverInfo.name), ``list_tools`` (trzy narzędzia upstream),
``call_tool ragflow_list_datasets`` (dataset A), ``call_tool ragflow_retrieval`` (fragment PL).
Serwer ``app.mcp`` powstaje w E6-2 T2.
"""

from __future__ import annotations

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from tests.contract.mcp_wd.support import (
    EXPECTED_MARKER,
    EXPECTED_TOOLS,
    QUESTION,
    McpStack,
)

pytestmark = [pytest.mark.contract]


async def test_sc_e6_2_01_streamable_http(mcp_stack: McpStack) -> None:
    """SC-E6-2-01: initialize + list_tools + ragflow_list_datasets + ragflow_retrieval."""
    async with (
        streamablehttp_client(
            mcp_stack.mcp_url,
            headers={"Authorization": f"Bearer {mcp_stack.api_key}"},
        ) as (read_stream, write_stream, _),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "ragflow-mcp-server"

        tools = await session.list_tools()
        assert sorted(tool.name for tool in tools.tools) == sorted(EXPECTED_TOOLS)

        datasets = await session.call_tool("ragflow_list_datasets", {})
        assert datasets.isError is False
        datasets_text = _text_of(datasets)
        assert mcp_stack.dataset_id in datasets_text

        retrieved = await session.call_tool("ragflow_retrieval", {"question": QUESTION})
        assert retrieved.isError is False
        assert EXPECTED_MARKER in _text_of(retrieved)


def _text_of(result: object) -> str:
    """Skleja teksty bloków ``TextContent`` z wyniku ``call_tool``."""
    content = getattr(result, "content", [])
    return "".join(block.text for block in content if getattr(block, "type", None) == "text")
