"""Repozytorium tabeli documents (kontrakt C2.2) — Core ``text()`` z parametrami wiązanymi.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
Format dopisywania linii do ``progress_msg`` (wszędzie ten sam): pusty komunikat → sama
linia; inaczej ``progress_msg + "\n" + linia``; całość ``RIGHT(..., PROGRESS_MSG_MAX)``.
Znak nowej linii przekazywany parametrem ``:nl`` — w bazie ma być prawdziwy ``"\n"``.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

PROGRESS_MSG_MAX = 65536  # znaki; obcinanie od początku (RIGHT liczy znaki, nie bajty)

_INSERT_SQL = text(
    "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type, size, location,"
    " content_hash, source_type, source_ref, chunk_method, parser_config, run, progress,"
    " progress_msg, error, process_begin_at, process_duration, chunk_count, token_count,"
    " enabled, meta_fields, thumbnail, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :dataset_id, :created_by, :name, :suffix, :type, :size, :location,"
    " :content_hash, :source_type, :source_ref, :chunk_method, :parser_config, :run,"
    " :progress, :progress_msg, :error, :process_begin_at, :process_duration, :chunk_count,"
    " :token_count, :enabled, :meta_fields, :thumbnail, :create_time, :create_date,"
    " :update_time, :update_date)"
)

_SELECT_SQL = text(
    "SELECT id, dataset_id, created_by, name, suffix, type, size, location, content_hash,"
    " source_type, source_ref, chunk_method, parser_config, run, progress, progress_msg,"
    " error, process_begin_at, process_duration, chunk_count, token_count, enabled,"
    " meta_fields, thumbnail, create_time, create_date, update_time, update_date"
    " FROM documents WHERE id = :id"
)

_SELECT_MANY_SQL = text(
    "SELECT id, dataset_id, created_by, name, suffix, type, size, location, content_hash,"
    " source_type, source_ref, chunk_method, parser_config, run, progress, progress_msg,"
    " error, process_begin_at, process_duration, chunk_count, token_count, enabled,"
    " meta_fields, thumbnail, create_time, create_date, update_time, update_date"
    " FROM documents WHERE id IN :ids"
).bindparams(bindparam("ids", expanding=True))

_UPDATE_FILE_SQL = text(
    "UPDATE documents SET name = :name, suffix = :suffix, type = :type, size = :size,"
    " location = :location, content_hash = :content_hash,"
    " update_time = :now, update_date = :now_date"
    " WHERE id = :id"
)

_SET_META_FIELDS_SQL = text("UPDATE documents SET meta_fields = :meta_fields WHERE id = :id")

_START_PARSE_SQL = text(
    "UPDATE documents SET run = '1', progress = 0, progress_msg = '', error = NULL,"
    " process_begin_at = :now, process_duration = 0,"
    " update_time = :now, update_date = :now_date"
    " WHERE id IN :ids"
).bindparams(bindparam("ids", expanding=True))

# progress = COALESCE — None pozostawia bieżącą wartość (C2.2).
_APPEND_PROGRESS_SQL = text(
    "UPDATE documents SET progress = COALESCE(:progress, progress),"
    " progress_msg = RIGHT(IF(progress_msg = '', :lines, CONCAT(progress_msg, :nl, :lines)),"
    " :max_msg),"
    " update_time = :now, update_date = :now_date"
    " WHERE id = :id"
)

_FINISH_DONE_SQL = text(
    "UPDATE documents SET"
    " chunk_count = (SELECT COUNT(*) FROM chunks WHERE document_id = :id AND committed = 1),"
    " token_count = (SELECT COALESCE(SUM(token_count), 0) FROM chunks"
    " WHERE document_id = :id AND committed = 1),"
    " run = '3', progress = 1, error = NULL, process_duration = :duration_s,"
    " update_time = :now, update_date = :now_date"
    " WHERE id = :id"
)

# JOIN tasks — dokument zmieniany tylko dla zadań parse_document (C2.2, §6.3).
_FAIL_BY_TASK_SQL = text(
    "UPDATE documents d JOIN tasks t ON t.document_id = d.id"
    " SET d.run = '4', d.error = t.error,"
    " d.progress_msg = RIGHT(IF(d.progress_msg = '', CONCAT(:prefix, COALESCE(t.error, '')),"
    " CONCAT(d.progress_msg, :nl, :prefix, COALESCE(t.error, ''))), :max_msg),"
    " d.update_time = :now, d.update_date = :now_date"
    " WHERE t.public_id = :pid AND t.task_type = 'parse_document'"
)

_CANCEL_BY_TASK_SQL = text(
    "UPDATE documents d JOIN tasks t ON t.document_id = d.id"
    " SET d.run = '2',"
    " d.progress_msg = RIGHT(IF(d.progress_msg = '', :line, CONCAT(d.progress_msg, :nl, :line)),"
    " :max_msg),"
    " d.update_time = :now, d.update_date = :now_date"
    " WHERE t.public_id = :pid AND t.task_type = 'parse_document'"
)

# Wołane PRZED zmianą statusu zadań (C2.2) — istnienie zadania queued decyduje.
_CANCEL_QUEUED_SQL = text(
    "UPDATE documents SET run = '2',"
    " progress_msg = RIGHT(IF(progress_msg = '', :line, CONCAT(progress_msg, :nl, :line)),"
    " :max_msg),"
    " update_time = :now, update_date = :now_date"
    " WHERE id IN :ids"
    " AND EXISTS (SELECT 1 FROM tasks t WHERE t.document_id = documents.id"
    " AND t.task_type = 'parse_document' AND t.status = 'queued')"
).bindparams(bindparam("ids", expanding=True))

_DELETE_MANY_SQL = text("DELETE FROM documents WHERE id IN :ids").bindparams(
    bindparam("ids", expanding=True)
)


@dataclass(frozen=True)
class DocumentRow:
    """Wiersz `documents` — wszystkie kolumny DDL (kontrakt C2.2)."""

    id: str
    dataset_id: str
    created_by: str
    name: str
    suffix: str
    type: str
    size: int
    location: str  # klucz storage (document_key)
    content_hash: str
    source_type: str
    source_ref: str | None
    chunk_method: str
    parser_config: dict[str, Any]
    run: str  # '0'..'5'
    progress: float
    progress_msg: str
    error: str | None
    process_begin_at: int | None
    process_duration: float
    chunk_count: int
    token_count: int
    enabled: bool
    meta_fields: dict[str, Any]
    thumbnail: str | None
    create_time: int
    create_date: datetime
    update_time: int
    update_date: datetime


def clock_hms(now_ms: int) -> str:
    """Godzina HH:MM:SS w UTC z milisekund epoki (prefiks linii progress_msg)."""
    return from_ms(now_ms).strftime("%H:%M:%S")


def _json_column(value: Any) -> Any:
    """JSON z bazy może przyjść jako str — wtedy parsowany (jak _to_task_row)."""
    return json.loads(value) if isinstance(value, str) else value


def _row(row: RowMapping) -> DocumentRow:
    """RowMapping → DocumentRow; JSON → dict, TINYINT(1) → bool (C2.2)."""
    return DocumentRow(
        id=row["id"],
        dataset_id=row["dataset_id"],
        created_by=row["created_by"],
        name=row["name"],
        suffix=row["suffix"],
        type=row["type"],
        size=int(row["size"]),
        location=row["location"],
        content_hash=row["content_hash"],
        source_type=row["source_type"],
        source_ref=row["source_ref"],
        chunk_method=row["chunk_method"],
        parser_config=_json_column(row["parser_config"]),
        run=row["run"],
        progress=float(row["progress"]),
        progress_msg=row["progress_msg"],
        error=row["error"],
        process_begin_at=row["process_begin_at"],
        process_duration=float(row["process_duration"]),
        chunk_count=int(row["chunk_count"]),
        token_count=int(row["token_count"]),
        enabled=bool(row["enabled"]),
        meta_fields=_json_column(row["meta_fields"]),
        thumbnail=row["thumbnail"],
        create_time=int(row["create_time"]),
        create_date=row["create_date"],
        update_time=int(row["update_time"]),
        update_date=row["update_date"],
    )


async def insert(session: AsyncSession, row: DocumentRow) -> None:
    """Wstawia dokument — wszystkie kolumny z wiersza, także create_*/update_* (C2.2)."""
    await session.execute(
        _INSERT_SQL,
        {
            "id": row.id,
            "dataset_id": row.dataset_id,
            "created_by": row.created_by,
            "name": row.name,
            "suffix": row.suffix,
            "type": row.type,
            "size": row.size,
            "location": row.location,
            "content_hash": row.content_hash,
            "source_type": row.source_type,
            "source_ref": row.source_ref,
            "chunk_method": row.chunk_method,
            "parser_config": json.dumps(row.parser_config, ensure_ascii=False),
            "run": row.run,
            "progress": row.progress,
            "progress_msg": row.progress_msg,
            "error": row.error,
            "process_begin_at": row.process_begin_at,
            "process_duration": row.process_duration,
            "chunk_count": row.chunk_count,
            "token_count": row.token_count,
            "enabled": int(row.enabled),
            "meta_fields": json.dumps(row.meta_fields, ensure_ascii=False),
            "thumbnail": row.thumbnail,
            "create_time": row.create_time,
            "create_date": row.create_date,
            "update_time": row.update_time,
            "update_date": row.update_date,
        },
    )


async def get(session: AsyncSession, document_id: str) -> DocumentRow | None:
    """Dokument po identyfikatorze; None gdy brak."""
    found = (await session.execute(_SELECT_SQL, {"id": document_id})).mappings().first()
    return _row(found) if found is not None else None


async def get_many(session: AsyncSession, document_ids: Sequence[str]) -> list[DocumentRow]:
    """Dokumenty po identyfikatorach (kolejność dowolna); [] → [] bez SQL (C2.2)."""
    if not document_ids:
        return []
    rows = (await session.execute(_SELECT_MANY_SQL, {"ids": list(document_ids)})).mappings().all()
    return [_row(row) for row in rows]


async def update_file(  # noqa: PLR0913 — kształt kontraktu C2.2
    session: AsyncSession,
    document_id: str,
    *,
    name: str,
    suffix: str,
    type: str,
    size: int,
    location: str,
    content_hash: str,
    now_ms: int,
) -> None:
    """Podmienia metadane pliku (replace) z update_time/date (C2.2)."""
    await session.execute(
        _UPDATE_FILE_SQL,
        {
            "id": document_id,
            "name": name,
            "suffix": suffix,
            "type": type,
            "size": size,
            "location": location,
            "content_hash": content_hash,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def set_meta_fields(
    session: AsyncSession, document_id: str, *, meta_fields: dict[str, Any]
) -> None:
    """Zapisuje ``meta_fields`` bez zmiany znaczników czasu (K12 §4, set_source_meta)."""
    await session.execute(
        _SET_META_FIELDS_SQL,
        {"id": document_id, "meta_fields": json.dumps(meta_fields, ensure_ascii=False)},
    )


async def start_parse(session: AsyncSession, document_ids: Sequence[str], *, now_ms: int) -> None:
    """run='1', zerowanie postępu i błędu, process_begin_at (C2.2); [] → bez SQL."""
    if not document_ids:
        return
    await session.execute(
        _START_PARSE_SQL,
        {"ids": list(document_ids), "now": now_ms, "now_date": from_ms(now_ms)},
    )


async def append_progress(
    session: AsyncSession,
    document_id: str,
    *,
    progress: float | None,
    lines: str,
    now_ms: int,
) -> None:
    """Dopisuje linie do progress_msg (obcinane RIGHT do 65536 znaków) (C2.2)."""
    await session.execute(
        _APPEND_PROGRESS_SQL,
        {
            "id": document_id,
            "progress": progress,
            "lines": lines,
            "nl": "\n",
            "max_msg": PROGRESS_MSG_MAX,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def finish_done(
    session: AsyncSession, document_id: str, *, duration_s: float, now_ms: int
) -> None:
    """run='3', progress=1, liczniki z chunków committed=1, process_duration (C2.2)."""
    await session.execute(
        _FINISH_DONE_SQL,
        {
            "id": document_id,
            "duration_s": duration_s,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def fail_by_task(session: AsyncSession, task_public_id: str, *, now_ms: int) -> None:
    """Dokument zadania parse_document → run='4', error z zadania, linia [ERROR] (§6.3)."""
    await session.execute(
        _FAIL_BY_TASK_SQL,
        {
            "pid": task_public_id,
            "prefix": f"{clock_hms(now_ms)} [ERROR] ",
            "nl": "\n",
            "max_msg": PROGRESS_MSG_MAX,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def cancel_by_task(session: AsyncSession, task_public_id: str, *, now_ms: int) -> None:
    """Dokument zadania parse_document → run='2', linia „Task has been cancelled.” (§6.3)."""
    await session.execute(
        _CANCEL_BY_TASK_SQL,
        {
            "pid": task_public_id,
            "line": f"{clock_hms(now_ms)} Task has been cancelled.",
            "nl": "\n",
            "max_msg": PROGRESS_MSG_MAX,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def cancel_queued(session: AsyncSession, document_ids: Sequence[str], *, now_ms: int) -> None:
    """Dokumenty z listy mające zadanie parse_document queued → run='2' (C2.2); [] → bez SQL."""
    if not document_ids:
        return
    await session.execute(
        _CANCEL_QUEUED_SQL,
        {
            "ids": list(document_ids),
            "line": f"{clock_hms(now_ms)} Task has been cancelled.",
            "nl": "\n",
            "max_msg": PROGRESS_MSG_MAX,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def delete_many(session: AsyncSession, document_ids: Sequence[str]) -> int:
    """Usuwa dokumenty (chunki, wektory, zadania — kaskadą FK); zwraca rowcount (C2.2)."""
    if not document_ids:
        return 0
    result = await session.execute(_DELETE_MANY_SQL, {"ids": list(document_ids)})
    return cast(CursorResult[Any], result).rowcount
