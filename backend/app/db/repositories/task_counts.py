"""Liczniki stanów tabeli tasks dla statystyk WD (kontrakt E3-6a §4, DEC-099).

Osobny moduł z powodu limitu 400 linii ``tasks.py`` (wzorzec ``task_lookup.py``). SQL przez
``text()`` z literałem stanów kolejki; bez ``commit``/``rollback`` — transakcję otwiera
wywołująca (``app.db.uow.transaction``).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Stany kolejki pokazywane w statystykach WD (kontrakt E3-6a §4) — literał, nie parametr.
_QUEUE_STATUSES: tuple[str, ...] = ("queued", "running", "dead")

_COUNT_BY_STATUS_SQL = text(
    "SELECT status, COUNT(*) AS n FROM tasks"
    " WHERE status IN ('queued','running','dead') GROUP BY status"
)


async def count_by_status(session: AsyncSession) -> dict[str, int]:
    """Liczba zadań w stanach kolejki; brakujący stan = 0 (kontrakt E3-6a §4)."""
    rows = (await session.execute(_COUNT_BY_STATUS_SQL)).mappings().all()
    counts = dict.fromkeys(_QUEUE_STATUSES, 0)
    counts.update({str(row["status"]): int(row["n"]) for row in rows})
    return counts
