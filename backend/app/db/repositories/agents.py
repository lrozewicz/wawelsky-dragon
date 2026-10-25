"""Repozytorium tabeli `agents` (CONTRACT E6-3f §C2, K2 §6).

SQL przez ``text()``, bez ``commit``/``rollback`` — transakcję otwiera ``app.db.uow.transaction``.
``id``/``tenant_id``/``created_by`` mają kolację `ascii_bin`, a parametry z żądania są w
`utf8mb4_*`: porównania parametru z kolumną ``CHAR(32)`` idą przez ``CAST(:x AS BINARY)``
(DEC-087/090). ``dsl`` i ``unsupported_components`` to JSON — dekodowane przy odczycie.
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
    "id, tenant_id, created_by, title, description, avatar, permission, canvas_category,"
    " tags, dsl, unsupported_components, create_time, create_date, update_time, update_date"
)

_GET_BY_ID_SQL = text(
    f"SELECT {_COLUMNS} FROM agents WHERE id = CAST(:agent_id AS BINARY)"  # noqa: S608
)

_LIST_BY_TENANT_SQL = text(
    f"SELECT {_COLUMNS} FROM agents WHERE tenant_id = :tenant_id"  # noqa: S608
    " ORDER BY update_time DESC, id"
)

_INSERT_SQL = text(
    "INSERT INTO agents (id, tenant_id, created_by, title, description, avatar, permission,"
    " canvas_category, tags, dsl, unsupported_components, create_time, create_date,"
    " update_time, update_date)"
    " VALUES (:id, :tenant_id, :created_by, :title, :description, :avatar, :permission,"
    " :canvas_category, :tags, :dsl, :unsupported_components, :now_ms, :date, :now_ms, :date)"
)

_UPDATE_SQL = text(
    "UPDATE agents SET title = :title, description = :description, avatar = :avatar,"
    " permission = :permission, canvas_category = :canvas_category, tags = :tags,"
    " dsl = :dsl, unsupported_components = :unsupported_components,"
    " update_time = :now_ms, update_date = :date"
    " WHERE id = CAST(:agent_id AS BINARY)"
)

_DELETE_SQL = text("DELETE FROM agents WHERE id = CAST(:agent_id AS BINARY)")


@dataclass(frozen=True)
class AgentRow:
    """Wiersz `agents`; `dsl`/`unsupported_components` zdekodowane (CONTRACT §C2)."""

    id: str
    tenant_id: str
    created_by: str
    title: str
    description: str | None
    avatar: str | None
    permission: str
    canvas_category: str
    tags: str
    dsl: dict[str, Any]
    unsupported_components: list[str] | None
    create_time: int
    create_date: datetime
    update_time: int
    update_date: datetime


def _row(row: RowMapping) -> AgentRow:
    """RowMapping → AgentRow; kolumny JSON (asyncmy: str) → struktury Pythona."""
    raw_unsupported = row["unsupported_components"]
    return AgentRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        created_by=row["created_by"],
        title=row["title"],
        description=row["description"],
        avatar=row["avatar"],
        permission=row["permission"],
        canvas_category=row["canvas_category"],
        tags=row["tags"],
        dsl=json.loads(row["dsl"]),
        unsupported_components=(
            json.loads(raw_unsupported) if raw_unsupported is not None else None
        ),
        create_time=int(row["create_time"]),
        create_date=row["create_date"],
        update_time=int(row["update_time"]),
        update_date=row["update_date"],
    )


async def insert(  # noqa: PLR0913 — kolumny tabeli §C2
    session: AsyncSession,
    *,
    id: str,  # nazwa pola z kontraktu §C2
    tenant_id: str,
    created_by: str,
    title: str,
    description: str | None,
    avatar: str | None,
    permission: str,
    canvas_category: str,
    tags: str,
    dsl: dict[str, Any],
    unsupported_components: list[str] | None,
    now_ms: int,
) -> None:
    """Wstawia agenta; czasy z zegara wołającego (§C2)."""
    date = from_ms(now_ms)
    await session.execute(
        _INSERT_SQL,
        {
            "id": id,
            "tenant_id": tenant_id,
            "created_by": created_by,
            "title": title,
            "description": description,
            "avatar": avatar,
            "permission": permission,
            "canvas_category": canvas_category,
            "tags": tags,
            "dsl": json.dumps(dsl, ensure_ascii=False),
            "unsupported_components": (
                json.dumps(unsupported_components, ensure_ascii=False)
                if unsupported_components is not None
                else None
            ),
            "now_ms": now_ms,
            "date": date,
        },
    )


async def get_by_id(session: AsyncSession, agent_id: str) -> AgentRow | None:
    """Agent po identyfikatorze; None gdy brak."""
    found = (await session.execute(_GET_BY_ID_SQL, {"agent_id": agent_id})).mappings().first()
    return _row(found) if found is not None else None


async def list_by_tenant(session: AsyncSession, tenant_id: str) -> list[AgentRow]:
    """Agenci właściciela, najnowsi po ``update_time`` DESC, id (§C2)."""
    rows = (await session.execute(_LIST_BY_TENANT_SQL, {"tenant_id": tenant_id})).mappings().all()
    return [_row(row) for row in rows]


async def update(  # noqa: PLR0913 — kolumny edytowalne §C2
    session: AsyncSession,
    *,
    agent_id: str,
    title: str,
    description: str | None,
    avatar: str | None,
    permission: str,
    canvas_category: str,
    tags: str,
    dsl: dict[str, Any],
    unsupported_components: list[str] | None,
    now_ms: int,
) -> None:
    """Podmienia pola edytowalne i podbija czasy (§C2)."""
    date = from_ms(now_ms)
    await session.execute(
        _UPDATE_SQL,
        {
            "agent_id": agent_id,
            "title": title,
            "description": description,
            "avatar": avatar,
            "permission": permission,
            "canvas_category": canvas_category,
            "tags": tags,
            "dsl": json.dumps(dsl, ensure_ascii=False),
            "unsupported_components": (
                json.dumps(unsupported_components, ensure_ascii=False)
                if unsupported_components is not None
                else None
            ),
            "now_ms": now_ms,
            "date": date,
        },
    )


async def delete_by_id(session: AsyncSession, agent_id: str) -> int:
    """Usuwa agenta (kaskada FK czyści sesje agenta, §C2)."""
    result = await session.execute(_DELETE_SQL, {"agent_id": agent_id})
    return int(cast("CursorResult[Any]", result).rowcount)
