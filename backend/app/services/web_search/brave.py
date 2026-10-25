"""Dostawca `brave`: `GET https://api.search.brave.com/res/v1/web/search` (§C4, K18 §5).

Klucz idzie w nagłówku `X-Subscription-Token` (i tylko tam — `repr` go nie zawiera).
Parametry: `q`, `count`; wynik: `web.results[].{title,url,description}` (pierwsze `top_n`).
`config` może nadpisać `base_url` (testy, §C4).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.web_search._http import DEFAULT_TIMEOUT_S, HttpProvider
from app.services.web_search.types import WebResult, WebSearchUnavailable

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveProvider(HttpProvider):
    """Dostawca Brave Search (§C4)."""

    name = "brave"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BRAVE_SEARCH_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._api_key = api_key
        self._url = base_url

    async def search(
        self, query: str, *, top_n: int, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> list[WebResult]:
        """`GET {base_url}` z kluczem w nagłówku → `WebResult` obcięte do `top_n` (§C4)."""
        payload = await self._request_json(
            "GET",
            self._url,
            params={"q": query, "count": top_n},
            headers={"X-Subscription-Token": self._api_key},
            timeout_s=timeout_s,
        )
        return _results(payload, top_n)


def _results(payload: Any, top_n: int) -> list[WebResult]:
    """Mapuje `web.results[]` na `WebResult`; zły kształt → `WebSearchUnavailable` (§C4)."""
    try:
        rows = payload["web"]["results"]
        triples = [
            (str(row["title"]), str(row["url"]), str(row["description"]))
            for row in rows
            if row.get("url")
        ]
    except (TypeError, KeyError, AttributeError) as exc:
        raise WebSearchUnavailable("brave", f"unexpected response: {type(exc).__name__}") from exc
    return [WebResult(title, url, snippet) for title, url, snippet in triples][:top_n]
