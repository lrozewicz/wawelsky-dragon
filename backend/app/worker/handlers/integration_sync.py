"""Handler zadania ``integration_sync`` — kolejka → ``SyncEngine`` (K12 §5, kontrakt C7).

Payload: ``{"integration_id": int, "trigger": "manual" | "full"}``. Zajęty lock nie jest
błędem — przebieg pomijamy, logujemy ``integration_sync skipped: lock busy`` i zadanie
kończy się sukcesem. ``TaskQueue.complete`` nie ma pola wyniku, więc wynikiem przebiegu
pominiętego pozostaje tylko ten log (brief T9).
Moduł nie ciągnie ``app.parsing``: silnik importuje ``UploadSource`` dopiero leniwie
w ``engine_items``, więc ``import app.worker.main`` pozostaje lekki.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from app.worker.context import Handler

if TYPE_CHECKING:
    from app.integrations.base import RunTrigger
    from app.integrations.engine import SyncEngine
    from app.worker.context import TaskContext
    from app.worker.queue import TaskRow

SKIPPED_MESSAGE = "integration_sync skipped: lock busy"


def make_handler(engine: SyncEngine) -> Handler:
    """Buduje handler wołający silnik z payloadu zadania (kontrakt C7)."""

    async def handle(task: TaskRow, ctx: TaskContext) -> None:
        """Przebieg wg payloadu; ``None`` (zajęty lock) → log, bez wyjątku (kontrakt C7)."""
        outcome = await engine.run(
            int(task.payload["integration_id"]),
            trigger=cast("RunTrigger", task.payload["trigger"]),
            worker_id=ctx.worker_id,
        )
        if outcome is None:
            ctx.logger.info(SKIPPED_MESSAGE)

    return handle
