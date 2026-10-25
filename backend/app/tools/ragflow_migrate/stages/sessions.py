"""Etap ``sessions``: ``conversation`` → ``chat_sessions`` + ``chat_messages`` (kontrakt §3).

Rozstrzyganie wiersza ``conversation`` (czyste funkcje, bez bazy) mieszka obok, w
:mod:`app.tools.ragflow_migrate.stages.sessions_rows` — razem przekraczały limit 400 linii pliku;
BRIEF WP E4-6b2 dopuszcza pomocnicze moduły w pakiecie narzędzia.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageInventory, StageResult
from app.tools.ragflow_migrate.stages.sessions_rows import resolve_session

#: Kolumny ``chat_sessions`` pisane przez etap (kolejność = lista INSERT); alembic ``0001_initial``.
COLUMNS: tuple[str, ...] = (
    "id",
    "chat_id",
    "name",
    "user_id",
    "owner_id",
    "source",
    "message_count",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

#: Kolumny ``chat_messages`` pisane przez etap (kolejność = lista INSERT).
MESSAGE_COLUMNS: tuple[str, ...] = (
    "id",
    "session_id",
    "seq",
    "role",
    "content",
    "reference",
    "thumbup",
    "feedback",
    "prompt_tokens",
    "completion_tokens",
    "created_at",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

_SESSION_COLUMN_LIST = ", ".join(COLUMNS)
_MESSAGE_COLUMN_LIST = ", ".join(MESSAGE_COLUMNS)
# Nazwy kolumn pochodzą ze stałych (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = (
    f"INSERT INTO chat_sessions ({_SESSION_COLUMN_LIST})"  # noqa: S608 — kolumny ze stałej
    f" VALUES ({', '.join(':' + c for c in COLUMNS)})"
)
_UPDATE = f"UPDATE chat_sessions SET {', '.join(f'{c} = :{c}' for c in COLUMNS)} WHERE id = :id"  # noqa: S608
_SELECT_EXISTING = f"SELECT {_SESSION_COLUMN_LIST} FROM chat_sessions WHERE id IN :ids"  # noqa: S608
_INSERT_MESSAGE = (
    f"INSERT INTO chat_messages ({_MESSAGE_COLUMN_LIST})"  # noqa: S608 — kolumny ze stałej
    f" VALUES ({', '.join(':' + c for c in MESSAGE_COLUMNS)})"
)
_SELECT_MESSAGES = (
    f"SELECT {_MESSAGE_COLUMN_LIST} FROM chat_messages"  # noqa: S608
    " WHERE session_id IN :ids ORDER BY session_id, seq"
)
_DELETE_MESSAGES = "DELETE FROM chat_messages WHERE session_id = :session_id"
_SELECT_TARGET_IDS = "SELECT id FROM chat_sessions WHERE id IN :ids"
_SELECT_CHAT_OWNERS = "SELECT id, tenant_id FROM chats"


def _empty_result() -> StageResult:
    """Wynik etapu bez tabeli ``conversation`` w źródle (kontrakt §3)."""
    return StageResult(
        stage="sessions",
        source_count=0,
        created=0,
        updated=0,
        skipped=0,
        target_count=0,
        issues=[],
    )


async def _chat_owners(session: AsyncSession, ctx: RunContext) -> dict[str, str]:
    """``chat_id`` → właściciel czatu w celu (``chats.tenant_id``) — kontrakt §1 i §3.

    Zbiór zawęża ``ctx.shared['chat_ids']`` (wynik etapu ``chats``, także z dry-run); gdy klucza
    nie ma, bierzemy wszystkie czaty celu (``SELECT id FROM chats``).
    """
    rows = (await session.execute(text(_SELECT_CHAT_OWNERS))).all()
    owners = {str(chat_id): str(tenant_id) for chat_id, tenant_id in rows}
    shared = ctx.shared.get("chat_ids")
    if shared is None:
        return owners
    wanted = {str(value) for value in shared}
    return {chat_id: owner for chat_id, owner in owners.items() if chat_id in wanted}


def _normalized(column: str, value: Any) -> Any:
    """Wartość kolumny do porównania idempotencji; ``reference`` porównujemy po ``json.loads``.

    ``TINYINT(1)`` może wrócić z bazy jako ``int``, a wyliczyć się jako ``bool`` — bool sprowadzamy
    do ``0``/``1``, by porównanie nie różnicowało zapisu (§3).
    """
    if column == "reference":
        if value is None:
            return None
        return json.loads(value) if isinstance(value, str | bytes) else value
    if isinstance(value, bool):
        return str(int(value))
    return str(value)


def _row_unchanged(existing: Mapping[str, Any], computed: Mapping[str, Any]) -> bool:
    """True, gdy każda kolumna wiersza istniejącego równa się wyliczonej."""
    return all(
        _normalized(column, existing[column]) == _normalized(column, computed[column])
        for column in COLUMNS
    )


def _messages_unchanged(
    stored: Sequence[Mapping[str, Any]], computed: Sequence[Mapping[str, Any]]
) -> bool:
    """True, gdy uporządkowana lista wiadomości celu równa się wyliczonej (kontrakt §3)."""
    if len(stored) != len(computed):
        return False
    return all(
        all(
            _normalized(column, existing[column]) == _normalized(column, target[column])
            for column in MESSAGE_COLUMNS
        )
        for existing, target in zip(stored, computed, strict=True)
    )


async def _fetch_existing(session: AsyncSession, ids: list[str]) -> dict[str, Mapping[str, Any]]:
    """Wiersze ``chat_sessions`` dla podanych id (klucz = id); puste ``ids`` → pusta mapa."""
    if not ids:
        return {}
    statement = text(_SELECT_EXISTING).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {
        str(row["id"]): {column: row[column] for column in COLUMNS}
        for row in result.mappings().all()
    }


async def _fetch_messages(
    session: AsyncSession, ids: list[str]
) -> dict[str, list[Mapping[str, Any]]]:
    """Wiadomości sesji celu w kolejności ``seq`` (klucz = ``session_id``)."""
    if not ids:
        return {}
    statement = text(_SELECT_MESSAGES).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    messages: dict[str, list[Mapping[str, Any]]] = {}
    for row in result.mappings().all():
        messages.setdefault(str(row["session_id"]), []).append(
            {column: row[column] for column in MESSAGE_COLUMNS}
        )
    return messages


async def _write_messages(session: AsyncSession, messages: list[dict[str, Any]]) -> None:
    """Wstawia wiadomości sesji; wiersz sesji musi już istnieć (FK, kontrakt §3)."""
    for message in messages:
        await session.execute(text(_INSERT_MESSAGE), message)


async def _target_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w ``chat_sessions`` po etapie."""
    if not ids:
        return set()
    statement = text(_SELECT_TARGET_IDS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


def _source_chat_ids(src: Source) -> set[str]:
    """Id czatów źródła (``dialog``) — do uwag ``plan`` (kontrakt §3)."""
    return {str(row["id"]) for row in src.rows("dialog")} if src.has_table("dialog") else set()


class SessionsStage:
    """``conversation`` → ``chat_sessions`` + ``chat_messages`` (kontrakt §3)."""

    name = "sessions"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz: licznik ``conversation`` i uwagi (bez zapisu, kontrakt §3)."""
        if not src.has_table("conversation"):
            return StageInventory(stage=self.name, source_counts={}, issues=[], not_migrated={})
        rows = src.rows("conversation")
        owners = {chat_id: "" for chat_id in _source_chat_ids(src)}
        issues = []
        for row in rows:
            _session, _messages, row_issues = resolve_session(row, owners, None, 0)
            issues.extend(row_issues)
        return StageInventory(
            stage=self.name,
            source_counts={"conversation": len(rows)},
            issues=issues,
            not_migrated={},
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapis ``conversation`` → ``chat_sessions`` + ``chat_messages`` (idempotencja po §3).

        ``--since`` (kontrakt §2) bierze do upsertu tylko rozmowy zmienione po ``since_ms``;
        niezmienione sesje zostają w celu nietknięte razem z wiadomościami.
        """
        if not src.has_table("conversation"):
            return _empty_result()
        rows = src.rows_changed("conversation", ctx.since_ms)
        source_ids = [str(row["id"]) for row in rows]
        existing = await _fetch_existing(session, source_ids)
        stored_times = {
            session_id: (int(row["create_time"]), int(row["update_time"]))
            for session_id, row in existing.items()
        }
        stored_messages = await _fetch_messages(session, source_ids)
        owners = await _chat_owners(session, ctx)
        created = updated = skipped = 0
        issues = []
        for row in rows:
            session_id = str(row["id"])
            target, messages, row_issues = resolve_session(
                row, owners, stored_times.get(session_id), ctx.clock.now_ms()
            )
            issues.extend(row_issues)
            if target is None:
                skipped += 1
                continue
            current = existing.get(session_id)
            if current is None:
                await session.execute(text(_INSERT), target)
                await _write_messages(session, messages)
                created += 1
            elif _row_unchanged(current, target) and _messages_unchanged(
                stored_messages.get(session_id, []), messages
            ):
                skipped += 1
            else:
                await session.execute(text(_UPDATE), target)
                # UNIQUE (session_id, seq): najpierw usuwamy wiadomości sesji, potem wstawiamy nowe.
                await session.execute(text(_DELETE_MESSAGES), {"session_id": session_id})
                await _write_messages(session, messages)
                updated += 1
        present = await _target_ids(session, source_ids)
        return StageResult(
            stage=self.name,
            source_count=len(rows),
            created=created,
            updated=updated,
            skipped=skipped,
            target_count=len(present),
            issues=issues,
        )
