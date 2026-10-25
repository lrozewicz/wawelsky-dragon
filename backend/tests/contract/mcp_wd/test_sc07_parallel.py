"""SC-E6-2-07 (K17 §5): 20 równoległych ``ragflow_retrieval`` + budżet pamięci serwera MCP.

Klient MCP wywołuje ``ragflow_retrieval`` 20x równolegle (``asyncio.gather``); wszystkie
odpowiedzi mają być poprawne, a RSS procesu ``python -m app.mcp`` poniżej 256 MB (limit
z ``WD_MCP_MEM_LIMIT``, K17 §1). RSS czytamy z ``/proc/<pid>/status`` (``VmRSS``) — bez
dodatkowej zależności (``psutil`` nie jest w ``pyproject``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.contract.mcp_wd.session_helpers import base_url_of, mcp_session, text_of
from tests.contract.mcp_wd.support import EXPECTED_MARKER, QUESTION, McpStack

pytestmark = [pytest.mark.contract]

PARALLEL_CALLS = 20
RSS_LIMIT_KB = 256 * 1024  # 256 MB (K17 §1: WD_MCP_MEM_LIMIT=256m)


def _rss_kb(pid: int) -> int:
    """Bieżący RSS procesu w KiB z ``/proc/<pid>/status`` (pole ``VmRSS``)."""
    for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise AssertionError(f"/proc/{pid}/status: brak pola VmRSS")


async def test_sc_e6_2_07_parallel_retrieval(mcp_stack: McpStack) -> None:
    """SC-E6-2-07: 20 równoległych retrievalli poprawnych; RSS serwera MCP < 256 MB."""
    headers = {"Authorization": f"Bearer {mcp_stack.api_key}"}
    async with mcp_session(base_url_of(mcp_stack.mcp_url), "streamable_http", headers) as session:
        await session.initialize()
        results = await asyncio.gather(
            *(
                session.call_tool("ragflow_retrieval", {"question": QUESTION})
                for _ in range(PARALLEL_CALLS)
            )
        )

    assert len(results) == PARALLEL_CALLS
    for index, result in enumerate(results):
        assert result.isError is False, (index, text_of(result))
        assert EXPECTED_MARKER in text_of(result), index

    rss_kb = _rss_kb(mcp_stack.mcp_pid)
    assert rss_kb < RSS_LIMIT_KB, f"RSS serwera MCP {rss_kb} KiB ≥ limit {RSS_LIMIT_KB} KiB"
