"""Wspólny transport dostawców wyszukiwania (CONTRACT E6-3f §C4, K18 §5).

Cztery dostawcy (`searxng`, `tavily`, `brave`, `duckduckgo`) dzielą identyczną obsługę
żądania: klient ``httpx`` (wstrzykiwalny w testach), timeout, mapowanie każdego błędu sieci/
timeoutu/HTTP ≥ 400/niepoprawnego JSON na `WebSearchUnavailable`, oraz `__repr__` bez klucza.
Bez tego wspólnego modułu ten kod byłby powielony cztery razy (CLAUDE.md: minimum kodu).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.web_search.types import WebSearchUnavailable

# Domyślny limit czasu żądania (K18 §5, sygnatura `search`).
DEFAULT_TIMEOUT_S = 10.0
# Od tego kodu HTTP traktujemy odpowiedź jako porażkę dostawcy (§C4: „HTTP ≥ 400").
HTTP_ERROR_MIN = 400


class HttpProvider:
    """Podstawa dostawcy: jedno żądanie → JSON albo `WebSearchUnavailable` (§C4).

    `client` wstrzykiwany w testach (`httpx.MockTransport`); ``None`` = klient tworzony per
    żądanie z limitem `timeout_s`. `name` (nazwa dostawcy) ustawiają podklasy.
    """

    name: str = ""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def __repr__(self) -> str:
        """`repr` bez klucza dostawcy — klucz nigdy nie trafia do logu ani diagnostyki (§C4)."""
        return f"<{type(self).__name__} name={self.name}>"

    async def _request_json(  # noqa: PLR0913 — parametry żądania HTTP z §C4
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> Any:
        """Żądanie HTTP → zdekodowany JSON; każdy błąd → `WebSearchUnavailable(name, reason)`."""
        if self._client is not None:
            return await _send(
                self._client,
                self.name,
                method=method,
                url=url,
                params=params,
                headers=headers,
                json_body=json_body,
                timeout_s=timeout_s,
            )
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            return await _send(
                client,
                self.name,
                method=method,
                url=url,
                params=params,
                headers=headers,
                json_body=json_body,
                timeout_s=timeout_s,
            )


async def _send(  # noqa: PLR0913 — parametry żądania HTTP z §C4
    client: httpx.AsyncClient,
    name: str,
    *,
    method: str,
    url: str,
    params: dict[str, Any] | None,
    headers: dict[str, str] | None,
    json_body: dict[str, Any] | None,
    timeout_s: float,
) -> Any:
    """Realizuje żądanie klientem `client`; mapuje błędy transportu/HTTP/JSON (§C4)."""
    try:
        response = await client.request(
            method, url, params=params, headers=headers, json=json_body, timeout=timeout_s
        )
    except httpx.HTTPError as exc:
        raise WebSearchUnavailable(name, type(exc).__name__) from exc
    if response.status_code >= HTTP_ERROR_MIN:
        raise WebSearchUnavailable(name, f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise WebSearchUnavailable(name, "invalid JSON response") from exc
