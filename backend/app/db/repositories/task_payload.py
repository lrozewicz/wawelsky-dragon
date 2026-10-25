"""Zapis postępu i wyniku do JSON-owego ``payload`` zadania (CONTRACT E7-1b §3, T7).

Handler importu (``app.worker.handlers.import_dataset``) prowadzi postęp zadania w kolumnie
``tasks.payload`` (``stage``/``done``/``total``, na końcu ``result``, przy porażce ``error_code``)
— trasa ``GET /tasks/{id}`` czyta te klucze (``app.api.wd.tasks``). Repozytorium ``tasks`` nie
miało funkcji aktualizacji payloadu, więc ta rola dostaje minimalny, nowy moduł: scalenie
podanego fragmentu z bieżącym JSON-em w jednej transakcji (``SELECT … FOR UPDATE`` serializuje
zapisy; właścicielem wiersza jest jeden worker).
"""

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

__all__ = ["patch_payload"]

_SELECT_SQL = text("SELECT payload FROM tasks WHERE public_id = :public_id FOR UPDATE")

_UPDATE_SQL = text(
    "UPDATE tasks SET payload = :payload, update_time = :now, update_date = :now_date"
    " WHERE public_id = :public_id"
)


async def patch_payload(
    session: AsyncSession,
    *,
    public_id: str,
    patch: Mapping[str, Any],
    now_ms: int,
) -> None:
    """Scala ``patch`` z bieżącym payloadem zadania; brak wiersza = no-op (CONTRACT §3).

    Klucze ``patch`` nadpisują istniejące (płytkie scalenie), reszta payloadu zostaje —
    postęp dokłada się, więc ``stage``/``done``/``total`` nie kasują pól z ``start``.
    """
    row = (await session.execute(_SELECT_SQL, {"public_id": public_id})).first()
    if row is None:
        return
    current = row[0]
    if isinstance(current, str):
        current = json.loads(current)
    merged: dict[str, Any] = {**(current or {}), **dict(patch)}
    await session.execute(
        _UPDATE_SQL,
        {
            "public_id": public_id,
            "payload": json.dumps(merged, ensure_ascii=False),
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )
