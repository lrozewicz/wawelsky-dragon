"""Dostawca `tavily`: `POST https://api.tavily.com/search` (CONTRACT E6-3f §C4, K18 §5).

Klucz idzie w nagłówku `Authorization: Bearer <key>` (i tylko tam — `repr` go nie zawiera).
Ciało: `{query, max_results}`; wynik: `results[].{title,url,content}` (pierwsze `top_n`).
`config` może nadpisać `base_url` (testy, §C4).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.web_search._http import DEFAULT_TIMEOUT_S, HttpProvider
from app.services.web_search.types import WebResult, WebSearchUnavailable

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilyProvider(HttpProvider):
    """Dostawca Tavily (§C4)."""

    name = "tavily"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = TAVILY_SEARCH_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._api_key = api_key
        self._url = base_url

    async def search(
        self, query: str, *, top_n: int, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> list[WebResult]:
        """`POST {base_url}` z kluczem w nagłówku → `WebResult` obcięte do `top_n` (§C4)."""
        payload = await self._request_json(
            "POST",
            self._url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json_body={"query": query, "max_results": top_n},
            timeout_s=timeout_s,
        )
        return _results(payload, top_n)


def _results(payload: Any, top_n: int) -> list[WebResult]:
    """Mapuje `results[]` na `WebResult`; niepoprawny kształt → `WebSearchUnavailable` (§C4)."""
    try:
        rows = payload["results"]
        triples = [
            (str(row["title"]), str(row["url"]), str(row["content"]))
            for row in rows
            if row.get("url")
        ]
    except (TypeError, KeyError, AttributeError) as exc:
        raise WebSearchUnavailable("tavily", f"unexpected response: {type(exc).__name__}") from exc
    return [WebResult(title, url, snippet) for title, url, snippet in triples][:top_n]
