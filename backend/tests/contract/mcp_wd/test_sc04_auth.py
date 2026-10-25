"""SC-E6-2-04 (K17 §3): brak klucza i zły klucz — oba transporty.

Brak nagłówka auth → serwer MCP odpowiada 401 ``{"error":"Missing or invalid authorization
header"}`` (oba transporty, także ``initialize``); klient pakietu ``mcp`` podnosi wtedy
``HTTPStatusError``. Zły klucz przechodzi przez middleware (sprawdza tylko OBECNOŚĆ tokenu),
a błąd wychodzi przy pierwszym wywołaniu API WD z narzędzia → ``McpError`` z „Unauthorized”.
"""

from __future__ import annotations

import httpx
import pytest

from tests.contract.mcp_wd.golden_steps import run_step
from tests.contract.mcp_wd.session_helpers import base_url_of
from tests.contract.mcp_wd.support import HTTP_TIMEOUT_S, McpStack

pytestmark = [pytest.mark.contract]

_TRANSPORTS = ("streamable_http", "sse")


@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_sc_e6_2_04_no_auth_401(mcp_stack: McpStack, transport: str) -> None:
    """SC-E6-2-04: ``list_tools`` bez nagłówka → ``HTTPStatusError`` 401 na obu transportach."""
    step = {"id": "no_auth", "transport": transport, "op": "list_tools", "auth": "none"}
    payload = await run_step(mcp_stack, step, dataset_id=mcp_stack.dataset_id, chat_id=None)
    assert payload["outcome"] == "error", payload
    result = payload["result"]
    assert result["error_type"] == "HTTPStatusError", result
    assert result["http_status"] == httpx.codes.UNAUTHORIZED, result
    assert "401" in result["message"], result


@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_sc_e6_2_04_bad_key_unauthorized(mcp_stack: McpStack, transport: str) -> None:
    """SC-E6-2-04: zły klucz → ``McpError`` z komunikatem zawierającym „Unauthorized”."""
    step = {"id": "bad_key", "transport": transport, "op": "list_tools", "auth": "bad"}
    payload = await run_step(mcp_stack, step, dataset_id=mcp_stack.dataset_id, chat_id=None)
    assert payload["outcome"] == "error", payload
    result = payload["result"]
    assert result["error_type"] == "McpError", result
    assert "Unauthorized" in result["message"], result


def test_sc_e6_2_04_401_body(mcp_stack: McpStack) -> None:
    """SC-E6-2-04: surowa odpowiedź 401 ma ciało z K17 §3.3 (oba transporty)."""
    base = base_url_of(mcp_stack.mcp_url)
    for path in (mcp_stack.mcp_url, f"{base}/sse"):
        response = httpx.get(path, timeout=HTTP_TIMEOUT_S)
        assert response.status_code == httpx.codes.UNAUTHORIZED, (path, response.status_code)
        assert response.json() == {"error": "Missing or invalid authorization header"}, (
            path,
            response.text,
        )
