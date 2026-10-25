"""Repozytorium tabeli chat_messages (kontrakt C1) — Core ``text()`` z parametrami wiązanymi.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
thumbup/feedback wypełnia ocena wiadomości (E2-1 chat_extras); przy zapisie sesji zostają NULL.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

Role = Literal["user", "assistant", "system"]

_INSERT_SQL = text(
    "INSERT INTO chat_messages (id, session_id, seq, role, content, reference, thumbup,"
    " feedback, prompt_tokens, completion_tokens, created_at, create_time, create_date,"
    " update_time, update_date)"
    " VALUES (:id, :session_id, :seq, :role, :content, :reference, NULL, NULL,"
    " :prompt_tokens, :completion_tokens, :created_at, :create_time, :create_date,"
    " :create_time, :create_date)"
)

# Kolumny zwracane przez SELECT-y wiadomości (w tym ocena: E2-1 chat_extras).
_SELECT_COLUMNS = (
    "SELECT id, session_id, seq, role, content, reference, prompt_tokens, completion_tokens,"
    " thumbup, feedback, created_at, create_time FROM chat_messages"
)

_SELECT_BY_SESSION_SQL = text(_SELECT_COLUMNS + " WHERE session_id = :session_id ORDER BY seq")

# Wiadomości wielu sesji jednym zapytaniem; grupowanie po stronie Pythona (C1).
_SELECT_BY_SESSIONS_SQL = text(
    _SELECT_COLUMNS + " WHERE session_id IN :ids ORDER BY session_id, seq"
).bindparams(bindparam("ids", expanding=True))

_GET_SQL = text(_SELECT_COLUMNS + " WHERE id = :id")

_DELETE_PAIR_SQL = text(
    "DELETE FROM chat_messages WHERE session_id = :session_id AND seq IN :seqs"
).bindparams(bindparam("seqs", expanding=True))

_SET_FEEDBACK_SQL = text(
    "UPDATE chat_messages SET thumbup = :thumbup, feedback = :feedback,"
    " update_time = :now, update_date = :now_date WHERE id = :id"
)

_NEXT_SEQ_SQL = text(
    "SELECT COALESCE(MAX(seq), -1) + 1 FROM chat_messages WHERE session_id = :session_id"
)

_EXISTS_SQL = text("SELECT 1 FROM chat_messages WHERE id = :id")


@dataclass(frozen=True)
class MessageRow:
    """Wiersz `chat_messages` (kontrakt C9)."""

    id: str
    session_id: str
    seq: int
    role: Role
    content: str
    reference: dict[str, Any] | None
    prompt_tokens: int | None
    completion_tokens: int | None
    created_at: float
    create_time: int
    thumbup: bool | None = None
    feedback: str | None = None


def _row(row: RowMapping) -> MessageRow:
    """RowMapping → MessageRow; reference (asyncmy: JSON jako str) → dict, NULL → None."""
    thumbup = row["thumbup"]
    return MessageRow(
        id=row["id"],
        session_id=row["session_id"],
        seq=int(row["seq"]),
        role=row["role"],
        content=row["content"],
        reference=json.loads(row["reference"]) if row["reference"] is not None else None,
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        created_at=float(row["created_at"]),
        create_time=int(row["create_time"]),
        thumbup=bool(thumbup) if thumbup is not None else None,
        feedback=row["feedback"],
    )


async def insert(session: AsyncSession, row: MessageRow) -> None:
    """Wstawia wiadomość; update_time = create_time, reference None → SQL NULL (C9)."""
    await session.execute(
        _INSERT_SQL,
        {
            "id": row.id,
            "session_id": row.session_id,
            "seq": row.seq,
            "role": row.role,
            "content": row.content,
            "reference": (
                json.dumps(row.reference, ensure_ascii=False) if row.reference is not None else None
            ),
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "created_at": row.created_at,
            "create_time": row.create_time,
            "create_date": from_ms(row.create_time),
        },
    )


async def list_by_session(session: AsyncSession, session_id: str) -> list[MessageRow]:
    """Wiadomości sesji w kolejności seq (C1)."""
    rows = (
        (await session.execute(_SELECT_BY_SESSION_SQL, {"session_id": session_id})).mappings().all()
    )
    return [_row(row) for row in rows]


async def list_by_sessions(
    session: AsyncSession, session_ids: Sequence[str]
) -> dict[str, list[MessageRow]]:
    """Wiadomości wielu sesji jednym zapytaniem, w każdej po seq rosnąco (C1).

    Sesja bez wiadomości → brak klucza; [] → {} bez SQL.
    """
    if not session_ids:
        return {}
    rows = (
        (await session.execute(_SELECT_BY_SESSIONS_SQL, {"ids": list(session_ids)}))
        .mappings()
        .all()
    )
    grouped: dict[str, list[MessageRow]] = {}
    for row in rows:
        grouped.setdefault(row["session_id"], []).append(_row(row))
    return grouped


async def next_seq(session: AsyncSession, session_id: str) -> int:
    """Następny seq sesji: COALESCE(MAX(seq), -1) + 1 (C9)."""
    return int((await session.execute(_NEXT_SEQ_SQL, {"session_id": session_id})).scalar_one())


async def get(session: AsyncSession, message_id: str) -> MessageRow | None:
    """Wiadomość po id; None gdy brak (C9)."""
    row = (await session.execute(_GET_SQL, {"id": message_id})).mappings().first()
    return _row(row) if row is not None else None


async def delete_pair(session: AsyncSession, session_id: str, first_seq: int) -> int:
    """Usuwa parę wiadomości (seq, seq+1) sesji; zwraca liczbę usuniętych wierszy (C9)."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            _DELETE_PAIR_SQL, {"session_id": session_id, "seqs": [first_seq, first_seq + 1]}
        ),
    )
    return result.rowcount


async def set_feedback(
    session: AsyncSession,
    message_id: str,
    *,
    thumbup: bool,
    feedback: str | None,
    now_ms: int,
) -> None:
    """Zapisuje ocenę wiadomości; feedback None → SQL NULL (C9)."""
    await session.execute(
        _SET_FEEDBACK_SQL,
        {
            "id": message_id,
            "thumbup": thumbup,
            "feedback": feedback,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def exists(session: AsyncSession, message_id: str) -> bool:
    """Czy wiadomość o podanym id istnieje (C9)."""
    found = (await session.execute(_EXISTS_SQL, {"id": message_id})).first()
    return found is not None
