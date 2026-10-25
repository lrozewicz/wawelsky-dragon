"""Repozytorium tabeli `agent_sessions` (CONTRACT E6-3f §C2, K2 §6).

SQL przez ``text()``, bez ``commit``/``rollback`` — transakcję otwiera ``app.db.uow.transaction``.
``id``/``agent_id``/``owner_id`` mają kolację `ascii_bin`, a parametry z żądania są w `utf8mb4_*`:
porównania parametru z kolumną ``CHAR(32)`` idą przez ``CAST(:x AS BINARY)`` (DEC-087/090).
``messages``/``reference``/``dsl`` to JSON — dekodowane przy odczycie. Kolumny ``round`` i
``reference`` cytujemy backtickami (słowa funkcyjne/zastrzeżone w MySQL).
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_COLUMNS = (
    "id, agent_id, user_id, owner_id, name, source, messages, `reference`, dsl, tokens,"
    " duration, `round`, errors, create_time, create_date, update_time, update_date"
)

_GET_BY_ID_SQL = text(
    f"SELECT {_COLUMNS} FROM agent_sessions WHERE id = CAST(:session_id AS BINARY)"  # noqa: S608
)

_LIST_BY_AGENT_SQL = text(
    f"SELECT {_COLUMNS} FROM agent_sessions"  # noqa: S608
    " WHERE agent_id = CAST(:agent_id AS BINARY) AND user_id = :user_id"
    " ORDER BY update_time DESC, id"
)

_INSERT_SQL = text(
    "INSERT INTO agent_sessions (id, agent_id, user_id, owner_id, name, source, messages,"
    " `reference`, dsl, tokens, duration, `round`, errors, create_time, create_date,"
    " update_time, update_date)"
    " VALUES (:id, :agent_id, :user_id, :owner_id, :name, :source, :messages, :reference,"
    " :dsl, :tokens, :duration, :round, :errors, :now_ms, :date, :now_ms, :date)"
)

_UPDATE_SQL = text(
    "UPDATE agent_sessions SET name = :name, source = :source, messages = :messages,"
    " `reference` = :reference, dsl = :dsl, tokens = :tokens, duration = :duration,"
    " `round` = :round, errors = :errors, update_time = :now_ms, update_date = :date"
    " WHERE id = CAST(:session_id AS BINARY)"
)

_DELETE_SQL = text("DELETE FROM agent_sessions WHERE id = CAST(:session_id AS BINARY)")


@dataclass(frozen=True)
class AgentSessionRow:
    """Wiersz `agent_sessions`; `messages`/`reference`/`dsl` zdekodowane (CONTRACT §C2)."""

    id: str
    agent_id: str
    user_id: str
    owner_id: str | None
    name: str | None
    source: str
    messages: list[Any]
    reference: list[Any]
    dsl: dict[str, Any]
    tokens: int
    duration: float
    round: int
    errors: str | None
    create_time: int
    create_date: datetime
    update_time: int
    update_date: datetime


def _row(row: RowMapping) -> AgentSessionRow:
    """RowMapping → AgentSessionRow; kolumny JSON (asyncmy: str) → struktury Pythona."""
    return AgentSessionRow(
        id=row["id"],
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        owner_id=row["owner_id"],
        name=row["name"],
        source=row["source"],
        messages=json.loads(row["messages"]),
        reference=json.loads(row["reference"]),
        dsl=json.loads(row["dsl"]),
        tokens=int(row["tokens"]),
        duration=float(row["duration"]),
        round=int(row["round"]),
        errors=row["errors"],
        create_time=int(row["create_time"]),
        create_date=row["create_date"],
        update_time=int(row["update_time"]),
        update_date=row["update_date"],
    )


async def insert(  # noqa: PLR0913 — kolumny tabeli §C2
    session: AsyncSession,
    *,
    id: str,  # nazwa pola z kontraktu §C2
    agent_id: str,
    user_id: str,
    owner_id: str | None,
    name: str | None,
    source: str,
    messages: list[Any],
    reference: list[Any],
    dsl: dict[str, Any],
    tokens: int,
    duration: float,
    round: int,  # nazwa kolumny z kontraktu §C2
    errors: str | None,
    now_ms: int,
) -> None:
    """Wstawia sesję agenta; czasy z zegara wołającego (§C2)."""
    date = from_ms(now_ms)
    await session.execute(
        _INSERT_SQL,
        {
            "id": id,
            "agent_id": agent_id,
            "user_id": user_id,
            "owner_id": owner_id,
            "name": name,
            "source": source,
            "messages": json.dumps(messages, ensure_ascii=False),
            "reference": json.dumps(reference, ensure_ascii=False),
            "dsl": json.dumps(dsl, ensure_ascii=False),
            "tokens": tokens,
            "duration": duration,
            "round": round,
            "errors": errors,
            "now_ms": now_ms,
            "date": date,
        },
    )


async def get_by_id(session: AsyncSession, session_id: str) -> AgentSessionRow | None:
    """Sesja po identyfikatorze; None gdy brak."""
    found = (await session.execute(_GET_BY_ID_SQL, {"session_id": session_id})).mappings().first()
    return _row(found) if found is not None else None


async def list_by_agent(
    session: AsyncSession, agent_id: str, user_id: str
) -> list[AgentSessionRow]:
    """Sesje agenta użytkownika, najnowsze po ``update_time`` DESC, id (§C2)."""
    rows = (
        (await session.execute(_LIST_BY_AGENT_SQL, {"agent_id": agent_id, "user_id": user_id}))
        .mappings()
        .all()
    )
    return [_row(row) for row in rows]


async def update(  # noqa: PLR0913 — kolumny edytowalne §C2
    session: AsyncSession,
    *,
    session_id: str,
    name: str | None,
    source: str,
    messages: list[Any],
    reference: list[Any],
    dsl: dict[str, Any],
    tokens: int,
    duration: float,
    round: int,  # nazwa kolumny z kontraktu §C2
    errors: str | None,
    now_ms: int,
) -> None:
    """Podmienia pola edytowalne i podbija czasy (§C2)."""
    date = from_ms(now_ms)
    await session.execute(
        _UPDATE_SQL,
        {
            "session_id": session_id,
            "name": name,
            "source": source,
            "messages": json.dumps(messages, ensure_ascii=False),
            "reference": json.dumps(reference, ensure_ascii=False),
            "dsl": json.dumps(dsl, ensure_ascii=False),
            "tokens": tokens,
            "duration": duration,
            "round": round,
            "errors": errors,
            "now_ms": now_ms,
            "date": date,
        },
    )


async def delete_by_id(session: AsyncSession, session_id: str) -> int:
    """Usuwa sesję agenta; zwraca liczbę usuniętych wierszy (§C2)."""
    result = await session.execute(_DELETE_SQL, {"session_id": session_id})
    return int(cast("CursorResult[Any]", result).rowcount)
