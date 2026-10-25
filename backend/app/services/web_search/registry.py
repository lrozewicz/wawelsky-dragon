"""Rejestr dostawców wyszukiwania (CONTRACT E6-3f §C4, K18 §5).

`get_provider(row, settings)` buduje dostawcę z wiersza `web_search_providers` (K2 §6):
`config.base_url` z seedu, klucz `api_key_enc` odszyfrowany przez `keys.decrypt_key` (M4
crypto; nigdy w odpowiedziach API ani logach). Nieznany `row.provider` → `ValueError`.
"""

from app.core.config import Settings
from app.db.repositories.web_search_providers import WebSearchProviderRow
from app.services.web_search import keys
from app.services.web_search.brave import BRAVE_SEARCH_URL, BraveProvider
from app.services.web_search.duckduckgo import DUCKDUCKGO_SEARCH_URL, DuckDuckGoProvider
from app.services.web_search.searxng import SearxngProvider
from app.services.web_search.tavily import TAVILY_SEARCH_URL, TavilyProvider
from app.services.web_search.types import WebSearchProvider

# `base_url` domyślnego stosu (seed migracji 0008, K18 §5) — gdy `config` go nie ustawia.
DEFAULT_SEARXNG_URL = "http://searxng:8080"


def get_provider(row: WebSearchProviderRow, settings: Settings) -> WebSearchProvider:
    """Dostawca z wiersza `web_search_providers`; nieznany `provider` → `ValueError` (§C4)."""
    if row.provider == "searxng":
        return SearxngProvider(str(row.config.get("base_url", DEFAULT_SEARXNG_URL)))
    if row.provider == "tavily":
        return TavilyProvider(_decrypt(settings, row), base_url=_base_url(row, TAVILY_SEARCH_URL))
    if row.provider == "brave":
        return BraveProvider(_decrypt(settings, row), base_url=_base_url(row, BRAVE_SEARCH_URL))
    if row.provider == "duckduckgo":
        return DuckDuckGoProvider(base_url=_base_url(row, DUCKDUCKGO_SEARCH_URL))
    raise ValueError(f"unknown web search provider: {row.provider}")


def _base_url(row: WebSearchProviderRow, fallback: str) -> str:
    """`config.base_url` nadpisujący host dostawcy (testy, §C4); brak → `fallback`."""
    return str(row.config["base_url"]) if "base_url" in row.config else fallback


def _decrypt(settings: Settings, row: WebSearchProviderRow) -> str:
    """Klucz dostawcy odszyfrowany z `api_key_enc`; brak klucza → `ValueError` (§C4)."""
    if row.api_key_enc is None:
        raise ValueError(f"{row.provider} provider requires an api key")
    return keys.decrypt_key(settings, row.id, row.api_key_enc)
