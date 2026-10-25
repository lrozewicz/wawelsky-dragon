"""Testy stubu SearXNG: `/search` w JSON, `/health`, kody błędów (kontrakt E6-3f C6, K18 §5)."""

from http.server import ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from fake_searx.app import DEFAULT_PORT, RESULT_COUNT, create_server, main

HTTP_OK = 200
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
SEARCH_PATH = "/search"
HEALTH_PATH = "/health"
JSON_FORMAT = "json"


def _expected_results(query: str) -> list[dict[str, str]]:
    """Trzy wyniki dokładnie wg C6 (tytuł, URL, `content`)."""
    return [
        {
            "title": f"Wynik {i}: {query}",
            "url": f"https://example.test/{i}",
            "content": f"Fragment {i} o {query}",
        }
        for i in range(1, RESULT_COUNT + 1)
    ]


def test_search_returns_exactly_three_results(client: httpx.Client) -> None:
    response = client.get(SEARCH_PATH, params={"q": "kot", "format": JSON_FORMAT})
    assert response.status_code == HTTP_OK
    assert response.json() == {"query": "kot", "results": _expected_results("kot")}


def test_search_results_have_title_url_and_content(client: httpx.Client) -> None:
    body = client.get(SEARCH_PATH, params={"q": "kot", "format": JSON_FORMAT}).json()
    assert [result["url"] for result in body["results"]] == [
        "https://example.test/1",
        "https://example.test/2",
        "https://example.test/3",
    ]
    assert all(set(result) == {"title", "url", "content"} for result in body["results"])


def test_search_keeps_utf8_query(client: httpx.Client) -> None:
    response = client.get(SEARCH_PATH, params={"q": "zażółć", "format": JSON_FORMAT})
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["query"] == "zażółć"
    assert body["results"] == _expected_results("zażółć")


def test_search_without_query_returns_empty_results(client: httpx.Client) -> None:
    response = client.get(SEARCH_PATH, params={"format": JSON_FORMAT})
    assert response.status_code == HTTP_OK
    assert response.json() == {"query": "", "results": []}


def test_search_empty_query_returns_empty_results(client: httpx.Client) -> None:
    response = client.get(SEARCH_PATH, params={"q": "", "format": JSON_FORMAT})
    assert response.status_code == HTTP_OK
    assert response.json() == {"query": "", "results": []}


def test_search_html_format_forbidden(client: httpx.Client) -> None:
    response = client.get(SEARCH_PATH, params={"q": "kot", "format": "html"})
    assert response.status_code == HTTP_FORBIDDEN


def test_search_without_format_forbidden(client: httpx.Client) -> None:
    """SearXNG bez włączonego JSON zwraca 403 — stub zachowuje się tak samo (C6)."""
    response = client.get(SEARCH_PATH, params={"q": "kot"})
    assert response.status_code == HTTP_FORBIDDEN


def test_search_unknown_format_forbidden(client: httpx.Client) -> None:
    response = client.get(SEARCH_PATH, params={"q": "kot", "format": "csv"})
    assert response.status_code == HTTP_FORBIDDEN


def test_health(client: httpx.Client) -> None:
    response = client.get(HEALTH_PATH)
    assert response.status_code == HTTP_OK
    assert response.json() == {"status": "ok"}


def test_unknown_path_not_found(client: httpx.Client) -> None:
    response = client.get("/inna/sciezka")
    assert response.status_code == HTTP_NOT_FOUND


def test_create_server_returns_threading_http_server() -> None:
    httpd = create_server(0)
    try:
        assert isinstance(httpd, ThreadingHTTPServer)
    finally:
        httpd.server_close()


class _StubServer:
    """Atrapa serwera dla `main`: notuje wywołanie `serve_forever`."""

    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    def serve_forever(self) -> None:
        self._captured["served"] = True


def _stub_create_server(captured: dict[str, Any], port: int) -> Any:
    """Zastępuje `create_server`, notując port i zwracając atrapę."""
    captured["port"] = port
    return _StubServer(captured)


def test_main_uses_env_port(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def factory(port: int) -> _StubServer:
        return _stub_create_server(captured, port)

    monkeypatch.setattr("fake_searx.app.create_server", factory)
    monkeypatch.setenv("FAKE_SEARX_PORT", "9999")
    main()
    assert captured == {"port": 9999, "served": True}


def test_main_default_port(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def factory(port: int) -> _StubServer:
        return _stub_create_server(captured, port)

    monkeypatch.setattr("fake_searx.app.create_server", factory)
    monkeypatch.delenv("FAKE_SEARX_PORT", raising=False)
    main()
    assert captured["port"] == DEFAULT_PORT
