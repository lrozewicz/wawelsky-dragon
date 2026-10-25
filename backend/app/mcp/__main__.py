"""Wejście ``python -m app.mcp``: serwer MCP na ``0.0.0.0:WD_MCP_PORT`` (K17 §1)."""

from __future__ import annotations

import os

import uvicorn

from app.mcp.server import create_app

HOST = "0.0.0.0"  # noqa: S104 — K17 §1: serwer słucha na wszystkich interfejsach w sieci compose
DEFAULT_PORT = 9382
DEFAULT_API_BASE = "http://api:8000/api/v1"


def main() -> None:
    """Startuje uvicorn z fabryką aplikacji sterowaną ``WD_MCP_API_BASE`` i ``WD_MCP_PORT``."""
    api_base = os.environ.get("WD_MCP_API_BASE", DEFAULT_API_BASE)
    port = int(os.environ.get("WD_MCP_PORT", str(DEFAULT_PORT)))
    uvicorn.run(create_app(api_base), host=HOST, port=port)


if __name__ == "__main__":
    main()
