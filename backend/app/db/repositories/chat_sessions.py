"""Repozytorium tabeli chat_sessions (kontrakt C1) — Core ``text()`` z parametrami wiązanymi.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_INSERT_SQL = text(
    "INSERT INTO chat_sessions (id, chat_id, name, user_id, owner_id, source, message_count,"
    " create_time, create_date, update_time, update_date)"
    " VALUES (:id, :chat_id, :name, :user_id, :owner_id, :source, :message_count,"
    " :create_time, :create_date, :update_time, :update_date)"
)

_SELECT_SQL = (
    "SELECT id, chat_id, name, user_id, owner_id, source, message_count, create_time,"
    " update_time FROM chat_sessions"
)

_GET_SQL = text(_SELECT_SQL + " WHERE id = :id")

# lock: jak get, ale z FOR UPDATE — wiersz zablokowany do końca transakcji (brief T3).
_LOCK_SQL = text(_SELECT_SQL + " WHERE id = :id FOR UPDATE")

_BUMP_SQL = text(
    "UPDATE chat_sessions SET message_count = message_count + :added,"
    " update_time = :now, update_date = :now_date WHERE id = :id"
)

_RENAME_SQL = text(
    "UPDATE chat_sessions SET name = :name, update_time = :now, update_date = :now_date"
    " WHERE id = :id"
)

_DELETE_SQL = text("DELETE FROM chat_sessions WHERE id = :id")

# Biała lista kolumn orderby — tekst od użytkownika nigdy nie trafia do SQL wprost (C1).
_ORDERBY: Final[dict[str, str]] = {
    "create_time": "create_time",
    "update_time": "update_time",
    "name": "name",
}


@dataclass(frozen=True)
class SessionRow:
    """Wiersz `chat_sessions` (kontrakt C9)."""

    id: str
    chat_id: str
    name: str
    user_id: str | None
    owner_id: str | None
    source: str
    message_count: int
    create_time: int
    update_time: int


def _row(row: RowMapping) -> SessionRow:
    """RowMapping → SessionRow; liczby z bazy na int (jak w documents)."""
    return SessionRow(
        id=row["id"],
        chat_id=row["chat_id"],
        name=row["name"],
        user_id=row["user_id"],
        owner_id=row["owner_id"],
        source=row["source"],
        message_count=int(row["message_count"]),
        create_time=int(row["create_time"]),
        update_time=int(row["update_time"]),
    )


async def insert(session: AsyncSession, row: SessionRow) -> None:
    """Wstawia sesję; create_date/update_date z create_time/update_time (C9)."""
    await session.execute(
        _INSERT_SQL,
        {
            "id": row.id,
            "chat_id": row.chat_id,
            "name": row.name,
            "user_id": row.user_id,
            "owner_id": row.owner_id,
            "source": row.source,
            "message_count": row.message_count,
            "create_time": row.create_time,
            "create_date": from_ms(row.create_time),
            "update_time": row.update_time,
            "update_date": from_ms(row.update_time),
        },
    )


async def get(session: AsyncSession, session_id: str) -> SessionRow | None:
    """Sesja po identyfikatorze; None gdy brak (C1)."""
    found = (await session.execute(_GET_SQL, {"id": session_id})).mappings().first()
    return _row(found) if found is not None else None


async def lock(session: AsyncSession, session_id: str) -> SessionRow | None:
    """Sesja po identyfikatorze z blokadą FOR UPDATE; None gdy brak (C1)."""
    found = (await session.execute(_LOCK_SQL, {"id": session_id})).mappings().first()
    return _row(found) if found is not None else None


async def bump(session: AsyncSession, session_id: str, *, added: int, now_ms: int) -> None:
    """message_count += added, update_time/update_date = now (C1)."""
    await session.execute(
        _BUMP_SQL,
        {"id": session_id, "added": added, "now": now_ms, "now_date": from_ms(now_ms)},
    )


async def list_page(  # noqa: PLR0913 — sygnatura z kontraktu C1
    session: AsyncSession,
    chat_id: str,
    *,
    owner_ids: frozenset[str] | None,
    session_id: str | None,
    name: str | None,
    user_id: str | None,
    orderby: str,
    desc: bool,
    offset: int,
    limit: int,
) -> list[SessionRow]:
    """Strona sesji czatu (C1).

    owner_ids None = bez filtra właściciela (pusty frozenset → [] bez SQL);
    session_id/name/user_id — równość, gdy nie None; orderby z białej listy,
    kolejność stabilna po id w tym samym kierunku.
    """
    if owner_ids is not None and not owner_ids:
        return []
    if orderby not in _ORDERBY:
        raise ValueError(f"orderby: {orderby}")
    direction = "DESC" if desc else "ASC"
    conditions = ["chat_id = :chat_id"]
    params: dict[str, Any] = {"chat_id": chat_id}
    if owner_ids is not None:
        conditions.append("owner_id IN :owner_ids")
        params["owner_ids"] = list(owner_ids)
    if session_id is not None:
        conditions.append("id = :session_id")
        params["session_id"] = session_id
    if name is not None:
        conditions.append("name = :name")
        params["name"] = name
    if user_id is not None:
        conditions.append("user_id = :user_id")
        params["user_id"] = user_id
    sql = (
        _SELECT_SQL
        + f" WHERE {' AND '.join(conditions)}"
        + f" ORDER BY {_ORDERBY[orderby]} {direction}, id {direction}"
        + " LIMIT :limit OFFSET :offset"
    )
    params["limit"] = limit
    params["offset"] = offset
    clause = text(sql)
    if owner_ids is not None:
        clause = clause.bindparams(bindparam("owner_ids", expanding=True))
    rows = (await session.execute(clause, params)).mappings().all()
    return [_row(row) for row in rows]


async def rename(session: AsyncSession, session_id: str, name: str, *, now_ms: int) -> None:
    """Zmienia nazwę sesji; update_time/update_date = now_ms (C1)."""
    await session.execute(
        _RENAME_SQL,
        {"id": session_id, "name": name, "now": now_ms, "now_date": from_ms(now_ms)},
    )


async def delete(session: AsyncSession, session_id: str) -> bool:
    """Usuwa sesję — True gdy usunięto wiersz; kaskada FK czyści chat_messages (C1)."""
    result = cast("CursorResult[Any]", await session.execute(_DELETE_SQL, {"id": session_id}))
    return result.rowcount == 1


async def list_ids(
    session: AsyncSession, chat_id: str, *, owner_ids: frozenset[str] | None
) -> list[str]:
    """Id sesji czatu, stabilnie po (create_time, id) (C1 — usuwanie masowe).

    owner_ids None = bez filtra właściciela; pusty frozenset → [] bez SQL.
    """
    if owner_ids is not None and not owner_ids:
        return []
    conditions = "chat_id = :chat_id"
    params: dict[str, Any] = {"chat_id": chat_id}
    if owner_ids is not None:
        conditions += " AND owner_id IN :owner_ids"
        params["owner_ids"] = list(owner_ids)
    # Składany SQL: warunki stałe, wartości przez bindparamy (C1).
    clause = text(
        f"SELECT id FROM chat_sessions WHERE {conditions} ORDER BY create_time, id"  # noqa: S608
    )
    if owner_ids is not None:
        clause = clause.bindparams(bindparam("owner_ids", expanding=True))
    rows = (await session.execute(clause, params)).all()
    return [row[0] for row in rows]
