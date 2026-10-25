"""Odczyt i zatrzymanie zadań powierzchni WD (K19 §3 trasy 3-4) — Core ``text()``.

Osobny moduł obok ``tasks.py``: trasy WD potrzebują ``create_time``/``finished_at``,
których wiersz kolejki (``TaskRow``) nie przenosi, a ``tasks.py`` jest na allowliście
limitu 400 linii. Bez ``commit``/``rollback`` — transakcję otwiera ``app.db.uow.transaction``.
"""

import json
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_GET_SQL = text(
    "SELECT public_id, task_type, payload, dataset_id, status, progress, progress_msg,"
    " error, create_time, finished_at FROM tasks WHERE public_id = :public_id"
)

# Zatrzymanie jednego zadania (K19 §3 trasa 4): ``queued``/``running`` → ``cancel_requested=1``.
# Statusu nie zmieniamy tutaj — zadanie ``queued`` z zapamiętanym anulowaniem zamyka
# claim jako ``cancelled``, a ``running`` kończy handler (kontrakt C5).
_REQUEST_CANCEL_SQL = text(
    "UPDATE tasks SET cancel_requested = 1, update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id AND status IN ('queued', 'running')"
)


async def get(session: AsyncSession, public_id: str) -> dict[str, Any] | None:
    """Wiersz zadania z czasami życia (``payload`` zdekodowany z JSON) albo ``None``."""
    row = (await session.execute(_GET_SQL, {"public_id": public_id})).mappings().first()
    if row is None:
        return None
    data = dict(row)
    payload = data["payload"]
    data["payload"] = json.loads(payload) if isinstance(payload, str) else payload
    return data


async def request_cancel(session: AsyncSession, *, public_id: str, now_ms: int) -> bool:
    """``queued``/``running`` → ``cancel_requested=1``; ``True``, gdy trafiliśmy w wiersz."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            _REQUEST_CANCEL_SQL,
            {"public_id": public_id, "now": now_ms, "now_date": from_ms(now_ms)},
        ),
    )
    return int(result.rowcount) == 1
