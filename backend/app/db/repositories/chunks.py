"""Repozytorium tabeli chunks (kontrakt C2.3) — Core ``text()`` z parametrami wiązanymi.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import xxhash
from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms


@dataclass(frozen=True)
class ChunkInsert:
    """Nowy chunk przed commitem zadania (kontrakt C2.3)."""

    id: str  # chunk_id(...)
    document_id: str
    dataset_id: str
    task_id: int  # tasks.id (BIGINT)
    ordinal: int
    chunk_type: str
    content: str
    content_llm: str | None
    content_ft: str
    content_stem: str
    title_ft: str
    keywords: tuple[str, ...]  # → JSON
    questions: tuple[str, ...]  # → JSON
    important_ft: str
    question_ft: str
    positions: tuple[tuple[int, int, int, int, int], ...]  # () → NULL; inaczej JSON listy list
    page_from: int | None
    page_to: int | None
    token_count: int
    embed_source: str  # "content" | "questions"


# available=1 i committed=0 na stałe — insert dotyczy wyłącznie nowych chunków (C2.3).
_INSERT_SQL = text(
    "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type, content,"
    " content_llm, content_ft, content_stem, title_ft, keywords, questions, important_ft,"
    " question_ft, positions, page_from, page_to, task_id, available, committed,"
    " token_count, embed_source, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :document_id, :dataset_id, :ordinal, :chunk_type, :content, :content_llm,"
    " :content_ft, :content_stem, :title_ft, :keywords, :questions, :important_ft,"
    " :question_ft, :positions, :page_from, :page_to, :task_id, 1, 0, :token_count,"
    " :embed_source, :now, :now_date, :now, :now_date)"
)

_DELETE_UNCOMMITTED_SQL = text("DELETE FROM chunks WHERE task_id = :task_id AND committed = 0")

_COMMIT_DELETE_SQL = text(
    "DELETE FROM chunks WHERE document_id = :document_id"
    " AND (task_id <> :task_id OR task_id IS NULL)"
)

_COMMIT_UPDATE_SQL = text(
    "UPDATE chunks SET committed = 1, update_time = :now, update_date = :now_date"
    " WHERE document_id = :document_id AND task_id = :task_id"
)

_COUNT_ALL_SQL = text("SELECT COUNT(*) FROM chunks WHERE document_id = :id")

_COUNT_COMMITTED_SQL = text(
    "SELECT COUNT(*) FROM chunks WHERE document_id = :id AND committed = :committed"
)


def chunk_id(document_id: str, task_public_id: str, ordinal: int) -> str:
    """Deterministyczny identyfikator chunka: xxh64 z „dokument:zadanie:porządek”."""
    return xxhash.xxh64_hexdigest(f"{document_id}:{task_public_id}:{ordinal}".encode())


def _params(row: ChunkInsert, *, now_ms: int) -> dict[str, Any]:
    """ChunkInsert → parametry INSERT; krotki JSON-owe jako listy (C2.3)."""
    positions = (
        None
        if not row.positions
        else json.dumps([list(p) for p in row.positions], ensure_ascii=False)
    )
    return {
        "id": row.id,
        "document_id": row.document_id,
        "dataset_id": row.dataset_id,
        "task_id": row.task_id,
        "ordinal": row.ordinal,
        "chunk_type": row.chunk_type,
        "content": row.content,
        "content_llm": row.content_llm,
        "content_ft": row.content_ft,
        "content_stem": row.content_stem,
        "title_ft": row.title_ft,
        "keywords": json.dumps(list(row.keywords), ensure_ascii=False),
        "questions": json.dumps(list(row.questions), ensure_ascii=False),
        "important_ft": row.important_ft,
        "question_ft": row.question_ft,
        "positions": positions,
        "page_from": row.page_from,
        "page_to": row.page_to,
        "token_count": row.token_count,
        "embed_source": row.embed_source,
        "now": now_ms,
        "now_date": from_ms(now_ms),
    }


async def insert_many(session: AsyncSession, rows: Sequence[ChunkInsert], *, now_ms: int) -> None:
    """Wstawia chunki w stanie roboczym (committed=0, available=1); [] → bez SQL (C2.3)."""
    if not rows:
        return
    await session.execute(_INSERT_SQL, [_params(row, now_ms=now_ms) for row in rows])


async def delete_uncommitted_by_task(session: AsyncSession, task_id: int) -> int:
    """Usuwa nierozliczone chunki zadania (committed=0); zwraca liczbę usuniętych (C2.3)."""
    result = await session.execute(_DELETE_UNCOMMITTED_SQL, {"task_id": task_id})
    return cast(CursorResult[Any], result).rowcount


async def commit_task(
    session: AsyncSession, document_id: str, task_id: int, *, now_ms: int
) -> None:
    """Rozlicza zadanie: najpierw DELETE obcych/starych chunków, potem committed=1 (C2.3)."""
    await session.execute(_COMMIT_DELETE_SQL, {"document_id": document_id, "task_id": task_id})
    await session.execute(
        _COMMIT_UPDATE_SQL,
        {
            "document_id": document_id,
            "task_id": task_id,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def count(session: AsyncSession, document_id: str, *, committed: bool | None = True) -> int:
    """Liczba chunków dokumentu; None = wszystkie, True/False = filtr committed (C2.3)."""
    sql = _COUNT_COMMITTED_SQL if committed is not None else _COUNT_ALL_SQL
    params: dict[str, Any] = {"id": document_id}
    if committed is not None:
        params["committed"] = int(committed)
    return cast("int", (await session.execute(sql, params)).scalar_one())


# ---------------------------------------------------------------------------
# API chunków (E1-9a C3.1) — odczyt, ręczny insert, update, switch, delete, liczniki.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkRecord:
    """Chunk dla API (E1-9a C3.1)."""

    id: str
    document_id: str
    dataset_id: str
    document_name: str  # documents.name (JOIN)
    ordinal: int
    chunk_type: str
    content: str
    keywords: list[str]  # JSON → list
    questions: list[str]  # JSON → list
    tags: list[str]  # JSON → list
    positions: list[list[int]]  # NULL → []
    image_id: str | None
    available: bool
    token_count: int
    create_time: int
    update_time: int


_RECORD_SELECT = (
    "SELECT c.id, c.document_id, c.dataset_id, d.name AS document_name, c.ordinal,"
    " c.chunk_type, c.content, c.keywords, c.questions, c.tags, c.positions, c.image_id,"
    " c.available, c.token_count, c.create_time, c.update_time"
)
_RECORD_FROM = " FROM chunks c JOIN documents d ON d.id = c.document_id"
_DOC_COMMITTED_WHERE = " WHERE c.document_id = :document_id AND c.committed = 1"
# Filtry list_for_document doklejane do WHERE — wartości zawsze parametrami wiązanymi.
_KEYWORDS_WHERE = " AND c.content LIKE CONCAT('%', :keywords, '%')"
_CHUNK_ID_WHERE = " AND c.id = :chunk_id"
_AVAILABLE_WHERE = " AND c.available = :available"
_LIST_PAGE_SUFFIX = " ORDER BY c.ordinal, c.id LIMIT :limit OFFSET :offset"

_GET_RECORD_SQL = text(_RECORD_SELECT + _RECORD_FROM + " WHERE c.id = :id AND c.committed = 1")

_MAX_ORDINAL_SQL = text(
    "SELECT COALESCE(MAX(ordinal), -1) FROM chunks WHERE document_id = :document_id"
)

# Jak _INSERT_SQL, ale task_id = NULL i committed = 1 — zapis chunka ręcznego (C3.1).
_INSERT_MANUAL_SQL = text(
    "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type, content,"
    " content_llm, content_ft, content_stem, title_ft, keywords, questions, important_ft,"
    " question_ft, positions, page_from, page_to, task_id, available, committed,"
    " token_count, embed_source, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :document_id, :dataset_id, :ordinal, :chunk_type, :content, :content_llm,"
    " :content_ft, :content_stem, :title_ft, :keywords, :questions, :important_ft,"
    " :question_ft, :positions, :page_from, :page_to, NULL, 1, 1, :token_count,"
    " :embed_source, :now, :now_date, :now, :now_date)"
)

# Biała lista kolumn update_content (DDL chunks); kolumny JSON-owe osobno (C3.1).
_CONTENT_COLUMNS = frozenset(
    {
        "content",
        "content_ft",
        "content_stem",
        "keywords",
        "questions",
        "important_ft",
        "question_ft",
        "tags",
        "positions",
        "available",
        "token_count",
        "embed_source",
    }
)
_JSON_CONTENT_COLUMNS = frozenset({"keywords", "questions", "tags", "positions"})

_SET_AVAILABLE_SQL = text(
    "UPDATE chunks SET available = :available, update_time = :now, update_date = :now_date"
    " WHERE document_id = :document_id AND id IN :ids"
).bindparams(bindparam("ids", expanding=True))

_DELETE_BY_IDS_SQL = text(
    "DELETE FROM chunks WHERE document_id = :document_id AND id IN :ids"
).bindparams(bindparam("ids", expanding=True))

_DELETE_ALL_SQL = text("DELETE FROM chunks WHERE document_id = :document_id")

_RECOUNT_SQL = text(
    "UPDATE documents SET"
    " chunk_count = (SELECT COUNT(*) FROM chunks WHERE document_id = :id AND committed = 1),"
    " token_count = COALESCE((SELECT SUM(token_count) FROM chunks"
    " WHERE document_id = :id AND committed = 1), 0),"
    " update_time = :now, update_date = :now_date"
    " WHERE id = :id"
)


def _json_list(value: Any) -> Any:
    """JSON z bazy może przyjść jako str — wtedy parsowany (wzór: documents._json_column)."""
    return json.loads(value) if isinstance(value, str) else value


def _record(row: RowMapping) -> ChunkRecord:
    """RowMapping → ChunkRecord; JSON → list, NULL positions → [], TINYINT(1) → bool (C3.1)."""
    positions = row["positions"]
    return ChunkRecord(
        id=row["id"],
        document_id=row["document_id"],
        dataset_id=row["dataset_id"],
        document_name=row["document_name"],
        ordinal=int(row["ordinal"]),
        chunk_type=row["chunk_type"],
        content=row["content"],
        keywords=_json_list(row["keywords"]),
        questions=_json_list(row["questions"]),
        tags=_json_list(row["tags"]),
        positions=[] if positions is None else [list(p) for p in _json_list(positions)],
        image_id=row["image_id"],
        available=bool(row["available"]),
        token_count=int(row["token_count"]),
        create_time=int(row["create_time"]),
        update_time=int(row["update_time"]),
    )


async def list_for_document(  # noqa: PLR0913 — kształt kontraktu C3.1
    session: AsyncSession,
    document_id: str,
    *,
    keywords: str | None,
    chunk_id: str | None,
    offset: int,
    limit: int,
    available: bool | None = None,
) -> tuple[list[ChunkRecord], int]:
    """Strona chunków committed dokumentu + total z tym samym WHERE; limit=0 → ([], total)."""
    where = _DOC_COMMITTED_WHERE
    params: dict[str, Any] = {"document_id": document_id}
    if keywords:
        where += _KEYWORDS_WHERE
        params["keywords"] = keywords
    if chunk_id is not None:
        where += _CHUNK_ID_WHERE
        params["chunk_id"] = chunk_id
    if available is not None:
        where += _AVAILABLE_WHERE
        params["available"] = int(available)
    # SQL wyłącznie ze stałych fragmentów + parametry wiązane (filtry wyżej).
    count_sql = "SELECT COUNT(*)" + _RECORD_FROM + where
    total = cast("int", (await session.execute(text(count_sql), params)).scalar_one())
    if limit == 0:
        return [], total
    # Stałe fragmenty + parametry wiązane; LIMIT/OFFSET liczbami z kontraktu API.
    page_sql = _RECORD_SELECT + _RECORD_FROM + where + _LIST_PAGE_SUFFIX
    rows = (
        (await session.execute(text(page_sql), {**params, "limit": limit, "offset": offset}))
        .mappings()
        .all()
    )
    return [_record(row) for row in rows], total


async def get_record(session: AsyncSession, chunk_id: str) -> ChunkRecord | None:
    """Chunk committed po identyfikatorze; niezacommitowany albo brak → None (C3.1)."""
    found = (await session.execute(_GET_RECORD_SQL, {"id": chunk_id})).mappings().first()
    return _record(found) if found is not None else None


async def max_ordinal(session: AsyncSession, document_id: str) -> int:
    """Najwyższy ordinal chunków dokumentu (także niezacommitowanych); brak → -1 (C3.1)."""
    result = await session.execute(_MAX_ORDINAL_SQL, {"document_id": document_id})
    return cast("int", result.scalar_one())


async def insert_manual(session: AsyncSession, row: ChunkInsert, *, now_ms: int) -> None:
    """Wstawia chunk ręczny (committed=1); pole ``row.task_id`` ignorowane — w bazie NULL (C3.1)."""
    params = _params(row, now_ms=now_ms)
    del params["task_id"]
    await session.execute(_INSERT_MANUAL_SQL, params)


async def update_content(
    session: AsyncSession, chunk_id: str, fields: Mapping[str, Any], *, now_ms: int
) -> None:
    """Aktualizuje dozwolone kolumny chunka + update_time/date; inna kolumna → ValueError (C3.1)."""
    params: dict[str, Any] = {"id": chunk_id, "now": now_ms, "now_date": from_ms(now_ms)}
    assignments = ["update_time = :now", "update_date = :now_date"]
    for key, value in fields.items():
        if key not in _CONTENT_COLUMNS:
            raise ValueError(f"column not allowed: {key}")
        if key in _JSON_CONTENT_COLUMNS:
            params[key] = json.dumps(value, ensure_ascii=False)
        elif key == "available":
            params[key] = int(value)
        else:
            params[key] = value
        # Kolumna z białej listy _CONTENT_COLUMNS — nie wartość użytkownika.
        assignments.append(f"{key} = :{key}")
    # Jw. — SET budowany wyłącznie z nazw kolumn z białej listy.
    sql = "UPDATE chunks SET " + ", ".join(assignments) + " WHERE id = :id"  # noqa: S608
    await session.execute(text(sql), params)


async def set_available(
    session: AsyncSession,
    document_id: str,
    chunk_ids: Sequence[str],
    available: bool,
    *,
    now_ms: int,
) -> int:
    """Przełącza available wybranych chunków dokumentu; [] → 0 bez SQL (C3.1)."""
    if not chunk_ids:
        return 0
    result = await session.execute(
        _SET_AVAILABLE_SQL,
        {
            "document_id": document_id,
            "ids": list(chunk_ids),
            "available": int(available),
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )
    return cast(CursorResult[Any], result).rowcount


async def delete(session: AsyncSession, document_id: str, chunk_ids: Sequence[str] | None) -> int:
    """Usuwa chunki dokumentu (None = wszystkie, [] → 0); wektory kasuje FK CASCADE (C3.1)."""
    if chunk_ids is None:
        result = await session.execute(_DELETE_ALL_SQL, {"document_id": document_id})
    else:
        if not chunk_ids:
            return 0
        result = await session.execute(
            _DELETE_BY_IDS_SQL, {"document_id": document_id, "ids": list(chunk_ids)}
        )
    return cast(CursorResult[Any], result).rowcount


async def recount_document(session: AsyncSession, document_id: str, *, now_ms: int) -> None:
    """chunk_count/token_count z chunków committed do documents; run/progress bez zmian (C3.1)."""
    await session.execute(
        _RECOUNT_SQL, {"id": document_id, "now": now_ms, "now_date": from_ms(now_ms)}
    )
