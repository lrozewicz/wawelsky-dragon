"""Dostawca `searxng`: `GET {base_url}/search?q=&format=json` (CONTRACT E6-3f §C4, K18 §5).

Wynik: `results[].{title,url,content}` (pierwsze `top_n`); wiersz bez `url` pomijamy.
`base_url` pochodzi z `config` dostawcy (seed: `http://searxng:8080`); klient `httpx`
wstrzykiwany w testach.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.web_search._http import DEFAULT_TIMEOUT_S, HttpProvider
from app.services.web_search.types import WebResult, WebSearchUnavailable


class SearxngProvider(HttpProvider):
    """Dostawca oparty o instancję SearXNG (§C4)."""

    name = "searxng"

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(client=client)
        self._base_url = base_url.rstrip("/")

    async def search(
        self, query: str, *, top_n: int, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> list[WebResult]:
        """`GET {base_url}/search` → `WebResult` obcięte do `top_n` (§C4)."""
        payload = await self._request_json(
            "GET",
            f"{self._base_url}/search",
            params={"q": query, "format": "json"},
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
        raise WebSearchUnavailable("searxng", f"unexpected response: {type(exc).__name__}") from exc
    return [WebResult(title, url, snippet) for title, url, snippet in triples][:top_n]
