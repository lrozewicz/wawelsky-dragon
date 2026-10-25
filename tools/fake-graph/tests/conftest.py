"""Fixture: serwer stubu w wątku na porcie losowym + klient httpx (C3)."""

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import httpx
import pytest

from fake_graph.app import create_server

LOCALHOST = "127.0.0.1"


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    """Serwer na porcie losowym w wątku daemon; zamknięty po teście."""
    httpd = create_server(0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.fixture
def base_url(server: ThreadingHTTPServer) -> str:
    """Bazowy URL klienta = adres, który trafi też do nagłówka `Host` żądań (C3)."""
    return f"http://{LOCALHOST}:{server.server_address[1]}"


@pytest.fixture
def client(base_url: str) -> Iterator[httpx.Client]:
    """Klient httpx bez podążania za przekierowaniami (302 sprawdzamy dosłownie)."""
    with httpx.Client(base_url=base_url, follow_redirects=False) as http_client:
        yield http_client


@pytest.fixture(autouse=True)
def _reset_state(client: httpx.Client) -> Iterator[None]:
    """Każdy test startuje i kończy na stanie początkowym."""
    client.post("/__test/reset")
    yield
    client.post("/__test/reset")
