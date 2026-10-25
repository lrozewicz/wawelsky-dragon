"""Serwer MCP Wawelskiego Smoka — aplikacja Starlette (tryb `host`, K17 §2)."""

# Port z RAGFlow v0.27.2 mcp/server/server.py (create_starlette_app, handlery,
# _extract_token_from_headers); Apache-2.0, InfiniFlow; zob. NOTICE.

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from app.mcp.client import ApiConnector

# K17 §2: nazwa serwera wymagana przez złoto `mcp--06`.
SERVER_NAME = "ragflow-mcp-server"
# Nazwa klucza w ``request.state``, nie sekret (wartość przenoszona z upstream).
AUTH_TOKEN_STATE_KEY = "ragflow_auth_token"  # noqa: S105
_CONTEXT_KEY = "mcp_ctx"
# Trasy wymagające tokenu (K17 §3.3); `/healthz` bez auth.
_AUTH_PATH_PREFIXES = ("/messages/", "/sse", "/mcp")

# ``Server`` bez zadeklarowanego typu requestu — kontekst żądania jest Starlette ``Request``.
McpServer = Server[dict[str, Any], Any]


class ApiCtx:
    """Kontekst życia serwera MCP: klient HTTP API WD (jak upstream ``RAGFlowCtx``)."""

    def __init__(self, conn: ApiConnector) -> None:
        self.conn = conn


def _to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="ignore")
    return str(value)


def _normalize_headers(headers: Any) -> dict[str, str]:
    """Nagłówki jako ``{nazwa lowercase: wartość}``; ``dict`` (str/bytes) i Starlette Headers."""
    if headers is None or not hasattr(headers, "items"):
        return {}
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        name = key.decode("latin-1") if isinstance(key, bytes) else str(key)
        normalized.setdefault(name.lower(), _to_text(value).strip())
    return normalized


def _extract_token_from_headers(headers: Any) -> str | None:
    """Token klienta z nagłówków (K17 §3): Bearer bez wielkości, inaczej ``api_key``/``x-api-key``."""  # noqa: E501
    normalized = _normalize_headers(headers)

    auth = normalized.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        bearer = auth[7:].strip()
        if bearer:
            return bearer

    for name in ("api_key", "x-api-key", "api-key"):
        token = normalized.get(name)
        if token:
            return token

    return None


def _extract_token_from_request(request: Any) -> str | None:
    """Token z ``request.state`` (ustawiony przez middleware), inaczej z nagłówków żądania."""
    if request is None:
        return None

    state = getattr(request, "state", None)
    if state is not None:
        token = getattr(state, AUTH_TOKEN_STATE_KEY, None)
        if token:
            return str(token)

    token = _extract_token_from_headers(getattr(request, "headers", None))
    if token and state is not None:
        setattr(request.state, AUTH_TOKEN_STATE_KEY, token)
    return token


class _StreamableHTTPEntry:
    """Adapter ASGI przekazujący żądania do menedżera sesji streamable HTTP."""

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._manager.handle_request(scope, receive, send)


class _AuthMiddleware:
    """401 bez tokenu na trasach MCP (K17 §3.3); ``/healthz`` przepuszczony."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["path"].startswith(_AUTH_PATH_PREFIXES):
            token = _extract_token_from_headers(dict(scope["headers"]))
            if not token:
                response = JSONResponse(
                    {"error": "Missing or invalid authorization header"}, status_code=401
                )
                await response(scope, receive, send)
                return
            scope.setdefault("state", {})[AUTH_TOKEN_STATE_KEY] = token

        await self.app(scope, receive, send)


def _tool_schemas(dataset_description: str, chat_description: str) -> list[types.Tool]:
    """Trzy narzędzia MCP — nazwy, opisy i ``inputSchema`` dosłownie z upstream (K17 §4)."""
    return [
        types.Tool(
            name="ragflow_retrieval",
            description="Retrieve relevant chunks from the RAGFlow retrieve interface based on the question. You can optionally specify dataset_ids to search only specific datasets, or omit dataset_ids entirely to search across ALL available datasets. You can also optionally specify document_ids to search within specific documents. When dataset_ids is not provided or is empty, the system will automatically search across all available datasets. Below is the list of all available datasets, including their descriptions and IDs:"  # noqa: E501 — opis z upstream (K17 §4)
            + dataset_description,
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional array of dataset IDs to search. If not provided or empty, all datasets will be searched.",  # noqa: E501
                    },
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional array of document IDs to search within.",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question or query to search for.",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number for pagination",
                        "default": 1,
                        "minimum": 1,
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Number of results to return per page (default: 10, max recommended: 50 to avoid token limits)",  # noqa: E501
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "similarity_threshold": {
                        "type": "number",
                        "description": "Minimum similarity threshold for results",
                        "default": 0.2,
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "vector_similarity_weight": {
                        "type": "number",
                        "description": "Weight for vector similarity vs term similarity",
                        "default": 0.3,
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "keyword": {
                        "type": "boolean",
                        "description": "Enable keyword-based search",
                        "default": False,
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum results to consider before ranking",
                        "default": 1024,
                        "minimum": 1,
                        "maximum": 1024,
                    },
                    "rerank_id": {
                        "type": "string",
                        "description": "Optional reranking model identifier",
                    },
                    "force_refresh": {
                        "type": "boolean",
                        "description": "Set to true only if fresh dataset and document metadata is explicitly required. Otherwise, cached metadata is used (default: false).",  # noqa: E501
                        "default": False,
                    },
                },
                "required": ["question"],
            },
        ),
        types.Tool(
            name="ragflow_list_datasets",
            description="List all accessible datasets (knowledge bases) in RAGFlow. Returns dataset IDs, names, and descriptions. Use this tool to discover which datasets are available before performing retrieval."  # noqa: E501 — opis z upstream (K17 §4)
            + dataset_description,
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number",
                        "default": 1,
                        "minimum": 1,
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Results per page",
                        "default": 100,
                        "minimum": 1,
                        "maximum": 1000,
                    },
                },
            },
        ),
        types.Tool(
            name="ragflow_list_chats",
            description="List all accessible chat assistants in RAGFlow. Returns chat assistant IDs, names, and descriptions. Use this tool to discover available chat assistants that can be used for conversations."  # noqa: E501 — opis z upstream (K17 §4)
            + chat_description,
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number",
                        "default": 1,
                        "minimum": 1,
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Results per page",
                        "default": 30,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
            },
        ),
    ]


async def _dispatch(
    name: str, arguments: dict[str, Any], *, conn: ApiConnector, api_key: str
) -> list[types.TextContent]:
    """Rozdysponowanie ``call_tool`` do metod klienta — jak upstream (K17 §4)."""
    if name == "ragflow_retrieval":
        return await conn.retrieval(
            api_key=api_key,
            dataset_ids=arguments.get("dataset_ids", []),
            document_ids=arguments.get("document_ids", []),
            question=arguments.get("question", ""),
            page=arguments.get("page", 1),
            page_size=arguments.get("page_size", 10),
            similarity_threshold=arguments.get("similarity_threshold", 0.2),
            vector_similarity_weight=arguments.get("vector_similarity_weight", 0.3),
            keyword=arguments.get("keyword", False),
            top_k=arguments.get("top_k", 1024),
            rerank_id=arguments.get("rerank_id"),
            force_refresh=arguments.get("force_refresh", False),
        )

    if name == "ragflow_list_datasets":
        result = await conn.list_datasets(
            api_key=api_key,
            page=arguments.get("page", 1),
            page_size=arguments.get("page_size", 100),
        )
        return [types.TextContent(type="text", text=result)]

    if name == "ragflow_list_chats":
        result = await conn.list_chats(
            api_key=api_key,
            page=arguments.get("page", 1),
            page_size=arguments.get("page_size", 30),
        )
        return [types.TextContent(type="text", text=result)]

    raise ValueError(f"Tool not found: {name}")


def create_app(api_base: str) -> Starlette:
    """Buduje aplikację Starlette serwera MCP (tryb host) dla ``api_base`` API WD.

    Bez efektów ubocznych przy imporcie — testy i ``python -m app.mcp`` wołają fabrykę.
    """

    @asynccontextmanager
    async def lifespan(_server: McpServer) -> AsyncIterator[dict[str, Any]]:
        # Klient HTTP powstaje na czas życia serwera (sesji) i jest zamykany na końcu —
        # klucz klienta idzie per żądanie, bez cache'u odpowiedzi między żądaniami.
        connector = ApiConnector(api_base)
        logging.info("MCP application started")
        try:
            yield {_CONTEXT_KEY: ApiCtx(connector)}
        finally:
            await connector.close()
            logging.info("MCP application shutting down")

    server: McpServer = Server(SERVER_NAME, lifespan=lifespan)

    async def _current_context() -> tuple[ApiConnector, str]:
        """Klient API WD i klucz klienta bieżącego żądania MCP (K17 §3)."""
        ctx = server.request_context
        api_ctx = ctx.lifespan_context.get(_CONTEXT_KEY)
        if not isinstance(api_ctx, ApiCtx):
            raise ValueError("MCP context is not available")
        api_key = _extract_token_from_request(ctx.request) or ""
        if not api_key:
            raise ValueError("API key or Bearer token is required.")
        return api_ctx.conn, api_key

    async def list_tools() -> list[types.Tool]:
        conn, api_key = await _current_context()
        dataset_description = await conn.list_datasets(api_key=api_key)
        chat_description = await conn.list_chats(api_key=api_key)
        return _tool_schemas(dataset_description, chat_description)

    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        conn, api_key = await _current_context()
        return await _dispatch(name, arguments, conn=conn, api_key=api_key)

    # ``Server.list_tools`` w SDK ``mcp`` jest bez adnotacji — stąd wyciszenie ``no-untyped-call``.
    server.list_tools()(list_tools)  # type: ignore[no-untyped-call]
    server.call_tool()(call_tool)

    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=True,
        stateless=True,
    )

    streamable_http_entry = _StreamableHTTPEntry(session_manager)

    @asynccontextmanager
    async def app_lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            logging.info("StreamableHTTP session manager started")
            try:
                yield
            finally:
                logging.info("StreamableHTTP session manager stopped")

    routes: list[Route | Mount] = [
        Route("/healthz", endpoint=healthz, methods=["GET"]),
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
        Route("/mcp", endpoint=streamable_http_entry, methods=["GET", "POST", "DELETE"]),
        Mount("/mcp", app=streamable_http_entry),
    ]

    return Starlette(
        debug=False,
        routes=routes,
        middleware=[Middleware(_AuthMiddleware)],
        lifespan=app_lifespan,
    )
