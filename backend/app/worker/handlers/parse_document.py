"""Handler zadania ``parse_document`` — most kolejka → DocumentIngestService (kontrakt C8).

Moduł nie importuje ``app.parsing`` ani ``stempel``: pipeline dołącza leniwie
w ``DocumentIngestService.run_parse_task``, więc sam ``import app.worker.main``
pozostaje lekki (brief T8, wymaganie 4).
"""

from concurrent.futures import Executor
from typing import TYPE_CHECKING

from app.worker.context import Handler

if TYPE_CHECKING:
    from app.worker.context import TaskContext
    from app.worker.queue import TaskRow


def make_handler(executor: Executor | None) -> Handler:
    """Buduje handler związaną z pulą procesów; ``None`` → konwersja w ``to_thread`` (C8)."""

    async def handle(task: "TaskRow", ctx: "TaskContext") -> None:
        """Deleguje zadanie do usługi ingestii z zapisaną pulą procesów."""
        await ctx.container.ingest.run_parse_task(task, ctx, executor=executor)

    return handle
