"""Testy `DuckDuckGoProvider` na nagranej odpowiedzi Instant Answer (§C4, K18 §5)."""

from __future__ import annotations

import httpx
import pytest

from app.services.web_search.duckduckgo import DuckDuckGoProvider
from app.services.web_search.types import WebResult, WebSearchUnavailable
from tests.unit.services.web_search.conftest import client_with, json_response, load_fixture

BASE_URL = "https://api.duckduckgo.test/"
#: Liczba pozycji fixture'u z adresem `FirstURL` (wpis bez adresu jest pomijany).
WITH_URL = 3


async def test_flattens_related_topics_and_truncates() -> None:
    """`RelatedTopics` (z grupami) spłaszczone; `title` = `Text` do pierwszego ` - ` (§C4)."""
    payload = load_fixture("duckduckgo")
    provider = DuckDuckGoProvider(
        base_url=BASE_URL, client=client_with(lambda _r: json_response(payload))
    )
    results = await provider.search("kot", top_n=10)
    assert results == [
        WebResult("Kot domowy", "https://duckduckgo.com/Kot_domowy", "Kot domowy - Wikipedia"),
        WebResult("Kot perski", "https://duckduckgo.com/Kot_perski", "Kot perski - rasa kota"),
        WebResult("Maine Coon", "https://duckduckgo.com/Maine_Coon", "Maine Coon - rasa kota"),
    ]


async def test_truncates_to_top_n() -> None:
    """Lista obcięta do `top_n` (§C4)."""
    payload = load_fixture("duckduckgo")
    provider = DuckDuckGoProvider(
        base_url=BASE_URL, client=client_with(lambda _r: json_response(payload))
    )
    results = await provider.search("kot", top_n=1)
    assert [result.url for result in results] == ["https://duckduckgo.com/Kot_domowy"]


async def test_skips_topics_without_url() -> None:
    """Pozycja bez `FirstURL` jest pomijana (§C4)."""
    payload = load_fixture("duckduckgo")
    provider = DuckDuckGoProvider(
        base_url=BASE_URL, client=client_with(lambda _r: json_response(payload))
    )
    results = await provider.search("kot", top_n=10)
    assert all(result.url for result in results)
    assert len(results) == WITH_URL


async def test_request_asks_json_without_html() -> None:
    """Żądanie niesie `q`, `format=json`, `no_html=1` (§C4)."""
    captured: dict[str, str] = {}
    payload = load_fixture("duckduckgo")

    def handler(request: httpx.Request) -> httpx.Response:
        captured["q"] = request.url.params["q"]
        captured["format"] = request.url.params["format"]
        captured["no_html"] = request.url.params["no_html"]
        return json_response(payload)

    provider = DuckDuckGoProvider(base_url=BASE_URL, client=client_with(handler))
    await provider.search("kot", top_n=1)
    assert captured == {"q": "kot", "format": "json", "no_html": "1"}


@pytest.mark.parametrize("status", [500, 401])
async def test_http_error_raises_unavailable(status: int) -> None:
    """HTTP ≥ 400 → `WebSearchUnavailable` z niepustym powodem (§C4)."""
    provider = DuckDuckGoProvider(
        base_url=BASE_URL, client=client_with(lambda _r: json_response({}, status=status))
    )
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.provider == "duckduckgo"
    assert exc_info.value.reason


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("zbyt wolno"), httpx.ConnectError("brak trasy")]
)
async def test_transport_error_raises_unavailable(error: httpx.HTTPError) -> None:
    """Timeout i błąd połączenia → `WebSearchUnavailable` z nazwą wyjątku (§C4)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise error

    provider = DuckDuckGoProvider(base_url=BASE_URL, client=client_with(handler))
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason == type(error).__name__


async def test_non_json_response_raises_unavailable() -> None:
    """Ciało nie-JSON → `WebSearchUnavailable` (§C4)."""
    provider = DuckDuckGoProvider(
        base_url=BASE_URL, client=client_with(lambda _r: httpx.Response(200, content=b"nie json"))
    )
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason == "invalid JSON response"


async def test_malformed_response_raises_unavailable() -> None:
    """JSON o złym kształcie (brak `RelatedTopics`) → `WebSearchUnavailable` (§C4)."""
    provider = DuckDuckGoProvider(
        base_url=BASE_URL, client=client_with(lambda _r: json_response({}))
    )
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason
