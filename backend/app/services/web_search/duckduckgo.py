"""Dostawca `duckduckgo`: `GET https://api.duckduckgo.com/` (§C4, K18 §5).

Parametry: `q`, `format=json`, `no_html=1`; bez klucza. Wynik: `RelatedTopics[].{Text,FirstURL}`
spłaszczone (grupy `Topics` rekurencyjnie); `title` = `Text` do pierwszego `" - "`,
`snippet` = cały `Text`. `config` może nadpisać `base_url` (testy, §C4).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.web_search._http import DEFAULT_TIMEOUT_S, HttpProvider
from app.services.web_search.types import WebResult, WebSearchUnavailable

DUCKDUCKGO_SEARCH_URL = "https://api.duckduckgo.com/"

# Separator tytułu w `Text` (np. „Kot domowy - Wikipedia" → tytuł „Kot domowy").
_TITLE_SEPARATOR = " - "


class DuckDuckGoProvider(HttpProvider):
    """Dostawca DuckDuckGo Instant Answer (§C4)."""

    name = "duckduckgo"

    def __init__(
        self,
        *,
        base_url: str = DUCKDUCKGO_SEARCH_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._url = base_url

    async def search(
        self, query: str, *, top_n: int, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> list[WebResult]:
        """`GET {base_url}` → spłaszczone `RelatedTopics` obcięte do `top_n` (§C4)."""
        payload = await self._request_json(
            "GET",
            self._url,
            params={"q": query, "format": "json", "no_html": 1},
            timeout_s=timeout_s,
        )
        return _results(payload, top_n)


def _flatten(topics: Any) -> list[tuple[str, str]]:
    """Spłaszcza `RelatedTopics` (grupy `Topics` rekurencyjnie) do par `(Text, FirstURL)`."""
    out: list[tuple[str, str]] = []
    for topic in topics:
        if "FirstURL" in topic:
            out.append((str(topic["Text"]), str(topic["FirstURL"])))
        elif "Topics" in topic:
            out.extend(_flatten(topic["Topics"]))
    return out


def _results(payload: Any, top_n: int) -> list[WebResult]:
    """Mapuje `RelatedTopics` na `WebResult`; zły kształt → `WebSearchUnavailable` (§C4)."""
    try:
        pairs = _flatten(payload["RelatedTopics"])
    except (TypeError, KeyError) as exc:
        raise WebSearchUnavailable(
            "duckduckgo", f"unexpected response: {type(exc).__name__}"
        ) from exc
    results = [
        WebResult(text.split(_TITLE_SEPARATOR, 1)[0], url, text) for text, url in pairs if url
    ]
    return results[:top_n]
