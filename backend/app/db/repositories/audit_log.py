"""Repozytorium tabeli `audit_log` (kontrakt C2) — Core `text()`, bez commit/rollback."""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AuditRow:
    """Wiersz `audit_log`; `details` zdekodowane z JSON (kontrakt C2)."""

    id: int
    ts: int
    actor_id: str | None
    actor_label: str
    action: str
    target_type: str
    target_id: str
    details: dict[str, Any] | None
    ip: str | None


def _row(row: RowMapping) -> AuditRow:
    """RowMapping → AuditRow; kolumna JSON wraca jako str, więc dekodujemy ją tutaj."""
    raw = row["details"]
    return AuditRow(
        id=int(row["id"]),
        ts=int(row["ts"]),
        actor_id=row["actor_id"],
        actor_label=row["actor_label"],
        action=row["action"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        details=json.loads(raw) if raw is not None else None,
        ip=row["ip"],
    )


async def insert(  # noqa: PLR0913 — sygnatura z kontraktu C2
    session: AsyncSession,
    *,
    ts: int,
    actor_id: str | None,
    actor_label: str,
    action: str,
    target_type: str,
    target_id: str,
    details_json: str | None,
    ip: str | None,
) -> None:
    """Wstawia wpis audytu; `details_json` to gotowy JSON albo NULL (C2)."""
    await session.execute(
        text(
            "INSERT INTO audit_log (ts, actor_id, actor_label, action, target_type,"
            " target_id, details, ip) VALUES (:ts, :actor_id, :actor_label, :action,"
            " :target_type, :target_id, :details_json, :ip)"
        ),
        {
            "ts": ts,
            "actor_id": actor_id,
            "actor_label": actor_label,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details_json": details_json,
            "ip": ip,
        },
    )


_SELECT_COLUMNS = (
    "SELECT id, ts, actor_id, actor_label, action, target_type, target_id, details, ip"
    " FROM audit_log"
)


async def list_by_action(session: AsyncSession, action: str) -> list[AuditRow]:
    """Wpisy danej akcji, kolejność `id` (C2)."""
    result = await session.execute(
        text(f"{_SELECT_COLUMNS} WHERE action = :action ORDER BY id"), {"action": action}
    )
    return [_row(row) for row in result.mappings()]


def _filters(
    *, actor: str | None, action: str | None, from_ms: int | None, to_ms: int | None
) -> tuple[list[str], dict[str, object]]:
    """Warunki `WHERE` i parametry dla `list_page` (nazwy wiązane, bez sklejania SQL)."""
    where: list[str] = []
    params: dict[str, object] = {}
    if actor is not None:
        where.append("LOWER(actor_label) = LOWER(:actor)")
        params["actor"] = actor
    if action is not None:
        where.append("action = :action")
        params["action"] = action
    if from_ms is not None:
        where.append("ts >= :from_ms")
        params["from_ms"] = from_ms
    if to_ms is not None:
        where.append("ts <= :to_ms")
        params["to_ms"] = to_ms
    return where, params


async def list_page(  # noqa: PLR0913 — sygnatura z kontraktu E3-6a §4
    session: AsyncSession,
    *,
    actor: str | None,
    action: str | None,
    from_ms: int | None,
    to_ms: int | None,
    limit: int,
    offset: int,
) -> tuple[list[AuditRow], int]:
    """Strona wpisów malejąco po `id` i łączna liczba pasujących (kontrakt E3-6a §4).

    Licznik to osobne `COUNT(*)` z tym samym `WHERE`.
    """
    where, params = _filters(actor=actor, action=action, from_ms=from_ms, to_ms=to_ms)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    count_sql = f"SELECT COUNT(*) FROM audit_log{clause}"  # noqa: S608 — `clause` z warunków
    select_sql = f"{_SELECT_COLUMNS}{clause} ORDER BY id DESC LIMIT :limit OFFSET :offset"
    total = await session.execute(text(count_sql), params)
    result = await session.execute(text(select_sql), {**params, "limit": limit, "offset": offset})
    return [_row(row) for row in result.mappings()], int(total.scalar_one())
