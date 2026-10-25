"""Testy autoryzacji serwera MCP (K17 §3): ekstrakcja tokenu, kształt 401, ``/healthz``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.datastructures import Headers
from starlette.testclient import TestClient

from app.mcp.server import (
    _extract_token_from_headers,
    _extract_token_from_request,
    _normalize_headers,
    create_app,
)

API_BASE = "http://api.test/api/v1"
UNAUTHORIZED_BODY = {"error": "Missing or invalid authorization header"}
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Klient aplikacji MCP z uruchomionym lifespanem (bez wywołań API WD)."""
    with TestClient(create_app(API_BASE)) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"authorization": b"Bearer abc"}, "abc"),
        ({"Authorization": "Bearer abc"}, "abc"),
        (Headers({"Authorization": "Bearer abc"}), "abc"),
        (Headers({"authorization": "bearer abc"}), "abc"),
        (Headers({"AUTHORIZATION": "BeArEr abc"}), "abc"),
        (Headers({"Authorization": "Bearer   abc  "}), "abc"),
        (Headers({"api_key": "k1"}), "k1"),
        (Headers({"x-api-key": "k2"}), "k2"),
        (Headers({"Api-Key": "k3"}), "k3"),
        (Headers({"X-API-Key": "k4"}), "k4"),
        (Headers({"Authorization": "Token abc"}), None),
        (Headers({"Authorization": "Bearer "}), None),
        (Headers({}), None),
        (None, None),
    ],
)
def test_extract_token_from_headers(headers: Any, expected: str | None) -> None:
    """Bearer (dowolna wielkość), potem ``api_key``/``x-api-key``/``Api-Key``; brak → ``None``."""
    assert _extract_token_from_headers(headers) == expected


def test_extract_token_from_request_prefers_state() -> None:
    """Token z ``request.state`` (ustawiony przez middleware) ma pierwszeństwo nad nagłówkami."""

    class _Request:
        def __init__(self) -> None:
            self.state = type("S", (), {})()
            self.headers = Headers({"Authorization": "Bearer z-naglowka"})

    request = _Request()
    request.state.ragflow_auth_token = "z-state"  # noqa: S105 — nazwa klucza w state, nie sekret
    assert _extract_token_from_request(request) == "z-state"


def test_extract_token_from_request_falls_back_to_headers() -> None:
    """Brak tokenu w ``state`` → odczyt z nagłówków i zapis do ``state`` (jak middleware)."""

    class _Request:
        def __init__(self) -> None:
            self.state = type("S", (), {})()
            self.headers = Headers({"Authorization": "Bearer z-naglowka"})

    request = _Request()
    assert _extract_token_from_request(request) == "z-naglowka"
    assert request.state.ragflow_auth_token == "z-naglowka"  # noqa: S105 — klucz w state, nie sekret
    assert _extract_token_from_request(None) is None


def test_normalize_headers_handles_bytes_and_str_keys() -> None:
    """Normalizacja sprowadza nazwy (str/bytes) do lowercase, z zachowaniem pierwszej wartości."""
    assert _normalize_headers({b"Api-Key": b"k1"}) == {"api-key": "k1"}
    assert _normalize_headers({"Authorization": "  Bearer x  "}) == {"authorization": "Bearer x"}
    assert _normalize_headers(None) == {}
    assert _normalize_headers(Headers({"X-API-Key": "k2"})) == {"x-api-key": "k2"}


@pytest.mark.parametrize("path", ["/mcp", "/sse", "/messages/?session_id=abc"])
def test_missing_token_is_401(client: TestClient, path: str) -> None:
    """Brak tokenu na trasach MCP → 401 z ciałem ``{"error": ...}`` (K17 §3.3)."""
    response = client.get(path) if not path.startswith("/messages/") else client.post(path)
    assert response.status_code == HTTP_UNAUTHORIZED
    assert response.json() == UNAUTHORIZED_BODY
    assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer klucz"},
        {"api_key": "klucz"},
        {"x-api-key": "klucz"},
        {"Api-Key": "klucz"},
        {"X-API-Key": "klucz"},
    ],
)
def test_token_present_is_not_401(client: TestClient, header: dict[str, str]) -> None:
    """Dowolny z obsługiwanych nagłówków przepuszcza żądanie za middleware (nie 401)."""
    response = client.post("/mcp", headers=header, json={})
    assert response.status_code != HTTP_UNAUTHORIZED


def test_healthz_without_auth(client: TestClient) -> None:
    """``GET /healthz`` bez tokenu → 200 ``{"status":"ok"}`` (K17 §2)."""
    response = client.get("/healthz")
    assert response.status_code == HTTP_OK
    assert response.json() == {"status": "ok"}
