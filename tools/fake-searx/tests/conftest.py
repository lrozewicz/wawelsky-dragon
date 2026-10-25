"""Fixture: serwer stubu w wątku na porcie losowym + klient httpx (C6)."""

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import httpx
import pytest

from fake_searx.app import create_server

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
    """Bazowy URL = adres serwera (nagłówek `Host` żądań)."""
    return f"http://{LOCALHOST}:{server.server_address[1]}"


@pytest.fixture
def client(base_url: str) -> Iterator[httpx.Client]:
    """Klient httpx stubu."""
    with httpx.Client(base_url=base_url) as http_client:
        yield http_client
