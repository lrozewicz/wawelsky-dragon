"""Integracja `SearxngProvider`: martwy port, wiszący serwer i stub fake-searx (§C4, §C6).

SC-E6-3f-03: host bez dostępu do wyszukiwarek → `WebSearchUnavailable` z czytelną przyczyną,
bez zawieszenia dłużej niż `timeout_s` (< 3 s). SC-E6-3f-04 (część): `fake-searx` jako
podproces zwraca 3 wyniki wg K18 §5.
"""

from __future__ import annotations

import socket
import time

import pytest

from app.services.web_search.searxng import SearxngProvider
from app.services.web_search.types import WebSearchUnavailable
from tests.integration.web_search.conftest import free_port

#: Górna granica czasu porażki (SC-03: „< 3 s"), bezpiecznie powyżej `timeout_s = 1.0`.
MAX_SECONDS = 3.0
QUERY = "kot"
TOP_N = 3


async def test_dead_port_raises_unavailable_quickly() -> None:
    """Zamknięty port → `WebSearchUnavailable` (ConnectError) w < 3 s (SC-03)."""
    port = free_port()  # port zwolniony → połączenie odrzucone
    provider = SearxngProvider(f"http://127.0.0.1:{port}")
    start = time.monotonic()
    with pytest.raises(WebSearchUnavailable) as exc_info:
        await provider.search(QUERY, top_n=TOP_N, timeout_s=1.0)
    assert time.monotonic() - start < MAX_SECONDS
    assert exc_info.value.provider == "searxng"
    assert exc_info.value.reason


async def test_hanging_server_times_out_quickly() -> None:
    """Serwer przyjmuje połączenie, ale nie odpowiada → timeout w < 3 s (SC-03)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = int(server.getsockname()[1])
    provider = SearxngProvider(f"http://127.0.0.1:{port}")
    start = time.monotonic()
    try:
        with pytest.raises(WebSearchUnavailable) as exc_info:
            await provider.search(QUERY, top_n=TOP_N, timeout_s=1.0)
    finally:
        server.close()
    assert time.monotonic() - start < MAX_SECONDS
    assert "Timeout" in exc_info.value.reason


async def test_fake_searx_returns_three_results(fake_searx: str) -> None:
    """Stub fake-searx → 3 wyniki „Wynik <i>: kot" wg K18 §5 (SC-04)."""
    provider = SearxngProvider(fake_searx)
    results = await provider.search(QUERY, top_n=TOP_N)
    assert [result.title for result in results] == [
        "Wynik 1: kot",
        "Wynik 2: kot",
        "Wynik 3: kot",
    ]
    assert results[0].url == "https://example.test/1"
    assert results[0].snippet == "Fragment 1 o kot"


async def test_fake_searx_truncates_to_top_n(fake_searx: str) -> None:
    """`top_n` obcina listę wyników stubu (§C4)."""
    provider = SearxngProvider(fake_searx)
    results = await provider.search(QUERY, top_n=2)
    assert [result.title for result in results] == ["Wynik 1: kot", "Wynik 2: kot"]
