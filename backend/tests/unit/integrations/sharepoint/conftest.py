"""Wspólne fixture'y testów warstwy SharePoint (WP E4-2a) — bez sieci."""

import itertools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.integrations.sharepoint.auth import TokenProvider, clear_token_cache
from app.integrations.sharepoint.graph import GRAPH_BASE_URL, GraphClient

FIXTURES_DIR = Path(__file__).parents[3] / "fixtures" / "graph"

Handler = Callable[[httpx.Request], httpx.Response]

TOKEN_HOST = "login.microsoftonline.com"  # noqa: S105 — nazwa hosta, nie sekret
TENANT_ID = "T1"
CLIENT_ID = "C1"
CLIENT_SECRET = "test-secret"  # noqa: S105 — sekret wyłącznie testowy
TOKEN_EXPIRES_IN = 3599


class FakeClock:
    """Deterministyczny zegar monotoniczny; `now` w sekundach, `advance()` przesuwa czas."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def load_fixture(name: str) -> dict[str, Any]:
    """Wczytuje syntetyczną odpowiedź Graph z `backend/tests/fixtures/graph/<name>`."""
    with open(FIXTURES_DIR / name, encoding="utf-8") as handle:
        loaded: dict[str, Any] = json.load(handle)
    return loaded


@pytest.fixture(autouse=True)
def _clear_token_cache() -> None:
    """Czyści modułowy cache tokenów przed każdym testem."""
    clear_token_cache()


@pytest.fixture
def clock() -> FakeClock:
    """Świeży deterministyczny zegar dla testu."""
    return FakeClock()


def make_client(handler: Handler, *, sleeps: list[float] | None = None) -> GraphClient:
    """Buduje `GraphClient` na `MockTransport`.

    `handler` obsługuje wyłącznie żądania do Graph; żądania tokenowe (host
    `login.microsoftonline.com`) odpowiadają licznikiem `tok-N` (N rośnie z każdym
    żądaniem tokenu). `sleep` nagrywa opóźnienia do `sleeps`, `jitter` zwraca 0.0.
    """
    recorded: list[float] = [] if sleeps is None else sleeps
    counter = itertools.count(1)

    def transport_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            token = f"tok-{next(counter)}"
            return httpx.Response(200, json={"access_token": token, "expires_in": TOKEN_EXPIRES_IN})
        return handler(request)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(transport_handler),
        base_url=GRAPH_BASE_URL,
        follow_redirects=False,
    )
    tokens = TokenProvider(
        http, tenant_id=TENANT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET
    )

    async def sleep(seconds: float) -> None:
        recorded.append(seconds)

    return GraphClient(http, tokens, sleep=sleep, jitter=lambda: 0.0)
