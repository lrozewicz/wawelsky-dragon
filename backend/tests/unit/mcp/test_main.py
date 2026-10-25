"""Testy ``__main__`` MCP: odczyt ``WD_MCP_PORT``/``WD_MCP_API_BASE`` i start uvicorna (K17 §1)."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette

import app.mcp.__main__ as mcp_main

ALL_INTERFACES = "0.0.0.0"  # noqa: S104 — K17 §1: nasłuch na wszystkich interfejsach
TEST_PORT = 9999


def test_main_reads_env_and_runs_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main`` bierze port i base z env i woła ``uvicorn.run`` na ``0.0.0.0`` z fabryką."""
    captured: dict[str, object] = {}

    def _fake_run(app: Starlette, host: str, port: int) -> None:
        captured.update(app=app, host=host, port=port)

    monkeypatch.setattr(mcp_main.uvicorn, "run", _fake_run)
    monkeypatch.setenv("WD_MCP_PORT", str(TEST_PORT))
    monkeypatch.setenv("WD_MCP_API_BASE", "http://api.internal:1234/api/v1")

    mcp_main.main()

    assert captured["host"] == ALL_INTERFACES
    assert captured["port"] == TEST_PORT
    assert isinstance(captured["app"], Starlette)


def test_main_defaults_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bez env: port 9382 i domyślny ``WD_MCP_API_BASE`` (K17 §1)."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        mcp_main.uvicorn,
        "run",
        lambda app, host, port: captured.update(app=app, host=host, port=port),
    )
    monkeypatch.delenv("WD_MCP_PORT", raising=False)
    monkeypatch.delenv("WD_MCP_API_BASE", raising=False)

    mcp_main.main()

    assert captured["port"] == mcp_main.DEFAULT_PORT
    assert mcp_main.DEFAULT_API_BASE == "http://api:8000/api/v1"
