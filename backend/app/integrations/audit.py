"""Audyt przebiegów integracji — ``RunRecorder`` (K12 §5, kontrakt E4-1 C4).

Zdarzenia zbierane są w buforze w pamięci i zapisywane paczkami (co ``events_flush_every``
zdarzeń lub ``events_flush_seconds``), by nie uderzać do bazy przy każdym zdarzeniu; resztę
bufora domyka ``finish``. Teksty przycinane są do limitów kolumn (``message`` ≤ 2000,
``file_path`` ≤ 1024 znaków), z końcowym „…” wliczonym w limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.integrations import (
    NewEvent,
    finish_run,
    insert_events,
    insert_run,
    update_run_counts,
)
from app.db.uow import transaction
from app.integrations.base import RunStatus, RunTrigger, SyncCounts
from app.integrations.config import IntegrationsConfig

if TYPE_CHECKING:
    from app.core.container import Container

MESSAGE_LIMIT = 2000
FILE_PATH_LIMIT = 1024


def trim(text: str, limit: int) -> str:
    """Przycina ``text`` do ``limit`` znaków (końcowe „…” wliczone w limit).

    Krótszy lub równy limitowi tekst wraca bez zmian; dłuższy skracany jest do
    ``limit - 1`` znaków i zakończony „…”, więc wynik ma dokładnie ``limit`` znaków.
    """
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class RunRecorder:
    """Rejestrator jednego przebiegu integracji (kontrakt C4).

    Konstruktor nie robi I/O; ``start`` wstawia wiersz ``running``, ``event`` buforuje
    zdarzenia, ``flush``/``maybe_flush`` zapisują bufor, a ``finish`` zamyka przebieg.
    """

    def __init__(
        self,
        container: Container,
        config: IntegrationsConfig,
        *,
        integration_id: int,
        integration_type: str,
    ) -> None:
        self._container = container
        self._config = config
        self._integration_id = integration_id
        self._integration_type = integration_type
        self.run_id = 0
        self.counts = SyncCounts()
        self._buffer: list[NewEvent] = []
        self._last_flush_ms = 0

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (wzorzec ``DatasetIngestionsService._sessionmaker``)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    async def start(self, trigger: RunTrigger) -> int:
        """Wstawia przebieg ``running`` i zwraca jego ``id``; zeruje liczniki (kontrakt C4)."""
        now_ms = self._container.clock.now_ms()
        async with transaction(self._sessionmaker()) as session:
            self.run_id = await insert_run(
                session,
                integration_id=self._integration_id,
                integration_type=self._integration_type,
                run_trigger=trigger,
                now_ms=now_ms,
            )
        self.counts = SyncCounts()
        self._last_flush_ms = now_ms
        return self.run_id

    def event(
        self,
        level: str,
        message: str,
        *,
        file_path: str | None = None,
        container_id: str | None = None,
        container_name: str | None = None,
    ) -> None:
        """Buforuje zdarzenie, przycinając ``message`` i ``file_path`` do limitów (C4)."""
        self._buffer.append(
            NewEvent(
                run_id=self.run_id,
                integration_id=self._integration_id,
                integration_type=self._integration_type,
                level=level,
                message=trim(message, MESSAGE_LIMIT),
                file_path=None if file_path is None else trim(file_path, FILE_PATH_LIMIT),
                container_id=container_id,
                container_name=container_name,
                created_at=self._container.clock.now_ms(),
            )
        )

    async def flush(self) -> None:
        """Zapisuje bufor zdarzeń i liczniki w jednej transakcji; czyści bufor (kontrakt C4)."""
        events = self._buffer
        async with transaction(self._sessionmaker()) as session:
            await insert_events(session, events)
            await update_run_counts(session, self.run_id, self.counts)
        self._buffer = []
        self._last_flush_ms = self._container.clock.now_ms()

    async def maybe_flush(self) -> None:
        """Flush, gdy bufor ≥ ``events_flush_every`` lub minęło ``events_flush_seconds`` (C4)."""
        if not self._buffer:
            return
        full = len(self._buffer) >= self._config.events_flush_every
        elapsed = self._container.clock.now_ms() - self._last_flush_ms
        if full or elapsed >= self._config.events_flush_seconds * 1000:
            await self.flush()

    async def finish(self, status: RunStatus) -> None:
        """Flush reszty bufora i zamknięcie przebiegu ``status`` + licznikami (kontrakt C4)."""
        await self.flush()
        async with transaction(self._sessionmaker()) as session:
            await finish_run(
                session,
                self.run_id,
                status=status,
                counts=self.counts,
                now_ms=self._container.clock.now_ms(),
            )
