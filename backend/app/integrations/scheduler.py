"""Scheduler integracji — tick, odzyskiwanie locków, retencja i przebiegi „due” (K12 §5, C6).

``tick`` jest jednym krokiem: najpierw ``locks.recover_stale``, potem usunięcie zdarzeń
starszych niż ``events_retention_days``, na końcu sekwencyjne przebiegi integracji „due”.
``run_forever`` woła ``tick`` w pętli bez nakładania ticków; błąd ticku jest logowany,
a pętla żyje dalej — zatrzymuje ją dopiero ``stop.set()``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import integrations as repo
from app.db.uow import transaction
from app.integrations import locks

if TYPE_CHECKING:
    from app.core.container import Container
    from app.integrations.config import IntegrationsConfig
    from app.integrations.engine import SyncEngine

logger = logging.getLogger("app.integrations.scheduler")

MS_PER_MINUTE = 60_000
MS_PER_DAY = 86_400_000


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera (wzorzec ``SyncEngine._sessionmaker``)."""
    return cast("async_sessionmaker[AsyncSession]", container.sessionmaker)


class Scheduler:
    """Pętla zaplanowanych przebiegów integracji (kontrakt C6)."""

    def __init__(
        self,
        container: Container,
        engine: SyncEngine,
        config: IntegrationsConfig,
        *,
        worker_id: str,
    ) -> None:
        self._container = container
        self._engine = engine
        self._config = config
        self._worker_id = worker_id

    async def tick(self, now_ms: int) -> list[int]:
        """Recover → retencja → „due”; zwraca ``id``, dla których powstał wynik (kontrakt C6)."""
        await locks.recover_stale(
            self._container, now_ms=now_ms, stale_ms=self._config.stale_lock_minutes * MS_PER_MINUTE
        )
        await self._purge_events(now_ms)
        started: list[int] = []
        for integration_id in await self._due(now_ms):
            try:
                outcome = await self._engine.run(
                    integration_id, trigger="schedule", worker_id=self._worker_id
                )
            except Exception:
                # Wyjątek infrastruktury jednej integracji nie przerywa pozostałych (C6).
                logger.exception("scheduled run failed", extra={"integration_id": integration_id})
                continue
            if outcome is not None:
                started.append(integration_id)
        return started

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Ticki co ``tick_seconds`` (bez nakładania) do ``stop.set()`` (kontrakt C6)."""
        while not stop.is_set():
            try:
                await self.tick(self._container.clock.now_ms())
            except Exception:
                # Błąd ticku logujemy, pętla żyje dalej (kontrakt C6).
                logger.exception("scheduler tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._config.tick_seconds)

    async def _purge_events(self, now_ms: int) -> None:
        """Usuwa zdarzenia starsze niż ``events_retention_days`` (kontrakt C6)."""
        before_ms = now_ms - self._config.events_retention_days * MS_PER_DAY
        async with transaction(_sessionmaker(self._container)) as session:
            await repo.purge_events_before(session, before_ms=before_ms)

    async def _due(self, now_ms: int) -> list[int]:
        """Id integracji gotowych do przebiegu (kontrakt C2, 09 §5)."""
        async with transaction(_sessionmaker(self._container)) as session:
            return await repo.list_due(session, now_ms=now_ms)
