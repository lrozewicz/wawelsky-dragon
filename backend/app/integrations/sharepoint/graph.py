"""Klient Microsoft Graph: retry z 401-refresh, site, drives, get_item (WP E4-2a, 09 §7.1-§7.3)."""

import asyncio
import logging
import random
import urllib.parse
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from app.integrations.base import ChangeSet, Container
from app.integrations.sharepoint.auth import TokenProvider
from app.integrations.sharepoint.errors import GraphError, GraphNotFound
from app.integrations.sharepoint.graph_delta import iter_delta
from app.integrations.sharepoint.graph_download import download_item
from app.integrations.sharepoint.log_redact import install_httpx_log_redaction

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
MAX_ATTEMPTS = 5
DELTA_SELECT = (
    "id,name,size,file,folder,deleted,cTag,eTag,parentReference,webUrl,lastModifiedDateTime"
)

RETRY_STATUSES = frozenset(
    {httpx.codes.TOO_MANY_REQUESTS, httpx.codes.SERVICE_UNAVAILABLE, httpx.codes.GATEWAY_TIMEOUT}
)
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
NOT_FOUND_STATUSES = frozenset({httpx.codes.NOT_FOUND, httpx.codes.GONE})

logger = logging.getLogger("app.integrations.sharepoint")


def make_http_client(graph_base_url: str = GRAPH_BASE_URL) -> httpx.AsyncClient:
    """Klient HTTP/1.1 pod podanym `graph_base_url` bez automatycznych przekierowań."""
    install_httpx_log_redaction()
    return httpx.AsyncClient(
        base_url=graph_base_url,
        timeout=httpx.Timeout(30.0, read=120.0),
        follow_redirects=False,
    )


def _json_object(response: httpx.Response) -> dict[str, Any]:
    """Body odpowiedzi jako obiekt; puste, gdy treść nie jest obiektem JSON."""
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_fields(response: httpx.Response) -> tuple[str, str]:
    """`(code, message)` z body `{"error": {...}}`; brak danych → `("", reason_phrase)`."""
    error = _json_object(response).get("error")
    if not isinstance(error, dict):
        return "", response.reason_phrase
    code = error.get("code")
    message = error.get("message")
    return (
        code if isinstance(code, str) else "",
        message if isinstance(message, str) else response.reason_phrase,
    )


def _retry_delay(attempt: int, retry_after: str | None, jitter: float) -> float:
    """Opóźnienie retry: liczbowe `Retry-After`, inaczej backoff wykładniczy z jitterem."""
    backoff: float = min(2 ** (attempt - 1), 30) + jitter
    if retry_after is None:
        return backoff
    try:
        return float(retry_after)
    except ValueError:
        return backoff


class GraphClient:
    """Cienki klient Graph z ponowieniami, odświeżaniem 401 i paginacją drives."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        tokens: TokenProvider,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.http = http
        self._tokens = tokens
        self._sleep = sleep
        self._jitter = jitter

    async def request(
        self, method: str, url: str, *, params: Mapping[str, str] | None = None
    ) -> httpx.Response:
        """Wykonuje żądanie z retry; zwraca wyłącznie odpowiedzi 2xx."""
        return await self._send(method, url, params, accept_redirect=False)

    async def request_redirect(self, url: str) -> httpx.Response:
        """GET jak `request`, ale zwraca także 301/302/303/307/308 (do pobierania treści)."""
        return await self._send("GET", url, None, accept_redirect=True)

    async def _send(
        self,
        method: str,
        url: str,
        params: Mapping[str, str] | None,
        *,
        accept_redirect: bool,
    ) -> httpx.Response:
        attempt = 0
        refreshed = False
        while True:
            attempt += 1
            token = await self._tokens.get_token()
            headers = {"Authorization": f"Bearer {token}"}
            try:
                response = await self.http.request(method, url, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt >= MAX_ATTEMPTS:
                    raise GraphError(0, "transport", type(exc).__name__) from exc
                await self._wait(0, attempt, None)
                continue

            status = response.status_code
            if status == httpx.codes.UNAUTHORIZED:
                if refreshed or attempt >= MAX_ATTEMPTS:
                    raise self._graph_error(response)
                refreshed = True
                await self._tokens.get_token(force_refresh=True)
                continue
            if accept_redirect and status in REDIRECT_STATUSES:
                return response
            if status in RETRY_STATUSES:
                if attempt >= MAX_ATTEMPTS:
                    raise self._graph_error(response)
                await self._wait(status, attempt, response.headers.get("Retry-After"))
                continue
            if status in NOT_FOUND_STATUSES:
                raise self._not_found(response)
            if httpx.codes.OK <= status < httpx.codes.MULTIPLE_CHOICES:
                return response
            raise self._graph_error(response)

    async def _wait(self, status: int, attempt: int, retry_after: str | None) -> None:
        delay = _retry_delay(attempt, retry_after, self._jitter())
        logger.warning("graph retry status=%s attempt=%s delay=%.1f", status, attempt, delay)
        await self._sleep(delay)

    @staticmethod
    def _graph_error(response: httpx.Response) -> GraphError:
        code, message = _error_fields(response)
        return GraphError(response.status_code, code, message)

    @staticmethod
    def _not_found(response: httpx.Response) -> GraphNotFound:
        code, message = _error_fields(response)
        return GraphNotFound(response.status_code, code, message)

    async def resolve_site(self, site_url: str) -> tuple[str, str]:
        """Zwraca `(site_id, display_name)` dla adresu witryny SharePoint."""
        parsed = urllib.parse.urlparse(site_url)
        hostname = parsed.hostname
        if hostname is None:
            raise ValueError("invalid site_url")
        site_path = parsed.path.strip("/")
        url = f"/sites/{hostname}:/{site_path}" if site_path else f"/sites/{hostname}"
        response = await self.request("GET", url)
        body: dict[str, Any] = response.json()
        name = body.get("displayName") or body.get("name") or ""
        return str(body["id"]), str(name)

    async def list_drives(
        self, site_id: str, excluded: Sequence[str]
    ) -> tuple[list[Container], int]:
        """Biblioteki witryny bez `system`; `total` przed wykluczeniem po nazwie."""
        url: str | None = f"/sites/{site_id}/drives"
        containers: list[Container] = []
        total = 0
        while url is not None:
            response = await self.request("GET", url)
            body: dict[str, Any] = response.json()
            for drive in body.get("value", []):
                if "system" in drive:
                    continue
                total += 1
                name = str(drive["name"])
                if name not in excluded:
                    containers.append(Container(id=str(drive["id"]), name=name))
            url = body.get("@odata.nextLink")
        return containers, total

    def delta(
        self, drive_id: str, cursor: str | None, *, max_pages: int = 10_000
    ) -> AsyncIterator[ChangeSet]:
        """Deleguje do `graph_delta.iter_delta` (implementacja w T3)."""
        return iter_delta(self, drive_id, cursor, max_pages)

    async def get_item(self, drive_id: str, item_id: str) -> dict[str, Any]:
        """Surowy driveItem jako dict; 404/410 → `GraphNotFound`."""
        response = await self.request("GET", f"/drives/{drive_id}/items/{item_id}")
        body: dict[str, Any] = response.json()
        return body

    async def download(
        self, drive_id: str, item_id: str, dest: Path, max_bytes: int
    ) -> tuple[int, str]:
        """Deleguje do `graph_download.download_item` (implementacja w T4)."""
        return await download_item(self, drive_id, item_id, dest, max_bytes)

    async def aclose(self) -> None:
        """Zamyka współdzielony klient HTTP."""
        await self.http.aclose()
