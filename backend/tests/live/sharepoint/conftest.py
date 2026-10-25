"""Fixture'y testów live SharePoint (marker ``sharepoint_live``) — prawdziwy tenant testowy.

Wartości ``WD_SP_TEST_*`` biorą udział wyłącznie w budowie klientów; nigdy nie trafiają do
asercji, wydruku ani komunikatu (poza NAZWAMI brakujących zmiennych). Brak zmiennych →
``pytest.skip``, więc domyślne bramki widzą te testy jako pominięte. Uruchamia je TL:
``tools/dev/live.sh sharepoint-live``.
"""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.sharepoint.auth import TokenProvider
from app.integrations.sharepoint.config import SharePointConfig
from app.integrations.sharepoint.connector import SharePointConnector
from app.integrations.sharepoint.graph import GraphClient, make_http_client

REQUIRED_ENV = ("WD_SP_TEST_TENANT_ID", "WD_SP_TEST_CLIENT_ID", "WD_SP_TEST_CLIENT_SECRET")
MAX_FILE_SIZE_BYTES = 1_048_576  # 1 MiB — kontrakt live (T5)
INTEGRATION_ID = 0  # tenant testowy nie ma wiersza w bazie


@pytest.fixture
def sp_env() -> dict[str, str]:
    """Obowiązkowe zmienne tenanta testowego; brak którejkolwiek → pominięcie testu."""
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        pytest.skip("brak WD_SP_TEST_*: " + ", ".join(missing))
    return {name: os.environ[name] for name in REQUIRED_ENV}


@pytest.fixture
async def sp_http(sp_env: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    """Klient HTTP pod Graph dla operacji zapisu (zamykany po teście)."""
    http = make_http_client()
    try:
        yield http
    finally:
        await http.aclose()


@pytest.fixture
def sp_tokens(sp_http: httpx.AsyncClient, sp_env: dict[str, str]) -> TokenProvider:
    """Tokeny aplikacji tenanta testowego (client credentials z env)."""
    return TokenProvider(
        sp_http,
        tenant_id=sp_env["WD_SP_TEST_TENANT_ID"],
        client_id=sp_env["WD_SP_TEST_CLIENT_ID"],
        client_secret=sp_env["WD_SP_TEST_CLIENT_SECRET"],
    )


@pytest.fixture
async def sp_config(
    sp_http: httpx.AsyncClient, sp_tokens: TokenProvider, sp_env: dict[str, str]
) -> SharePointConfig:
    """Konfiguracja tenanta testowego; brak ``WD_SP_TEST_SITE_URL`` → witryna główna z Graph."""
    site_url = os.environ.get("WD_SP_TEST_SITE_URL") or await root_site_url(sp_http, sp_tokens)
    return SharePointConfig(
        integration_id=INTEGRATION_ID,
        tenant_id=sp_env["WD_SP_TEST_TENANT_ID"],
        client_id=sp_env["WD_SP_TEST_CLIENT_ID"],
        client_secret=SecretStr(sp_env["WD_SP_TEST_CLIENT_SECRET"]),
        site_url=site_url,
        max_file_size_bytes=MAX_FILE_SIZE_BYTES,
    )


@pytest.fixture
def connector() -> SharePointConnector:
    """Konektor na prawdziwym Graph (fabryka klientów domyślna)."""
    return SharePointConnector()


async def root_site_url(http: httpx.AsyncClient, tokens: TokenProvider) -> str:
    """``webUrl`` witryny głównej z ``GET /sites/root`` — adresu nie da się wywnioskować z env."""
    graph = GraphClient(http, tokens)
    response = await graph.request("GET", "/sites/root")
    body = response.json()
    return str(body["webUrl"])
