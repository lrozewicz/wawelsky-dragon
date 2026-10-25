"""Klient REST API v2 RunPod (https://docs.runpod.io/api-reference-v2/overview).

Tylko to, czego potrzebuje WD: katalog GPU i centrów danych, tworzenie, odczyt i kasowanie poda.
Klient ``httpx`` jest wstrzykiwany w testach (``httpx.MockTransport``). Klucz API nie trafia do
komunikatów błędów ani do logów.
"""

from __future__ import annotations

from typing import Any

import httpx

API_BASE = "https://api.runpod.io/v2"
DEFAULT_TIMEOUT_S = 30.0
HTTP_NOT_FOUND = 404

# Fragmenty komunikatów RunPod oznaczające brak wolnych maszyn (nie błąd żądania).
_CAPACITY_HINTS = (
    "no instances",
    "no available",
    "not available",
    "unavailable",
    "insufficient",
    "out of stock",
    "capacity",
    "no resources",
    "could not find any pods",
)


class RunpodError(Exception):
    """Błąd wywołania API RunPod; ``status`` to kod HTTP (0 przy błędzie sieci)."""

    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class RunpodAuthError(RunpodError):
    """Klucz API odrzucony (401/403)."""


class RunpodCapacityError(RunpodError):
    """Wybrane GPU nie jest teraz dostępne w żadnym z dozwolonych centrów danych."""


def _message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        for key in ("detail", "message", "error", "title"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:300]
    return str(body)[:300]


class RunpodClient:
    """Cienka warstwa nad ``httpx`` z klasyfikacją błędów (auth, brak mocy, reszta)."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = API_BASE,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client
        self._timeout_s = timeout_s

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            if self._client is not None:
                response = await self._client.request(
                    method, url, headers=self._headers, params=params, json=json
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                    response = await client.request(
                        method, url, headers=self._headers, params=params, json=json
                    )
        except httpx.HTTPError as exc:
            raise RunpodError(f"RunPod unreachable: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise RunpodAuthError("RunPod rejected the API key", status=response.status_code)
        if response.status_code == HTTP_NOT_FOUND:
            raise RunpodError("not found", status=404)
        if response.status_code >= 400:  # noqa: PLR2004
            message = _message(response)
            if any(hint in message.lower() for hint in _CAPACITY_HINTS):
                raise RunpodCapacityError(message, status=response.status_code)
            raise RunpodError(message, status=response.status_code)
        if not response.content:
            return None
        return response.json()

    async def verify(self) -> None:
        """Sprawdza klucz (lista podów, 1 pozycja); ``RunpodAuthError`` przy złym kluczu."""
        await self._request("GET", "/pods", params={"limit": 1})

    async def list_gpus(
        self, *, cloud: str = "SECURE", country_codes: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Katalog GPU z dostępnością dla podów (``GET /catalog/gpus``)."""
        params: dict[str, Any] = {"include": "AVAILABILITY", "product": "POD", "cloud": cloud}
        if country_codes:
            params["countryCodes"] = ",".join(country_codes)
        payload = await self._request("GET", "/catalog/gpus", params=params)
        return list(payload.get("gpus", [])) if isinstance(payload, dict) else []

    async def list_data_centers(self) -> list[dict[str, Any]]:
        """Centra danych z regionem (``GET /catalog/datacenters``)."""
        payload = await self._request("GET", "/catalog/datacenters")
        return list(payload.get("dataCenters", [])) if isinstance(payload, dict) else []

    async def create_pod(self, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /pods`` — zaczyna naliczanie kosztów; brak mocy → ``RunpodCapacityError``."""
        payload = await self._request("POST", "/pods", json=body)
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RunpodError("RunPod returned no pod id")
        return payload

    async def get_pod(self, pod_id: str) -> dict[str, Any] | None:
        """``GET /pods/{id}``; ``None``, gdy poda już nie ma (skasowany)."""
        try:
            payload = await self._request("GET", f"/pods/{pod_id}")
        except RunpodError as exc:
            if exc.status == HTTP_NOT_FOUND:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    async def delete_pod(self, pod_id: str) -> None:
        """``DELETE /pods/{id}`` — kasuje poda (koniec kosztów); brak poda nie jest błędem."""
        try:
            await self._request("DELETE", f"/pods/{pod_id}")
        except RunpodError as exc:
            if exc.status != HTTP_NOT_FOUND:
                raise
