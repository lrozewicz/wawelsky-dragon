"""Konektor SharePoint: port `Connector` na warstwie Graph (WP E4-2b; 09 §7, §9, §10)."""

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx

from app.integrations.base import ChangeSet, ConnectionReport, Container, RemoteItem
from app.integrations.sharepoint.auth import LOGIN_BASE_URL, TokenProvider
from app.integrations.sharepoint.config import SharePointConfig
from app.integrations.sharepoint.errors import GraphAuthError, GraphError, GraphNotFound
from app.integrations.sharepoint.graph import GRAPH_BASE_URL, GraphClient, make_http_client
from app.integrations.sharepoint.graph_delta import decode_item

DATASET_NOT_FOUND = "dataset not found"


class SharePointConnector:
    """Biblioteki dokumentów SharePoint przez Microsoft Graph; każda metoda ma własny klient."""

    type = "sharepoint"

    def __init__(
        self,
        http_factory: Callable[[], httpx.AsyncClient] | None = None,
        *,
        login_base_url: str = LOGIN_BASE_URL,
        graph_base_url: str = GRAPH_BASE_URL,
    ) -> None:
        self._http_factory = (
            http_factory if http_factory is not None else lambda: make_http_client(graph_base_url)
        )
        self._login_base_url = login_base_url

    def _client(self, cfg: SharePointConfig) -> tuple[TokenProvider, GraphClient]:
        """Buduje parę tokeny/klient Graph; wołający zamyka klienta przez `graph.aclose()`."""
        http = self._http_factory()
        tokens = TokenProvider(
            http,
            tenant_id=cfg.tenant_id,
            client_id=cfg.client_id,
            client_secret=cfg.client_secret.get_secret_value(),
            login_base_url=self._login_base_url,
        )
        return tokens, GraphClient(http, tokens)

    async def test_connection(
        self, cfg: SharePointConfig, *, dataset_exists: bool
    ) -> ConnectionReport:
        """Sekwencyjne kroki testu połączenia: token, site + biblioteki, dataset."""
        tokens, graph = self._client(cfg)
        try:
            try:
                await tokens.get_token()
            except GraphAuthError as exc:
                # Wczesny powrót: bez tokenu dalsze kroki nie mają czego sprawdzać.
                return ConnectionReport(
                    ok=False,
                    checks=[{"name": "graph_auth", "status": "failed", "detail": str(exc)}],
                    resolved={},
                )
            checks: list[dict[str, object]] = [{"name": "graph_auth", "status": "ok", "detail": ""}]
            resolved: dict[str, object] = {}
            try:
                site_id, site_name = await graph.resolve_site(cfg.site_url)
                containers, total = await graph.list_drives(site_id, cfg.excluded_library_names)
            except (GraphError, ValueError) as exc:
                checks.append({"name": "site_resolution", "status": "failed", "detail": str(exc)})
            else:
                checks.append({"name": "site_resolution", "status": "ok", "detail": ""})
                resolved = {
                    "site_id": site_id,
                    "site_display_name": site_name,
                    "libraries_total": total,
                    "libraries_included": len(containers),
                }
            checks.append(self._dataset_check(dataset_exists))
            ok = all(check["status"] == "ok" for check in checks)
            return ConnectionReport(ok=ok, checks=checks, resolved=resolved)
        finally:
            await graph.aclose()

    @staticmethod
    def _dataset_check(dataset_exists: bool) -> dict[str, object]:
        """Krok 3 testu połączenia: dataset sprawdza lokalnie wołający (E4-3)."""
        if dataset_exists:
            return {"name": "dataset_exists", "status": "ok", "detail": ""}
        return {"name": "dataset_exists", "status": "failed", "detail": DATASET_NOT_FOUND}

    async def resolve(self, cfg: SharePointConfig) -> dict[str, Any]:
        """Identyfikator i nazwa witryny z `site_url` (zawsze przez Graph)."""
        _, graph = self._client(cfg)
        try:
            site_id, site_name = await graph.resolve_site(cfg.site_url)
            return {"site_id": site_id, "site_display_name": site_name}
        finally:
            await graph.aclose()

    async def list_containers(self, cfg: SharePointConfig) -> list[Container]:
        """Biblioteki witryny po filtrze `system` i wykluczeniach z konfiguracji."""
        _, graph = self._client(cfg)
        try:
            site_id = cfg.site_id
            if site_id is None:
                site_id, _ = await graph.resolve_site(cfg.site_url)
            containers, _ = await graph.list_drives(site_id, cfg.excluded_library_names)
            return containers
        finally:
            await graph.aclose()

    async def changes(
        self, cfg: SharePointConfig, container: Container, cursor: str | None
    ) -> AsyncIterator[ChangeSet]:
        """Strumień zmian biblioteki; klient zamykany także po przerwaniu odbioru."""
        _, graph = self._client(cfg)
        try:
            async for change_set in graph.delta(container.id, cursor):
                yield change_set
        finally:
            await graph.aclose()

    async def download(
        self, cfg: SharePointConfig, item: RemoteItem, dest_path: Path, *, max_bytes: int
    ) -> int:
        """Pobiera zawartość elementu na dysk; zwraca rozmiar w bajtach."""
        _, graph = self._client(cfg)
        try:
            size, _ = await graph.download(item.container_id, item.item_id, dest_path, max_bytes)
            return size
        finally:
            await graph.aclose()

    async def web_link(
        self, cfg: SharePointConfig, container_id: str, item_id: str
    ) -> RemoteItem | None:
        """Aktualny stan elementu dla linku źródłowego; brak elementu (404/410) → `None`."""
        _, graph = self._client(cfg)
        try:
            raw = await graph.get_item(container_id, item_id)
        except GraphNotFound:
            return None
        finally:
            await graph.aclose()
        return decode_item(raw, container_id)
