"""Testy rejestru dostawców wyszukiwania (CONTRACT E6-3f §C4, K18 §5).

`get_provider(row, settings)` buduje dostawcę z wiersza `web_search_providers`; klucz
`api_key_enc` jest odszyfrowywany, nieznany `provider` → `ValueError`.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.db.repositories.web_search_providers import WebSearchProviderRow
from app.services.web_search import keys
from app.services.web_search.brave import BraveProvider
from app.services.web_search.duckduckgo import DuckDuckGoProvider
from app.services.web_search.registry import get_provider
from app.services.web_search.searxng import SearxngProvider
from app.services.web_search.tavily import TAVILY_SEARCH_URL, TavilyProvider
from tests.unit.services.web_search.conftest import client_with, json_response, load_fixture

SEED_ID = "5ea4c00d5ea4c00d5ea4c00d5ea4c00d"
CRYPTO_KEY = "ab" * 32
PLAIN = "tvly-SECRET-key"


def _settings() -> Settings:
    """Ustawienia testowe z prawidłowym kluczem szyfrowania (64 hex)."""
    return Settings(env="test", crypto_key=CRYPTO_KEY)


def _row(
    provider: str,
    *,
    config: dict[str, Any] | None = None,
    api_key_enc: bytes | None = None,
) -> WebSearchProviderRow:
    """Wiersz `web_search_providers` do testu rejestru (§C2)."""
    return WebSearchProviderRow(
        id=SEED_ID,
        provider=provider,
        name=provider,
        config=config if config is not None else {},
        api_key_enc=api_key_enc,
        is_default=True,
        created_by=None,
        create_time=0,
    )


async def test_seed_row_builds_searxng_with_base_url() -> None:
    """Wiersz `searxng` z seedu → `SearxngProvider` celujący w `config.base_url` (§C4)."""
    provider = get_provider(
        _row("searxng", config={"base_url": "http://searxng:8080"}), _settings()
    )
    assert isinstance(provider, SearxngProvider)
    captured: dict[str, str] = {}
    payload = load_fixture("searxng")

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return json_response(payload)

    provider._client = client_with(handler)
    await provider.search("kot", top_n=1)
    assert captured["url"].startswith("http://searxng:8080/search?")


async def test_tavily_row_decrypts_key() -> None:
    """Wiersz `tavily` z `api_key_enc` → klucz odszyfrowany i wysłany w nagłówku (§C4)."""
    settings = _settings()
    blob = keys.encrypt_key(settings, SEED_ID, PLAIN)
    provider = get_provider(_row("tavily", api_key_enc=blob), settings)
    assert isinstance(provider, TavilyProvider)
    captured: dict[str, str] = {}
    payload = load_fixture("tavily")

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["url"] = str(request.url)
        return json_response(payload)

    provider._client = client_with(handler)
    await provider.search("kot", top_n=1)
    assert captured["authorization"] == f"Bearer {PLAIN}"
    assert captured["url"] == TAVILY_SEARCH_URL


async def test_brave_row_decrypts_key_and_uses_config_base_url() -> None:
    """Wiersz `brave` → klucz odszyfrowany; `config.base_url` nadpisuje host (§C4)."""
    settings = _settings()
    blob = keys.encrypt_key(settings, SEED_ID, PLAIN)
    provider = get_provider(
        _row(
            "brave", config={"base_url": "https://brave.test/res/v1/web/search"}, api_key_enc=blob
        ),
        settings,
    )
    assert isinstance(provider, BraveProvider)
    captured: dict[str, str] = {}
    payload = load_fixture("brave")

    def handler(request: httpx.Request) -> httpx.Response:
        captured["token"] = request.headers["x-subscription-token"]
        captured["url"] = str(request.url)
        return json_response(payload)

    provider._client = client_with(handler)
    await provider.search("kot", top_n=1)
    assert captured["token"] == PLAIN
    assert captured["url"].startswith("https://brave.test/res/v1/web/search?")


def test_duckduckgo_row_needs_no_key() -> None:
    """Wiersz `duckduckgo` nie wymaga klucza → `DuckDuckGoProvider` (§C4)."""
    provider = get_provider(_row("duckduckgo"), _settings())
    assert isinstance(provider, DuckDuckGoProvider)


def test_tavily_row_without_key_raises() -> None:
    """`tavily` bez `api_key_enc` → `ValueError` (dostawca wymaga klucza, §C4)."""
    with pytest.raises(ValueError, match="tavily"):
        get_provider(_row("tavily"), _settings())


def test_unknown_provider_raises_value_error() -> None:
    """Nieznany `provider` → `ValueError("unknown web search provider: <x>")` (§C4)."""
    with pytest.raises(ValueError, match="unknown web search provider: google"):
        get_provider(_row("google"), _settings())
