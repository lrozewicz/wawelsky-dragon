"""Kontekst zadania przekazywany handlerom (K5 §2.3, kontrakt C9)."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.container import Container
from app.worker.errors import TaskCancelled, TaskLost
from app.worker.queue import TaskQueue, TaskRow

Handler = Callable[[TaskRow, "TaskContext"], Awaitable[None]]


@dataclass
class TaskContext:
    """Usługi dla handlera: zadanie, tożsamość workera, kontener, logger i kolejka."""

    task: TaskRow
    worker_id: str
    container: Container
    logger: logging.LoggerAdapter[logging.Logger]
    # DOPRECYZOWANIE TL: kolejka dla report/check_cancel (pole dodatkowe, na końcu).
    queue: TaskQueue

    async def report(self, progress: float, msg: str | None = None) -> None:
        """Heartbeat z postępem; False → zadanie przejął ktoś inny → przerywamy (C9)."""
        if not await self.queue.heartbeat(self.task.id, self.worker_id, progress, msg):
            raise TaskLost(self.task.id)

    async def check_cancel(self) -> None:
        """Rzuca TaskCancelled, gdy zaplanowano anulowanie tego zadania (C9)."""
        if await self.queue.is_cancel_requested(self.task.id):
            raise TaskCancelled(self.task.id)
