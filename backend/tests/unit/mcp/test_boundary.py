"""K17 §1: ``app/mcp`` nie importuje warstwy usług ani bazy; ``create_app`` to fabryka bez efektów."""  # noqa: E501

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette

from app.mcp.client import ApiConnector
from app.mcp.server import _AuthMiddleware, _dispatch, _tool_schemas, create_app

MCP_DIR = Path(__file__).resolve().parents[3] / "app" / "mcp"
# K17 §1: serwer MCP rozmawia z API WD po HTTP, nie dotyka usług, bazy ani innych warstw.
FORBIDDEN_PREFIXES = ("app.services", "app.db", "app.api", "app.worker", "app.llm")
EXPECTED_TOOLS = ("ragflow_retrieval", "ragflow_list_datasets", "ragflow_list_chats")


def _imported_modules(path: Path) -> set[str]:
    """Nazwy modułów z instrukcji ``import``/``from … import`` w pliku."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_mcp_package_has_no_service_or_db_imports() -> None:
    """Żaden plik ``app/mcp`` nie importuje ``app.services``/``app.db``/``app.api`` (K17 §1)."""
    violations: list[str] = []
    for path in sorted(MCP_DIR.glob("*.py")):
        for module in _imported_modules(path):
            if module.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{path.name}: {module}")
    assert violations == []


def test_create_app_returns_starlette_without_side_effects() -> None:
    """``create_app`` buduje aplikację Starlette i nie startuje serwera przy imporcie/wołaniu."""
    app = create_app("http://api.test/api/v1")
    assert isinstance(app, Starlette)
    paths = {route.path for route in app.routes}
    assert {"/healthz", "/sse", "/mcp", "/messages"} <= paths


def test_tool_schemas_names_required_and_dynamic_descriptions() -> None:
    """Trzy narzędzia upstream: nazwy, wymagane ``question``, dynamiczny ogon opisu (K17 §4)."""
    tools = _tool_schemas("LISTA-DS", "LISTA-CHAT")
    by_name = {tool.name: tool for tool in tools}
    assert tuple(tool.name for tool in tools) == EXPECTED_TOOLS
    assert by_name["ragflow_retrieval"].inputSchema["required"] == ["question"]
    assert by_name["ragflow_retrieval"].description.endswith("LISTA-DS")
    assert by_name["ragflow_list_datasets"].description.endswith("LISTA-DS")
    assert by_name["ragflow_list_chats"].description.endswith("LISTA-CHAT")


async def test_auth_middleware_passes_through_non_http_scopes() -> None:
    """Zakresy nie-HTTP (lifespan/websocket) middleware przepuszcza bez sprawdzania tokenu."""
    seen: list[str] = []

    async def _inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen.append(str(scope["type"]))

    middleware = _AuthMiddleware(_inner)
    await middleware({"type": "lifespan"}, None, None)

    assert seen == ["lifespan"]


def _connector() -> ApiConnector:
    """``ApiConnector`` z klientem na atrapie HTTP (bez sieci)."""
    conn = ApiConnector("http://api.test/api/v1")
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(_api))
    return conn


def _api(request: httpx.Request) -> httpx.Response:
    """Atrapa API WD dla ``_dispatch`` (koperty ``code``/``data``)."""
    path = request.url.path
    if path == "/api/v1/retrieval":
        return httpx.Response(200, json={"code": 0, "data": {"chunks": [], "total": 0}})
    if path == "/api/v1/datasets":
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [{"id": "ds1", "name": "A", "description": None}],
                "total_datasets": 1,
            },
        )
    if path == "/api/v1/datasets/ds1/documents":
        return httpx.Response(200, json={"code": 0, "data": {"docs": []}})
    if path == "/api/v1/chats":
        return httpx.Response(200, json={"code": 0, "data": {"chats": [{"id": "c1", "name": "N"}]}})
    return httpx.Response(404, json={"code": 404, "message": "not found"})


async def test_dispatch_routes_tools_and_rejects_unknown() -> None:
    """``_dispatch`` (K17 §4): trzy narzędzia rozdzielone do klienta, nieznane → ``ValueError``."""
    conn = _connector()

    retrieval = await _dispatch("ragflow_retrieval", {"question": "q"}, conn=conn, api_key="k")
    assert json.loads(retrieval[0].text)["chunks"] == []

    datasets = await _dispatch("ragflow_list_datasets", {}, conn=conn, api_key="k")
    assert "ds1" in datasets[0].text

    chats = await _dispatch("ragflow_list_chats", {}, conn=conn, api_key="k")
    assert "c1" in chats[0].text

    with pytest.raises(ValueError, match="Tool not found: ragflow_unknown_tool"):
        await _dispatch("ragflow_unknown_tool", {}, conn=conn, api_key="k")
