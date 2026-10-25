"""Testy `BraveProvider` na nagranej odpowiedzi Brave (CONTRACT E6-3f §C4, K18 §5).

Klucz dostawcy idzie w żądaniu (nagłówek `X-Subscription-Token`) i NIE wycieka przez `repr`,
wyjątek ani log (§C4).
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.services.web_search.brave import BraveProvider
from app.services.web_search.types import WebResult, WebSearchUnavailable
from tests.unit.services.web_search.conftest import client_with, json_response, load_fixture

API_KEY = "BSA-SECRET-token-0123456789"
#: Liczba wierszy fixture'u z adresem `url` (jeden wiersz bez `url` jest pomijany).
WITH_URL = 2


async def test_maps_results_and_truncates_to_top_n() -> None:
    """Nagrana odpowiedź → `WebResult` z `web.results[]` obcięte do `top_n` (§C4)."""
    payload = load_fixture("brave")
    provider = BraveProvider(API_KEY, client=client_with(lambda _r: json_response(payload)))
    results = await provider.search("kot", top_n=2)
    assert results == [
        WebResult(
            "Kot domowy - Wikipedia",
            "https://pl.wikipedia.org/wiki/Kot_domowy",
            "Kot domowy (Felis catus) - udomowiony gatunek ssaka.",
        ),
        WebResult("Koty - poradnik", "https://example.org/koty", "Poradnik o kotach."),
    ]


async def test_skips_results_without_url() -> None:
    """Wiersz bez `url` pomijamy; z 3 wierszy zostają 2 z adresem (§C4)."""
    payload = load_fixture("brave")
    provider = BraveProvider(API_KEY, client=client_with(lambda _r: json_response(payload)))
    results = await provider.search("kot", top_n=10)
    assert len(results) == WITH_URL
    assert all(result.url for result in results)


async def test_puts_key_in_subscription_header() -> None:
    """Klucz trafia do nagłówka `X-Subscription-Token`; `q` i `count` w parametrach (§C4)."""
    captured: dict[str, str] = {}
    payload = load_fixture("brave")

    def handler(request: httpx.Request) -> httpx.Response:
        captured["token"] = request.headers["x-subscription-token"]
        captured["q"] = request.url.params["q"]
        captured["count"] = request.url.params["count"]
        return json_response(payload)

    provider = BraveProvider(API_KEY, client=client_with(handler))
    await provider.search("kot", top_n=3)
    assert captured == {"token": API_KEY, "q": "kot", "count": "3"}


def test_key_is_absent_from_repr() -> None:
    """`repr(provider)` nie zawiera klucza (§C4)."""
    provider = BraveProvider(API_KEY)
    assert repr(provider) == "<BraveProvider name=brave>"
    assert API_KEY not in repr(provider)


async def test_key_is_absent_from_error_and_log(caplog: pytest.LogCaptureFixture) -> None:
    """Klucz nie wycieka przez wyjątek ani log przy porażce HTTP (§C4)."""
    provider = BraveProvider(API_KEY, client=client_with(lambda _r: json_response({}, status=401)))
    with caplog.at_level(logging.DEBUG), pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert API_KEY not in str(exc_info.value)
    assert API_KEY not in caplog.text


@pytest.mark.parametrize("status", [500, 401])
async def test_http_error_raises_unavailable(status: int) -> None:
    """HTTP ≥ 400 → `WebSearchUnavailable` z niepustym powodem (§C4)."""
    provider = BraveProvider(
        API_KEY, client=client_with(lambda _r: json_response({}, status=status))
    )
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.provider == "brave"
    assert exc_info.value.reason


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("zbyt wolno"), httpx.ConnectError("brak trasy")]
)
async def test_transport_error_raises_unavailable(error: httpx.HTTPError) -> None:
    """Timeout i błąd połączenia → `WebSearchUnavailable` z nazwą wyjątku (§C4)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise error

    provider = BraveProvider(API_KEY, client=client_with(handler))
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason == type(error).__name__


async def test_non_json_response_raises_unavailable() -> None:
    """Ciało nie-JSON → `WebSearchUnavailable` (§C4)."""
    provider = BraveProvider(
        API_KEY, client=client_with(lambda _r: httpx.Response(200, content=b"nie json"))
    )
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason == "invalid JSON response"


async def test_malformed_response_raises_unavailable() -> None:
    """JSON o złym kształcie (brak `web.results`) → `WebSearchUnavailable` (§C4)."""
    provider = BraveProvider(API_KEY, client=client_with(lambda _r: json_response({})))
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search("kot", top_n=1)
    assert exc_info.value.reason
