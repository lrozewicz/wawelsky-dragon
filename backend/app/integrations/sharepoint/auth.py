"""Token aplikacji Graph (client credentials) z cache modułowym (WP E4-2a, 09 §7.1)."""

import asyncio
import hashlib
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.integrations.sharepoint.errors import GraphAuthError

LOGIN_BASE_URL = "https://login.microsoftonline.com"
TOKEN_URL_TEMPLATE = LOGIN_BASE_URL + "/{tenant_id}/oauth2/v2.0/token"
SCOPE = "https://graph.microsoft.com/.default"
REFRESH_MARGIN_S = 60

# Cache modułowy: (tenant_id, client_id, sha256(client_secret)) -> (access_token, expires_at).
# Skrót sekretu w kluczu rozdziela wpisy dla różnych poświadczeń tej samej pary tenant/client;
# sam sekret nigdy nie trafia do klucza.
_token_cache: dict[tuple[str, str, str], tuple[str, float]] = {}


def clear_token_cache() -> None:
    """Czyści modułowy cache tokenów (testy oraz zmiana konfiguracji)."""
    _token_cache.clear()


def _json_body(response: httpx.Response) -> dict[str, Any]:
    """Body odpowiedzi jako dict; puste, gdy treść nie jest obiektem JSON."""
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_description(body: dict[str, Any], status: int) -> str:
    """`error_description` z body, a gdy go brak — krótki opis ze statusem HTTP."""
    description = body.get("error_description")
    if isinstance(description, str) and description:
        return description
    return f"token endpoint returned HTTP {status}"


class TokenProvider:
    """Pobiera i cache'uje token aplikacji dla jednej pary (tenant_id, client_id)."""

    def __init__(  # noqa: PLR0913 — sygnatura z kontraktu C2 (WP E4-3d)
        self,
        http: httpx.AsyncClient,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        login_base_url: str = LOGIN_BASE_URL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._login_base_url = login_base_url
        self._clock = clock
        self._lock = asyncio.Lock()

    def _cache_key(self) -> tuple[str, str, str]:
        """Klucz wpisu cache: para tenant/client plus skrót sekretu (nigdy sam sekret)."""
        secret_hash = hashlib.sha256(self._client_secret.encode()).hexdigest()
        return (self._tenant_id, self._client_id, secret_hash)

    async def get_token(self, *, force_refresh: bool = False) -> str:
        """Zwraca ważny token; cache jest wspólny dla instancji o tym samym kluczu."""
        key = self._cache_key()
        async with self._lock:
            if not force_refresh:
                cached = _token_cache.get(key)
                if cached is not None and self._clock() < cached[1] - REFRESH_MARGIN_S:
                    return cached[0]
            return await self._fetch(key)

    def invalidate(self) -> None:
        """Usuwa wpis cache tego (tenant_id, client_id, skrót sekretu)."""
        _token_cache.pop(self._cache_key(), None)

    async def _fetch(self, key: tuple[str, str, str]) -> str:
        url = f"{self._login_base_url}/{self._tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": SCOPE,
            "grant_type": "client_credentials",
        }
        try:
            response = await self._http.post(url, data=data)
        except httpx.TransportError as exc:
            raise GraphAuthError("token endpoint unreachable") from exc

        body = _json_body(response)
        token = body.get("access_token")
        if response.status_code != httpx.codes.OK or not isinstance(token, str):
            raise GraphAuthError(_error_description(body, response.status_code))

        expires_at = self._clock() + float(body.get("expires_in", 0))
        _token_cache[key] = (token, expires_at)
        return token
