"""Stan systemu WD: sondy komponentów i tętno workerów (brief SYS p. 2, K5 §2.6).

Rekordy neutralne wobec kształtu odpowiedzi — mapowanie na nazwy pól RAGFlow robi
warstwa API (``app/api/ragflow/routes/system.py``, kontrakt ``compat-isolated``).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import health as db_health
from app.db.repositories import task_counts
from app.db.repositories import worker_heartbeat as heartbeat_repo
from app.db.uow import transaction

if TYPE_CHECKING:
    from app.core.container import Container


@dataclass(frozen=True)
class ComponentProbe:
    """Wynik sondy komponentu: powodzenie i czas trwania w milisekundach."""

    ok: bool
    elapsed_ms: float


@dataclass(frozen=True)
class SystemStatusRecord:
    """Sondy bazy i storage oraz tętna workerów (data /system/status)."""

    database: ComponentProbe
    storage: ComponentProbe
    heartbeats: dict[str, list[dict[str, object]]]


class SystemInfoService:
    """Sondy zdrowia WD (baza, storage) i tętno workerów z ``worker_heartbeat``."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def probe_database(self) -> ComponentProbe:
        """SELECT 1 i wersja schematu (K5 ``check_ready``); brak engine = brak gotowości."""
        engine = self._container.engine
        start = time.perf_counter()
        if engine is None:
            return ComponentProbe(False, _elapsed_ms(start))
        return ComponentProbe(await db_health.check_ready(engine) is None, _elapsed_ms(start))

    async def probe_storage(self) -> ComponentProbe:
        """Prawo zapisu w korzeniu storage; jedyna implementacja portu to filesystem (K5 §1.3).

        Sonda nie zapisuje niczego — ``ensure_layout`` poza startem workera (loop.py:81)
        czyściłby ``tmp/`` w trakcie trwających uploadów.
        """
        start = time.perf_counter()
        root = Path(self._container.settings.storage_root)
        writable = await asyncio.to_thread(os.access, root, os.W_OK)
        return ComponentProbe(bool(writable), _elapsed_ms(start))

    async def healthz(self) -> tuple[bool, bool]:
        """(baza ok, storage ok) dla surowego /system/healthz (bez koperty)."""
        return (await self.probe_database()).ok, (await self.probe_storage()).ok

    async def status(self) -> SystemStatusRecord:
        """Sondy bazy i storage oraz tętna workerów (data /system/status)."""
        return SystemStatusRecord(
            database=await self.probe_database(),
            storage=await self.probe_storage(),
            heartbeats=await self.heartbeats(),
        )

    async def queue_counts(self) -> dict[str, int]:
        """Liczba zadań w stanach kolejki (``queued``/``running``/``dead``) — kontrakt E3-6a §4."""
        sessionmaker = cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)
        async with transaction(sessionmaker) as session:
            return await task_counts.count_by_status(session)

    async def heartbeats(self) -> dict[str, list[dict[str, object]]]:
        """Tętna workerów kluczowane ``worker_id`` (odpowiednik ``TASKEXE`` upstreamu)."""
        sessionmaker = cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)
        async with transaction(sessionmaker) as session:
            rows = await heartbeat_repo.list_all(session)
        return {
            row.worker_id: [
                {
                    "started_at": row.started_at,
                    "heartbeat_at": row.heartbeat_at,
                    "capabilities": row.capabilities,
                    "version": row.version,
                }
            ]
            for row in rows
        }


def _elapsed_ms(start: float) -> float:
    """Milisekundy od ``start`` (``time.perf_counter``)."""
    return (time.perf_counter() - start) * 1000.0
