"""Raportowanie postępu parsowania (kontrakt C7, K5 §6.3).

Heartbeat zadania idzie przez ``TaskContext.report`` (kolejka; ``TaskLost`` przepuszczamy).
Linie postępu dokumentu trafiają do ``documents.progress_msg`` osobnymi krótkimi transakcjami,
dławionymi do jednego zapisu na ``PROGRESS_THROTTLE_MS`` (odstępstwo od 05 §5.2 — K5 §6.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.timeutil import Clock
from app.db.repositories import documents
from app.db.repositories.documents import clock_hms
from app.db.uow import transaction

if TYPE_CHECKING:
    from app.worker.context import TaskContext

PROGRESS_THROTTLE_MS = 1000


class ProgressReporter:
    """Pisze postęp do zadania (heartbeat) i do dokumentu (bufor + dławienie zapisu)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        ctx: TaskContext,
        document_id: str,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._ctx = ctx
        self._document_id = document_id
        self._buffer: list[str] = []
        self._last_progress = 0.0
        self._last_write_ms: int | None = None  # None = ten obiekt jeszcze nic nie zapisał

    @property
    def last_progress(self) -> float:
        """Ostatni raportowany procent — bez jego zmiany (hook logu zadania, C1)."""
        return self._last_progress

    async def report(self, progress: float, msg: str | None = None, *, force: bool = False) -> None:
        """Heartbeat zadania, dopisanie linii do bufora i zapis wg dławienia (C7).

        ``TaskLost`` z heartbeatu przepuszczamy (przejmuje go hook pracy zadań).
        Zapis wyzwalają: ``force``, pierwszy zapis tego obiektu albo upływ
        ``PROGRESS_THROTTLE_MS`` od poprzedniego zapisu.
        """
        await self._ctx.report(progress, msg)
        now_ms = self._clock.now_ms()
        if msg:
            self._buffer.append(f"{clock_hms(now_ms)} {msg}")
        self._last_progress = progress
        if (
            force
            or self._last_write_ms is None
            or now_ms - self._last_write_ms >= PROGRESS_THROTTLE_MS
        ):
            await self.flush()

    async def flush(self) -> None:
        """Zapisuje niepusty bufor jedną transakcją (append_progress); pusty → nic.

        Pusty bufor przy zmienionym progress także pomijamy — ``append_progress``
        dopisałby pustą linię; progress zapisze następny flush z niepustym buforem.
        """
        if not self._buffer:
            return
        now_ms = self._clock.now_ms()
        lines = "\n".join(self._buffer)
        self._buffer.clear()
        async with transaction(self._sessionmaker) as session:
            await documents.append_progress(
                session,
                self._document_id,
                progress=self._last_progress,
                lines=lines,
                now_ms=now_ms,
            )
        self._last_write_ms = now_ms
