"""Sterowanie przebiegami integracji: zlecenie, oczekiwanie, anulowanie (K12 §5, 09 §5 i §8 p. 1-3).

Bez tras HTTP (te dochodzą w E4-3). Zlecenie nie wykonuje synchronizacji w procesie API —
wstawia zadanie ``integration_sync`` do kolejki; worker bierze je przez ten sam lock.
``Container`` importowany pod ``TYPE_CHECKING`` (jak w ``app/services/ingest.py``).
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict, NotFound
from app.db.repositories import integrations as integrations_repo
from app.db.uow import transaction
from app.integrations.config import IntegrationsConfig
from app.worker.queue import DbTaskQueue, NewTask

if TYPE_CHECKING:
    from app.core.container import Container
    from app.db.repositories.integrations import RunRow

POLL_SECONDS = 0.2  # 09 §5 „Ręczny sync”; testy skracają przez ``_poll_s``


@dataclass(frozen=True)
class CancelResult:
    """Wynik anulowania (09 §8): czy przebieg zakończył się kooperacyjnie i ile runów zamknięto."""

    was_running_in_process: bool
    lock_cleared: bool
    runs_marked_cancelled: int


class IntegrationRunsService:
    """Zlecanie synchronizacji, oczekiwanie na przebieg i anulowanie (kontrakt C7)."""

    def __init__(self, container: Container, config: IntegrationsConfig) -> None:
        self._container = container
        self._config = config
        self._poll_s = POLL_SECONDS

    def _sm(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C7)."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        return sessionmaker

    async def request_sync(self, integration_id: int, *, full: bool) -> str:
        """Wstawia zadanie ``integration_sync`` (priorytet 1) i zwraca ``task_id`` (C7).

        Trwający przebieg (``is_running=1``) ⇒ ``Conflict``; nieznana integracja ⇒ ``NotFound``.
        """
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
        if row is None:
            raise NotFound(f"integration not found: {integration_id}")
        if row.is_running:
            raise Conflict("integration is already running")
        queue = DbTaskQueue(self._sm(), self._container.clock, self._container.id_gen)
        return await queue.enqueue(
            NewTask(
                task_type="integration_sync",
                payload={
                    "integration_id": integration_id,
                    "trigger": "full" if full else "manual",
                },
                priority=1,
            )
        )

    async def wait_for_run(
        self, integration_id: int, *, since_run_id: int | None, timeout_s: float
    ) -> RunRow | None:
        """Czeka na przebieg o ``id > since_run_id`` w stanie innym niż ``running`` (C7).

        Koniec po ``timeout_s`` zegara albo po ``ceil(timeout_s / poll)`` próbach (gdy zegar
        stoi — testy z ``FrozenClock``); timeout ⇒ ``None``.
        """
        since = since_run_id or 0
        deadline_ms = self._container.clock.now_ms() + int(timeout_s * 1000)
        attempts = max(1, math.ceil(timeout_s / self._poll_s))
        for _ in range(attempts):
            async with transaction(self._sm()) as session:
                latest = await integrations_repo.latest_run(session, integration_id)
            if latest is not None and latest.id > since and latest.status != "running":
                return latest
            if self._container.clock.now_ms() >= deadline_ms:
                break
            await asyncio.sleep(self._poll_s)
        return None

    async def cancel(self, integration_id: int) -> CancelResult:
        """Anulowanie wg 09 §8 p. 1-3; nieznana integracja ⇒ ``NotFound`` (C7)."""
        async with transaction(self._sm()) as session:
            row = await integrations_repo.get_integration(session, integration_id)
            if row is None:
                raise NotFound(f"integration not found: {integration_id}")
            was_running = await integrations_repo.request_cancel(session, integration_id)
        if was_running:
            if await self._wait_until_released(integration_id):
                # p. 1: worker zakończył kooperacyjnie — run zamknął sam (stała 1).
                return CancelResult(True, True, 1)
            # p. 2: worker martwy/zawieszony — wymuszenie w jednej transakcji.
            async with transaction(self._sm()) as session:
                await integrations_repo.force_unlock(session, integration_id)
                marked = await integrations_repo.mark_running_runs(
                    session,
                    integration_id,
                    status="cancelled",
                    now_ms=self._container.clock.now_ms(),
                )
            return CancelResult(False, True, marked)
        # p. 3: przebiegu nie było, ale sieroty ``running`` oznaczamy i liczymy.
        async with transaction(self._sm()) as session:
            marked = await integrations_repo.mark_running_runs(
                session, integration_id, status="cancelled", now_ms=self._container.clock.now_ms()
            )
        return CancelResult(False, False, marked)

    async def _wait_until_released(self, integration_id: int) -> bool:
        """Czeka, aż worker zwolni lock; ``False`` po ``cancel_wait_seconds`` (09 §8 p. 1)."""
        deadline_ms = self._container.clock.now_ms() + self._config.cancel_wait_seconds * 1000
        attempts = max(1, math.ceil(self._config.cancel_wait_seconds / self._poll_s))
        for _ in range(attempts):
            async with transaction(self._sm()) as session:
                row = await integrations_repo.get_integration(session, integration_id)
            if row is None or not row.is_running:
                return True
            if self._container.clock.now_ms() >= deadline_ms:
                return False
            await asyncio.sleep(self._poll_s)
        return False
