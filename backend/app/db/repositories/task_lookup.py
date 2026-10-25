"""Odczyty i kasowanie wierszy tabeli tasks dla ingestii (kontrakt C3) — Core ``text()``.

Osobny moduł z powodu limitu 400 linii ``tasks.py``. Bez ``commit``/``rollback`` —
transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

_INTERNAL_ID_SQL = text("SELECT id FROM tasks WHERE public_id = :public_id")

_ACTIVE_PARSE_SQL = text(
    "SELECT DISTINCT document_id FROM tasks"
    " WHERE document_id IN :ids AND task_type = 'parse_document'"
    " AND status IN ('queued', 'running')"
).bindparams(bindparam("ids", expanding=True))

# Deduplikacja przeglądu spisu (K21 §2 p. 4): dokument z zadaniem build_outline w kolejce pomijamy.
_ACTIVE_BUILD_OUTLINE_SQL = text(
    "SELECT DISTINCT document_id FROM tasks"
    " WHERE document_id IN :ids AND task_type = 'build_outline'"
    " AND status IN ('queued', 'running')"
).bindparams(bindparam("ids", expanding=True))

_DELETE_BY_DOCUMENTS_SQL = text("DELETE FROM tasks WHERE document_id IN :ids").bindparams(
    bindparam("ids", expanding=True)
)

# Digest ostatniego ukończonego parsowania dokumentu (referencja dla re-parse, 05 §5.4).
_LAST_DONE_DIGEST_SQL = text(
    "SELECT digest FROM tasks"
    " WHERE document_id = :document_id AND task_type = 'parse_document'"
    " AND status = 'done' AND public_id <> :exclude_public_id"
    " ORDER BY finished_at DESC, id DESC"
    " LIMIT 1"
)


async def internal_id(session: AsyncSession, public_id: str) -> int | None:
    """BIGINT ``tasks.id`` po public_id; None gdy zadanie nie istnieje (kontrakt C3)."""
    found = (await session.execute(_INTERNAL_ID_SQL, {"public_id": public_id})).scalar()
    return cast("int | None", found)


async def active_parse_documents(session: AsyncSession, document_ids: Sequence[str]) -> set[str]:
    """Identyfikatory dokumentów z zadaniem parse_document queued/running; [] → set() (C3)."""
    if not document_ids:
        return set()
    rows = (await session.execute(_ACTIVE_PARSE_SQL, {"ids": list(document_ids)})).scalars().all()
    return {str(row) for row in rows}


async def active_build_outline_documents(
    session: AsyncSession, document_ids: Sequence[str]
) -> set[str]:
    """Dokumenty z zadaniem ``build_outline`` w kolejce (queued/running); [] → set()."""
    if not document_ids:
        return set()
    rows = (
        (await session.execute(_ACTIVE_BUILD_OUTLINE_SQL, {"ids": list(document_ids)}))
        .scalars()
        .all()
    )
    return {str(row) for row in rows}


async def delete_by_documents(session: AsyncSession, document_ids: Sequence[str]) -> int:
    """Kasuje wszystkie zadania dokumentów; [] → 0 bez SQL (DOC:1508 filter_delete).

    Upstream ``POST /documents/ingest`` z ``delete=true`` usuwa zadania dokumentu przed
    ponownym parsowaniem — dzięki temu ponowne zlecenie nie trafia na ``_reject_active``.
    """
    if not document_ids:
        return 0
    result = await session.execute(_DELETE_BY_DOCUMENTS_SQL, {"ids": list(document_ids)})
    return cast("CursorResult[Any]", result).rowcount


async def last_done_digest(
    session: AsyncSession, document_id: str, *, exclude_public_id: str
) -> str | None:
    """Digest ostatniego done zadania parse_document (finished_at DESC, id DESC), poza exclude."""
    found = (
        await session.execute(
            _LAST_DONE_DIGEST_SQL,
            {"document_id": document_id, "exclude_public_id": exclude_public_id},
        )
    ).scalar()
    return None if found is None else str(found)
