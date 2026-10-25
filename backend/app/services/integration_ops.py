"""Rdzeń usługi integracji: kontener, konektor z rejestru, odczyty i test połączenia.

Wydzielone z ``app/services/integrations.py`` dla twardego limitu 400 linii pliku (brief T2b p. 10).
Klasa ``IntegrationCore`` nie ma ``__init__`` — pola ``_container``, ``_config`` i ``_runs``
ustawia ``IntegrationService`` (podklasa w ``app/services/integrations.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from app.core.errors import NotFound, UpstreamError, ValidationFailed
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import (
    ContainerRow,
    DatasetSummary,
    EventRow,
    IntegrationRow,
    RunRow,
    SharePointRow,
)
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.secrets import decrypt_secret
from app.integrations.sharepoint.config import SharePointConfig
from app.services.integration_input import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    TestConnectionInput,
    TestOverrides,
)
from app.services.integration_test_report import build_report, site_resolution_ok

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.container import Container
    from app.integrations.base import Connector
    from app.integrations.config import IntegrationsConfig
    from app.services.integration_runs import IntegrationRunsService

INTEGRATION_TYPE = "sharepoint"
CONNECTOR_MISSING = "sharepoint connector is not registered"
NOT_FOUND = "Not found"
LOCAL_OK = "ok"
LOCAL_NOT_FOUND = "not_found"
LOCAL_SKIPPED = "skipped"

# Alias na wbudowany ``list``: metoda ``list`` usługi (kontrakt §3) przesłania go w adnotacjach.
_List = list


def _pick[T](new: T | None, current: T) -> T:
    """Wartość z nadpisania, a gdy jej nie ma — zapisana w bazie (kontrakt §3 ``test_saved``)."""
    return current if new is None else new


@dataclass(frozen=True)
class Actor:
    """Wykonawca operacji (K7 część 2 §7 p. 13): etykieta z ciała żądania albo ``X-API-Secret``."""

    label: str
    id: str | None = None
    ip: str | None = None


@dataclass(frozen=True)
class IntegrationView:
    """Integracja: wiersz ``integrations`` + jej konfiguracja SharePoint (kontrakt §3)."""

    row: IntegrationRow
    sharepoint: SharePointRow


@dataclass(frozen=True)
class StatusView:
    """Stan integracji i jej ostatni przebieg (``GET /api/integrations/{id}/status``)."""

    row: IntegrationRow
    latest_run: RunRow | None


@dataclass(frozen=True)
class SyncOutcome:
    """Wynik zlecenia; ``run`` wypełniony tylko dla ``wait=True`` zakończonego w czasie."""

    started: bool
    full: bool
    run: RunRow | None


class IntegrationCore:
    """Dostęp do kontenera i konektora, odczyty oraz test połączenia (kontrakt E4-3a §3)."""

    _container: Container
    _config: IntegrationsConfig
    _runs: IntegrationRunsService

    # --- odczyty ------------------------------------------------------------------

    async def list(self) -> _List[IntegrationView]:
        """Wszystkie integracje z konfiguracją SharePoint, malejąco po ``id``."""
        async with transaction(self._sm()) as session:
            rows = await integrations_repo.list_integrations(session)
            return [await self._view(session, row) for row in rows]

    async def get(self, integration_id: int) -> IntegrationView:
        """Integracja po ``id``; brak → ``NotFound("Not found")``."""
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
            if row is None:
                raise NotFound(NOT_FOUND)
            return await self._view(session, row)

    async def status(self, integration_id: int) -> StatusView:
        """Stan integracji + ostatni przebieg (``GET /api/integrations/{id}/status``)."""
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
            if row is None:
                raise NotFound(NOT_FOUND)
            latest = await integrations_repo.latest_run(session, integration_id)
        return StatusView(row=row, latest_run=latest)

    async def drives(self, integration_id: int) -> _List[ContainerRow]:
        """Kontenery integracji rosnąco po nazwie (03 §5 ``drive_dto``)."""
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
            if row is None:
                raise NotFound(NOT_FOUND)
            containers = await integrations_repo.list_containers(session, integration_id)
        return sorted(containers, key=lambda container: container.name)

    async def list_runs(
        self,
        *,
        integration_type: str | None,
        integration_id: int | None,
        limit: int,
        before_id: int | None = None,
    ) -> _List[RunRow]:
        """Przebiegi malejąco po ``id``, z filtrami trasy (``GET /api/integrations/runs``)."""
        async with transaction(self._sm()) as session:
            return await integrations_repo.list_runs(
                session,
                integration_type=integration_type,
                integration_id=integration_id,
                limit=limit,
                before_id=before_id,
            )

    async def list_events(
        self, run_id: int, *, after_id: int, level: str | None, limit: int
    ) -> _List[EventRow]:
        """Zdarzenia przebiegu (``GET /api/integrations/runs/{run_id}/events``)."""
        async with transaction(self._sm()) as session:
            return await integrations_repo.list_events_page(
                session, run_id, after_id=after_id, level=level, limit=limit
            )

    async def list_datasets(self) -> _List[DatasetSummary]:
        """Wszystkie datasety (``GET /api/datasets``, K7 część 2 §7 p. 11)."""
        async with transaction(self._sm()) as session:
            return await integrations_repo.list_dataset_summaries(session)

    # --- test połączenia ----------------------------------------------------------

    async def test_connection(self, data: TestConnectionInput) -> dict[str, object]:
        """Etapy ``graph_auth`` → ``site_resolution`` → ``dataset_exists`` (09 §10, 03 §5)."""
        cfg = self._sharepoint_cfg(
            0,
            tenant_id=data.tenant_id,
            client_id=data.client_id,
            client_secret=data.client_secret,
            site_url=data.site_url,
            site_id=None,
            excluded_library_names=data.excluded_library_names,
            max_file_size_bytes=DEFAULT_MAX_FILE_SIZE_BYTES,
        )
        return await self._run_connection_test(cfg, data.dataset_id)

    async def test_saved(self, integration_id: int, overrides: TestOverrides) -> dict[str, object]:
        """Test połączenia zapisanej integracji; nadpisania pól bez zapisu (kontrakt §3).

        Brak integracji → ``NotFound``; brak zapisanego sekretu → ``ValidationFailed``;
        sekret z nadpisania albo odszyfrowany z wiersza. Zero zapisu do bazy i audytu.
        """
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
            if row is None:
                raise NotFound(NOT_FOUND)
            sharepoint = await self._sharepoint_row(session, integration_id)
        if row.secret_enc is None:
            raise ValidationFailed("Integration has no stored secret.")
        secret = overrides.client_secret
        if secret is None:
            secret = decrypt_secret(self._key(), row.id, row.secret_enc)
        cfg = self._sharepoint_cfg(
            row.id,
            tenant_id=_pick(overrides.tenant_id, sharepoint.tenant_id),
            client_id=_pick(overrides.client_id, sharepoint.client_id),
            client_secret=secret,
            site_url=_pick(overrides.site_url, sharepoint.site_url),
            site_id=None,
            excluded_library_names=_pick(
                overrides.excluded_library_names, sharepoint.excluded_library_names
            ),
            max_file_size_bytes=DEFAULT_MAX_FILE_SIZE_BYTES,
        )
        return await self._run_connection_test(cfg, _pick(overrides.dataset_id, row.dataset_id))

    async def _run_connection_test(
        self, cfg: SharePointConfig, dataset_id: str | None
    ) -> dict[str, object]:
        """Wspólna ścieżka testu: lokalny dataset → konektor → ``build_report`` (kontrakt §3)."""
        local: tuple[str, str | None] = (LOCAL_SKIPPED, None)
        if dataset_id is not None:
            async with transaction(self._sm()) as session:
                dataset = await datasets_repo.get(session, dataset_id)
            local = (LOCAL_OK, dataset.name) if dataset is not None else (LOCAL_NOT_FOUND, None)
        connector = self._connector()
        report = await connector.test_connection(cfg, dataset_exists=local[0] == LOCAL_OK)
        containers = await connector.list_containers(cfg) if site_resolution_ok(report) else None
        return build_report(report, containers=containers, local_dataset=local)

    # --- pomocnicze ---------------------------------------------------------------

    def _sm(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera; brak (kontener nie wystartował) → ``RuntimeError``."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        return sessionmaker

    def _key(self) -> str:
        """Klucz szyfrowania sekretów z ustawień kontenera (09 §11)."""
        return self._container.settings.crypto_key.get_secret_value()

    def _now_ms(self) -> int:
        """Bieżący czas zegara kontenera w milisekundach."""
        return self._container.clock.now_ms()

    def _connector(self) -> Connector:
        """Konektor typu ``sharepoint`` z rejestru; brak rejestracji → ``UpstreamError``."""
        try:
            connector, _ = registry.get(INTEGRATION_TYPE)
        except KeyError as exc:
            raise UpstreamError(CONNECTOR_MISSING) from exc
        return connector

    def _sharepoint_cfg(  # noqa: PLR0913 — kształt ``SharePointConfig`` (kontrakt §3 create p. 3)
        self,
        integration_id: int,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        site_url: str,
        site_id: str | None,
        excluded_library_names: _List[str],
        max_file_size_bytes: int,
    ) -> SharePointConfig:
        """Konfiguracja konektora; plaintext sekretu żyje tylko w tym obiekcie (``SecretStr``)."""
        return SharePointConfig(
            integration_id=integration_id,
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=SecretStr(client_secret),
            site_url=site_url,
            site_id=site_id,
            excluded_library_names=excluded_library_names,
            max_file_size_bytes=max_file_size_bytes,
        )

    async def _resolve(self, connector: Connector, cfg: SharePointConfig) -> dict[str, Any]:
        """``resolve`` konektora; każdy błąd Graph → 400 „Cannot save: …” (kontrakt §3)."""
        try:
            return await connector.resolve(cfg)
        except Exception as exc:
            raise ValidationFailed(f"Cannot save: {exc}. Run test-connection first.") from exc

    async def _sharepoint_row(self, session: AsyncSession, integration_id: int) -> SharePointRow:
        """Wiersz ``integration_sharepoint``; brak = wiersz nie jest integracją SharePoint."""
        sharepoint = await integrations_repo.get_sharepoint(session, integration_id)
        if sharepoint is None:
            raise NotFound(NOT_FOUND)
        return sharepoint

    async def _view(self, session: AsyncSession, row: IntegrationRow) -> IntegrationView:
        """Widok integracji: wiersz + konfiguracja SharePoint (bez sekretu)."""
        return IntegrationView(row=row, sharepoint=await self._sharepoint_row(session, row.id))
