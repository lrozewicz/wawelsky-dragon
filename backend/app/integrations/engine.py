"""Silnik synchronizacji integracji — przebieg i status końcowy (K12 §5, kontrakt E4-1 C5).

Zakres: lock → ``RunRecorder`` → ``trigger="full"`` (reset kursorów) → lista kontenerów →
elementy wg tabeli decyzji 09 §6 (``engine_items.ItemProcessor``) → status końcowy → zwolnienie
locka. Pętlę kontenera, ``reset_required`` z rekonsyliacją, kontenery zniknięte i anulowanie
kooperacyjne obsługuje ``engine_sync.ContainerSyncer`` (T8).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import integrations as repo
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.audit import RunRecorder
from app.integrations.base import RunStatus, RunTrigger, SyncCounts
from app.integrations.engine_items import ItemProcessor
from app.integrations.engine_sync import ContainerSyncer, RunCancelled

if TYPE_CHECKING:
    from app.core.container import Container
    from app.db.repositories.integrations import IntegrationRow
    from app.integrations.base import Container as RemoteContainer
    from app.integrations.config import IntegrationsConfig

STATUS_FAILED: RunStatus = "failed"
STATUS_PARTIAL: RunStatus = "partial"
STATUS_SUCCESS: RunStatus = "success"
STATUS_CANCELLED: RunStatus = "cancelled"


class RunOutcome(NamedTuple):
    """Wynik przebiegu (kontrakt C5)."""

    run_id: int
    status: RunStatus
    counts: SyncCounts


def final_status(counts: SyncCounts) -> RunStatus:
    """Status przebiegu wg 09 §6 pkt 7: ``failed``/``partial`` zależnie od zmian i błędów."""
    if counts.failed == 0:
        return STATUS_SUCCESS
    changed = counts.added + counts.updated + counts.renamed + counts.deleted
    return STATUS_PARTIAL if changed > 0 else STATUS_FAILED


class SyncEngine:
    """Przebieg synchronizacji jednej integracji (kontrakt C5).

    Instancja nie jest bezpieczna dla równoległych przebiegów tej samej integracji —
    kolejność wywołań pilnuje ``Scheduler`` (T9), a lock pilnuje bazy.
    """

    def __init__(self, container: Container, config: IntegrationsConfig) -> None:
        self._container = container
        self._config = config

    async def run(
        self, integration_id: int, *, trigger: RunTrigger, worker_id: str
    ) -> RunOutcome | None:
        """Przebieg; ``None``, gdy lock zajęty (bez wiersza runu) (kontrakt C5)."""
        now_ms = self._container.clock.now_ms()
        if not await self._acquire_lock(integration_id, owner=worker_id, now_ms=now_ms):
            return None
        row = await self._integration_row(integration_id)
        if row is None:  # integracja zniknęła między wyborem do przebiegu a jego startem
            await self._release_lock(integration_id, owner=worker_id, status=STATUS_FAILED)
            return None
        recorder = RunRecorder(
            self._container, self._config, integration_id=integration_id, integration_type=row.type
        )
        await recorder.start(trigger)
        if trigger == "full":  # pkt 2: reset kursorów przed kontenerami
            await self._reset_cursors(integration_id)
            recorder.event("info", "full resync requested")
        status: RunStatus = STATUS_FAILED
        try:
            await self._sync(row, recorder, worker_id=worker_id)
            status = final_status(recorder.counts)
        except RunCancelled:  # pkt 1: ma pierwszeństwo przed failed/partial/success
            status = STATUS_CANCELLED
        except Exception as exc:  # noqa: BLE001 — błąd przebiegu trafia do audytu i statusu (09 §6)
            recorder.event("error", f"sync failed: {exc}")
        finally:
            # Anulowanie (CancelledError) nie jest łapane jako błąd, ale lock i run wracają.
            await self._finish(integration_id, recorder, status=status, owner=worker_id)
        return RunOutcome(recorder.run_id, status, recorder.counts)

    async def _finish(
        self, integration_id: int, recorder: RunRecorder, *, status: RunStatus, owner: str
    ) -> None:
        """Zamyka przebieg i zwalnia lock — także po wyjątku i anulowaniu (brief T6 pkt 3)."""
        try:
            await recorder.finish(status)
        finally:
            await self._release_lock(integration_id, owner=owner, status=status)

    async def _sync(self, row: IntegrationRow, recorder: RunRecorder, *, worker_id: str) -> None:
        """Kontenery i ich elementy wg 09 §6 (pętla kontenera w ``engine_sync.ContainerSyncer``)."""
        connector, load_config = registry.get(row.type)
        cfg = await load_config(row)
        remote_containers = await connector.list_containers(cfg)
        await self._upsert_containers(row.id, remote_containers)
        syncer = ContainerSyncer(
            self._container,
            self._config,
            row=row,
            connector=connector,
            cfg=cfg,
            recorder=recorder,
            processor=ItemProcessor(
                self._container, integration=row, connector=connector, cfg=cfg, recorder=recorder
            ),
            worker_id=worker_id,
        )
        await syncer.sync_all(remote_containers)

    async def _upsert_containers(
        self, integration_id: int, remote_containers: Sequence[RemoteContainer]
    ) -> None:
        """Dopisuje/odświeża kontenery w jednej krótkiej transakcji (09 §6 pkt 4)."""
        now_ms = self._container.clock.now_ms()
        async with transaction(self._sessionmaker()) as session:
            for remote in remote_containers:
                await repo.upsert_container(
                    session, integration_id, remote.id, name=remote.name, now_ms=now_ms
                )

    async def _reset_cursors(self, integration_id: int) -> None:
        """``trigger="full"``: zeruje ``delta_cursor`` kontenerów (pkt 2, kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            await repo.reset_cursors(session, integration_id)

    async def _acquire_lock(self, integration_id: int, *, owner: str, now_ms: int) -> bool:
        """Zakłada lock w krótkiej transakcji; ``False`` = ktoś inny prowadzi przebieg."""
        async with transaction(self._sessionmaker()) as session:
            return await repo.try_lock(session, integration_id, owner=owner, now_ms=now_ms)

    async def _release_lock(self, integration_id: int, *, owner: str, status: RunStatus) -> None:
        """Zwalnia lock i zapisuje ``last_sync_at``/``last_sync_status`` (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            await repo.release_lock(
                session,
                integration_id,
                owner=owner,
                now_ms=self._container.clock.now_ms(),
                status=status,
            )

    async def _integration_row(self, integration_id: int) -> IntegrationRow | None:
        """Wiersz integracji w krótkiej transakcji (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            return await repo.get_integration(session, integration_id)

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (wzorzec ``RunRecorder._sessionmaker``)."""
        return cast("async_sessionmaker[AsyncSession]", self._container.sessionmaker)
