"""Pętla kontenera przebiegu: elementy, kursor, reset delty i rekonsyliacja (kontrakt C5, 09 §6).

Wydzielone z ``engine.py`` (limit 400 linii/plik). Obsługuje jedno przejście ``changes`` kontenera,
``reset_required`` z pełnym przejściem i rekonsyliacją usunięć, kontenery zniknięte ze źródła oraz
anulowanie kooperacyjne przez ``integrations.cancel_requested`` sprawdzane między elementami.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import integrations as repo
from app.db.uow import transaction
from app.integrations.audit import RunRecorder
from app.integrations.base import ChangeSet, RemoteItem
from app.integrations.engine_items import ItemProcessor

if TYPE_CHECKING:
    from app.core.container import Container
    from app.db.repositories.integrations import ContainerRow, IntegrationRow, MappingRow
    from app.integrations.base import Connector
    from app.integrations.base import Container as RemoteContainer
    from app.integrations.config import IntegrationsConfig


class RunCancelled(Exception):
    """Anulowanie kooperacyjne (``cancel_requested``) — status końcowy ``cancelled``."""


class ContainerSyncer:
    """Przetwarza kontenery przebiegu wg 09 §6 (kontrakt C5, brief T8).

    Stan obiektu jest stały dla przebiegu (integracja, konektor, rekorder, procesor elementów).
    """

    def __init__(  # noqa: PLR0913 — kształt kontraktu C5 (kontekst przebiegu)
        self,
        container: Container,
        config: IntegrationsConfig,
        *,
        row: IntegrationRow,
        connector: Connector,
        cfg: object,
        recorder: RunRecorder,
        processor: ItemProcessor,
        worker_id: str,
    ) -> None:
        self._container = container
        self._config = config
        self._row = row
        self._connector = connector
        self._cfg = cfg
        self._recorder = recorder
        self._processor = processor
        self._worker_id = worker_id

    async def sync_all(self, remote_containers: Sequence[RemoteContainer]) -> None:
        """Kontenery zniknięte (pkt 4), potem każdy kontener zdalny (pkt 1-3)."""
        await self._purge_missing(remote_containers)
        for remote in remote_containers:
            await self.sync_container(remote)

    async def sync_container(self, remote: RemoteContainer) -> None:
        """Jedno przejście ``changes`` kontenera: elementy, reset delty, kursor, rekonsyliacja."""
        self._recorder.event(
            "info",
            f"container start: {remote.name}",
            container_id=remote.id,
            container_name=remote.name,
        )
        cursor = await self._container_cursor(remote.id)
        last_cursor = cursor
        last_heartbeat_ms = self._now()
        seen: set[str] | None = None
        async for changeset in self._connector.changes(self._cfg, remote, cursor):
            if changeset.reset_required:
                await self._reset_delta(remote)
                seen = set()
                last_cursor, last_heartbeat_ms = await self._consume(
                    self._connector.changes(self._cfg, remote, None), last_heartbeat_ms, seen
                )
                break
            if changeset.cursor is not None:
                last_cursor = changeset.cursor
            last_heartbeat_ms = await self._consume_items(changeset.items, last_heartbeat_ms, None)
        await self._set_cursor(remote.id, cursor=last_cursor)
        if seen is not None:  # rekonsyliacja tylko po przejściu po resecie (pkt 3)
            await self._reconcile(remote, seen)
        self._recorder.event(
            "info",
            f"container done: {remote.name}",
            container_id=remote.id,
            container_name=remote.name,
        )

    async def _consume(
        self, pages: AsyncIterator[ChangeSet], last_heartbeat_ms: int, seen: set[str]
    ) -> tuple[str | None, int]:
        """Pełne przejście po resecie: strony, kursor i zbiór widzianych ``item_id``."""
        last_cursor: str | None = None
        async for changeset in pages:
            if changeset.cursor is not None:
                last_cursor = changeset.cursor
            last_heartbeat_ms = await self._consume_items(changeset.items, last_heartbeat_ms, seen)
        return last_cursor, last_heartbeat_ms

    async def _consume_items(
        self, items: Sequence[RemoteItem], last_heartbeat_ms: int, seen: set[str] | None
    ) -> int:
        """Elementy jednej strony: anulowanie, zbiór pełnego stanu, heartbeat, decyzja."""
        for item in items:
            await self._check_cancel()
            if seen is not None and not item.is_folder and not item.deleted:
                seen.add(item.item_id)
            last_heartbeat_ms = await self._between_items(last_heartbeat_ms)
            await self._processor.process(item)
        return last_heartbeat_ms

    async def _reconcile(self, remote: RemoteContainer, seen: set[str]) -> None:
        """Rekonsyliacja po resecie: mappingi nieobecne w pełnym stanie idą ścieżką wiersza 2."""
        for mapping in await self._list_mappings(remote.id):
            if mapping.item_id in seen:
                continue
            await self._check_cancel()
            await self._processor.reconcile_deleted(mapping)

    async def _purge_missing(self, remote_containers: Sequence[RemoteContainer]) -> None:
        """Kontenery z bazy nieobecne u źródła: ``warn`` i opcjonalne czyszczenie (pkt 4)."""
        remote_ids = {container.id for container in remote_containers}
        for stored in await self._list_stored_containers():
            if stored.container_id in remote_ids:
                continue
            self._recorder.event(
                "warn",
                f"container no longer available: {stored.name}",
                container_id=stored.container_id,
                container_name=stored.name,
            )
            if not self._config.purge_excluded_containers:
                continue
            for mapping in await self._list_mappings(stored.container_id):
                await self._processor.reconcile_deleted(mapping)

    async def _reset_delta(self, remote: RemoteContainer) -> None:
        """Zeruje kursor kontenera po ``reset_required`` i zapisuje zdarzenie ``warn`` (pkt 3)."""
        self._recorder.event(
            "warn",
            f"delta token expired, full resync of {remote.name}",
            container_id=remote.id,
            container_name=remote.name,
        )
        async with transaction(self._sessionmaker()) as session:
            await repo.set_container_cursor(
                session, self._row.id, remote.id, cursor=None, now_ms=self._now()
            )

    async def _check_cancel(self) -> None:
        """Przed każdym elementem: ``cancel_requested`` w krótkiej transakcji (pkt 1)."""
        async with transaction(self._sessionmaker()) as session:
            cancelled: bool = await repo.is_cancel_requested(session, self._row.id)
        if cancelled:
            self._recorder.event("warn", "cancelled")
            raise RunCancelled

    async def _between_items(self, last_heartbeat_ms: int) -> int:
        """Między elementami: flush bufora zdarzeń i odświeżenie locka (kontrakt C4/C6)."""
        await self._recorder.maybe_flush()
        now_ms = self._now()
        if now_ms - last_heartbeat_ms < self._config.heartbeat_seconds * 1000:
            return last_heartbeat_ms
        async with transaction(self._sessionmaker()) as session:
            await repo.heartbeat_lock(session, self._row.id, owner=self._worker_id, now_ms=now_ms)
        return now_ms

    async def _list_stored_containers(self) -> list[ContainerRow]:
        """Kontenery zapisane w bazie po ``container_id`` (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            return await repo.list_containers(session, self._row.id)

    async def _list_mappings(self, container_id: str) -> list[MappingRow]:
        """Mappingi kontenera po ``item_id`` (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            return await repo.list_mappings(session, self._row.id, container_id)

    async def _container_cursor(self, container_id: str) -> str | None:
        """Zapisany ``delta_cursor`` kontenera (``None``, gdy kontener nieznany) (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            row: ContainerRow | None = await repo.get_container(session, self._row.id, container_id)
        return None if row is None else row.delta_cursor

    async def _set_cursor(self, container_id: str, cursor: str | None) -> None:
        """Zapisuje ``delta_cursor`` i ``last_sync_at`` kontenera (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            await repo.set_container_cursor(
                session, self._row.id, container_id, cursor=cursor, now_ms=self._now()
            )

    def _now(self) -> int:
        """Czas z zegara kontenera (kontrakt C5)."""
        return self._container.clock.now_ms()

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (wzorzec ``RunRecorder._sessionmaker``)."""
        return cast("async_sessionmaker[AsyncSession]", self._container.sessionmaker)
