"""Testy `SearxngProvider` na nagranej odpowiedzi SearXNG (CONTRACT E6-3f §C4, K18 §5)."""

from __future__ import annotations

import httpx
import pytest

from app.services.web_search.searxng import SearxngProvider
from app.services.web_search.types import WebResult, WebSearchUnavailable
from tests.unit.services.web_search.conftest import client_with, json_response, load_fixture

BASE_URL = "http://searxng.test:8080"
#: Liczba wierszy fixture'u z adresem `url` (jeden wiersz bez `url` jest pomijany).
WITH_URL = 3


async def test_maps_results_and_truncates_to_top_n() -> None:
    """Nagrana odpowiedź → `WebResult` obcięte do `top_n` (§C4)."""
    payload = load_fixture("searxng")
    provider = SearxngProvider(BASE_URL, client=client_with(lambda _r: json_response(payload)))
    results = await provider.search("kot", top_n=2)
    assert results == [
        WebResult(
            "Kot domowy - Wikipedia, wolna encyklopedia",
            "https://pl.wikipedia.org/wiki/Kot_domowy",
            "Kot domowy (Felis catus) - udomowiony gatunek ssaka z rodziny kotowatych.",
        ),
        WebResult(
            "Kot - pielęgnacja i żywienie",
            "https://example.org/kot-zywienie",
            "Poradnik o pielęgnacji i żywieniu kota domowego.",
        ),
    ]


async def test_skips_results_without_url() -> None:
    """Wiersz bez `url` pomijamy; z 4 wierszy zostają 3 z adresem (§C4)."""
    payload = load_fixture("searxng")
    provider = SearxngProvider(BASE_URL, client=client_with(lambda _r: json_response(payload)))
    results = await provider.search("kot", top_n=10)
    assert len(results) == WITH_URL
    assert all(result.url for result in results)


async def test_request_targets_search_with_json_format() -> None:
    """Żądanie idzie na `/search` z `q` i `format=json` (§C4)."""
    captured: dict[str, str] = {}
    payload = load_fixture("searxng")

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["q"] = request.url.params["q"]
        captured["format"] = request.url.params["format"]
        return json_response(payload)

    provider = SearxngProvider(BASE_URL, client=client_with(handler))
    await provider.search("kot", top_n=1)
    assert captured == {"path": "/search", "q": "kot", "format": "json"}


@pytest.mark.parametrize("status", [500, 401])
async def test_http_error_raises_unavailable(status: int) -> None:
    """HTTP ≥ 400 → `WebSearchUnavailable` z niepustym powodem (§C4)."""
    provider = SearxngProvider(
        BASE_URL, client=client_with(lambda _r: json_response({}, status=status))
    )
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.provider == "searxng"
    assert exc_info.value.reason
    assert str(exc_info.value) == f"searxng: HTTP {status}"


async def test_read_timeout_raises_unavailable() -> None:
    """`httpx.ReadTimeout` → `WebSearchUnavailable` z nazwą wyjątku jako powodem (§C4)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("zbyt wolno")

    provider = SearxngProvider(BASE_URL, client=client_with(handler))
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason == "ReadTimeout"


async def test_connect_error_raises_unavailable() -> None:
    """`httpx.ConnectError` → `WebSearchUnavailable` z nazwą wyjątku jako powodem (§C4)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brak trasy")

    provider = SearxngProvider(BASE_URL, client=client_with(handler))
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason == "ConnectError"


async def test_non_json_response_raises_unavailable() -> None:
    """Ciało nie-JSON → `WebSearchUnavailable` („invalid JSON response", §C4)."""
    not_json = httpx.Response(200, content=b"<html>nie json</html>")

    provider = SearxngProvider(BASE_URL, client=client_with(lambda _r: not_json))
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason == "invalid JSON response"


async def test_repr_has_no_extra_state() -> None:
    """`repr` dostawcy nie zawiera stanu poza nazwą (§C4)."""
    provider = SearxngProvider(BASE_URL)
    assert repr(provider) == "<SearxngProvider name=searxng>"


async def test_malformed_response_raises_unavailable() -> None:
    """JSON o złym kształcie (brak `results`) → `WebSearchUnavailable` (§C4)."""
    provider = SearxngProvider(BASE_URL, client=client_with(lambda _r: json_response({})))
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason
