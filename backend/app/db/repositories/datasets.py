"""Repozytorium tabeli datasets (kontrakty C2.1, E1-9a C1.1) — Core ``text()`` z parametrami.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms
from app.domain.policy import VisibilityFilter


@dataclass(frozen=True)
class DatasetRow:
    """Wiersz `datasets` — pola używane przez ingestię (kontrakt C2.1)."""

    id: str
    tenant_id: str
    name: str
    language: str
    embedding_model: str
    embedding_dim: int
    chunk_method: str
    parser_config: dict[str, Any]  # JSON → dict
    document_count: int
    chunk_count: int
    token_num: int


_SELECT_SQL = text(
    "SELECT id, tenant_id, name, language, embedding_model, embedding_dim, chunk_method,"
    " parser_config, document_count, chunk_count, token_num"
    " FROM datasets WHERE id = :id"
)

# Jedno UPDATE z podzapytaniami po documents (C2.1); brak dokumentów → 0 (COALESCE).
_RECOUNT_SQL = text(
    "UPDATE datasets SET"
    " document_count = (SELECT COUNT(*) FROM documents WHERE dataset_id = :id),"
    " chunk_count = COALESCE((SELECT SUM(chunk_count) FROM documents WHERE dataset_id = :id), 0),"
    " token_num = COALESCE((SELECT SUM(token_count) FROM documents WHERE dataset_id = :id), 0),"
    " update_time = :now, update_date = :now_date"
    " WHERE id = :id"
)

# Blokada wiersza datasetu na czas transakcji; kolejność blokad: dataset przed dokumentami.
_LOCK_SQL = text("SELECT id FROM datasets WHERE id = :id FOR UPDATE")


async def lock(session: AsyncSession, dataset_id: str) -> None:
    """X-blokada wiersza datasetu przed mutacjami dokumentów/chunków.

    ``documents``/``chunks`` mają FK do ``datasets``, więc INSERT bierze S-blokadę wiersza
    datasetu, a ``recount`` chce na nim X — dwie równoległe transakcje kończyły konwersją
    blokad (``OperationalError 1213``, DEC-088 p. 3). Wzięcie X przed zapisem serializuje
    transakcje per dataset.
    """
    await session.execute(_LOCK_SQL, {"id": dataset_id})


def _row(row: RowMapping) -> DatasetRow:
    """RowMapping → DatasetRow; parser_config może przyjść jako str (JSON)."""
    parser_config = row["parser_config"]
    if isinstance(parser_config, str):
        parser_config = json.loads(parser_config)
    return DatasetRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        language=row["language"],
        embedding_model=row["embedding_model"],
        embedding_dim=int(row["embedding_dim"]),
        chunk_method=row["chunk_method"],
        parser_config=parser_config,
        document_count=int(row["document_count"]),
        chunk_count=int(row["chunk_count"]),
        token_num=int(row["token_num"]),
    )


async def get(session: AsyncSession, dataset_id: str) -> DatasetRow | None:
    """Dataset po identyfikatorze; None gdy brak."""
    found = (await session.execute(_SELECT_SQL, {"id": dataset_id})).mappings().first()
    return _row(found) if found is not None else None


async def recount(session: AsyncSession, dataset_id: str, *, now_ms: int) -> None:
    """Przelicza document_count/chunk_count/token_num z tabeli documents (kontrakt C2.1)."""
    await session.execute(
        _RECOUNT_SQL,
        {"id": dataset_id, "now": now_ms, "now_date": from_ms(now_ms)},
    )


# --- E1-9a (kontrakt C1.1): pełny wiersz + operacje API -------------------------------


@dataclass(frozen=True)
class DatasetRecord:
    """Pełny wiersz `datasets` + nickname właściciela (API, E1-9a)."""

    id: str
    tenant_id: str
    created_by: str
    name: str
    description: str | None
    avatar: str | None
    language: str
    embedding_model: str
    embedding_dim: int
    permission: Literal["me", "team"]
    chunk_method: str
    parser_config: dict[str, Any]
    similarity_threshold: float  # round(x, 6) przy odczycie (FLOAT: 0.2 → 0.200000003)
    vector_similarity_weight: float  # round(x, 6)
    pagerank: int
    document_count: int
    chunk_count: int
    token_num: int
    status: str
    create_time: int
    update_time: int
    owner_nickname: str  # users.nickname (JOIN users ON users.id = datasets.tenant_id)


# Fragmenty SQL jako str — składane w text() (WHERE zależy od filtra widoczności).
_RECORD_COLUMNS = (
    "SELECT d.id, d.tenant_id, d.created_by, d.name, d.description, d.avatar, d.language,"
    " d.embedding_model, d.embedding_dim, d.permission, d.chunk_method, d.parser_config,"
    " d.similarity_threshold, d.vector_similarity_weight, d.pagerank, d.document_count,"
    " d.chunk_count, d.token_num, d.status, d.create_time, d.update_time,"
    " u.nickname AS owner_nickname"
    " FROM datasets d JOIN users u ON u.id = d.tenant_id"
)
_VISIBILITY_WHERE = " (d.tenant_id IN :owners OR (:team AND d.permission = 'team'))"

_INSERT_RECORD_SQL = text(
    "INSERT INTO datasets (id, tenant_id, created_by, name, description, avatar, language,"
    " embedding_model, embedding_dim, permission, chunk_method, parser_config,"
    " create_time, create_date, update_time, update_date)"
    " VALUES (:id, :tenant_id, :created_by, :name, :description, :avatar, :language,"
    " :embedding_model, :embedding_dim, :permission, :chunk_method, :parser_config,"
    " :now_ms, :now_date, :now_ms, :now_date)"
)

# name_ci — kolumna generowana LOWER(name); COLLATE utf8mb4_bin = porównanie bez wielkości liter
# po znormalizowaniu parametru LOWER() po stronie Pythona.
_TAKEN_SQL = text("SELECT name_ci FROM datasets WHERE tenant_id = :tenant_id")

# size datasetu = suma rozmiarów plików dokumentów (upstream DAS:276 get_total_size_by_kb_id).
_TOTAL_SIZE_SQL = text(
    "SELECT COALESCE(SUM(size), 0) FROM documents WHERE dataset_id = :dataset_id"
)

_DOC_IDS_SQL = text(
    "SELECT id FROM documents WHERE dataset_id = :dataset_id ORDER BY create_time, id"
)

_DELETE_LINKS_SQL = text("DELETE FROM chat_datasets WHERE dataset_id = :dataset_id")
_DELETE_DATASET_SQL = text("DELETE FROM datasets WHERE id = :dataset_id")

# Biała lista kolumn update_fields (kontrakt C1.1); inna → ValueError.
_UPDATABLE_COLUMNS = frozenset(
    {
        "name",
        "description",
        "avatar",
        "language",
        "embedding_model",
        "embedding_dim",
        "permission",
        "chunk_method",
        "parser_config",
        "similarity_threshold",
        "vector_similarity_weight",
        "pagerank",
    }
)

# ORDER BY: wyłącznie te kolumny (kontrakt C1.1); inna → ValueError.
_ORDER_COLUMNS = frozenset({"create_time", "update_time"})


def _record(row: RowMapping) -> DatasetRecord:
    """RowMapping → DatasetRecord; JSON → dict, FLOAT → round(x, 6) (kontrakt C1.1)."""
    parser_config = row["parser_config"]
    if isinstance(parser_config, str):
        parser_config = json.loads(parser_config)
    return DatasetRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        created_by=row["created_by"],
        name=row["name"],
        description=row["description"],
        avatar=row["avatar"],
        language=row["language"],
        embedding_model=row["embedding_model"],
        embedding_dim=int(row["embedding_dim"]),
        permission=cast(Literal["me", "team"], row["permission"]),
        chunk_method=row["chunk_method"],
        parser_config=parser_config,
        similarity_threshold=round(float(row["similarity_threshold"]), 6),
        vector_similarity_weight=round(float(row["vector_similarity_weight"]), 6),
        pagerank=int(row["pagerank"]),
        document_count=int(row["document_count"]),
        chunk_count=int(row["chunk_count"]),
        token_num=int(row["token_num"]),
        status=row["status"],
        create_time=int(row["create_time"]),
        update_time=int(row["update_time"]),
        owner_nickname=row["owner_nickname"],
    )


async def insert(  # noqa: PLR0913 — kształt kontraktu C1.1
    session: AsyncSession,
    *,
    id: str,  # nazwa kolumny z kontraktu C1.1
    tenant_id: str,
    created_by: str,
    name: str,
    description: str | None,
    avatar: str | None,
    language: str,
    embedding_model: str,
    embedding_dim: int,
    permission: str,
    chunk_method: str,
    parser_config: dict[str, Any],
    now_ms: int,
) -> None:
    """Wstawia dataset; create_date/update_date z now_ms, parser_config jako JSON (C1.1)."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        _INSERT_RECORD_SQL,
        {
            "id": id,
            "tenant_id": tenant_id,
            "created_by": created_by,
            "name": name,
            "description": description,
            "avatar": avatar,
            "language": language,  # zawsze jawnie — DDL DEFAULT 'Polish' jest niezgodny ze złotem
            "embedding_model": embedding_model,
            "embedding_dim": embedding_dim,
            "permission": permission,
            "chunk_method": chunk_method,
            "parser_config": json.dumps(parser_config, ensure_ascii=False),
            "now_ms": now_ms,
            "now_date": date,
        },
    )


async def get_record(session: AsyncSession, dataset_id: str) -> DatasetRecord | None:
    """Pełny wiersz datasetu + nickname właściciela; None gdy brak (kontrakt C1.1)."""
    found = (
        (await session.execute(text(_RECORD_COLUMNS + " WHERE d.id = :id"), {"id": dataset_id}))
        .mappings()
        .first()
    )
    return _record(found) if found is not None else None


def _visibility_clause(visibility: VisibilityFilter) -> tuple[str, dict[str, Any]]:
    """Fragment WHERE z filtra widoczności (kontrakt C1.1); all → brak warunku."""
    if visibility.all:
        return "", {}
    return _VISIBILITY_WHERE, {
        "owners": sorted(visibility.owner_ids),
        "team": visibility.include_team,
    }


async def list_records(  # noqa: PLR0913 — kształt kontraktu C1.1
    session: AsyncSession,
    *,
    visibility: VisibilityFilter,
    offset: int,
    limit: int,
    orderby: str,
    desc: bool,
    dataset_id: str | None = None,
    name: str | None = None,
    keywords: str | None = None,
) -> tuple[list[DatasetRecord], int]:
    """Strona listy datasetów + total; pusta widoczność → ([], 0) bez SQL (kontrakt C1.1).

    Filtry: dataset_id → id; name → name_ci = LOWER(:name); keywords → LIKE %LOWER(:kw)%.
    orderby ∈ {create_time, update_time} (biała lista), kierunek wg ``desc``, remis po id.
    limit == 0 → pusta lista, total liczony (używa tego `exists`).
    """
    if orderby not in _ORDER_COLUMNS:
        raise ValueError(f"invalid orderby: {orderby!r}")
    if not visibility.all and not visibility.owner_ids and not visibility.include_team:
        return [], 0
    conditions: list[str] = []
    params: dict[str, Any] = {}
    visibility_clause, params = _visibility_clause(visibility)
    if visibility_clause:
        conditions.append(visibility_clause)
    if dataset_id is not None:
        conditions.append("d.id = :dataset_id")
        params["dataset_id"] = dataset_id
    if name is not None:
        conditions.append("d.name_ci = :name")
        params["name"] = name.lower()
    if keywords:
        conditions.append("d.name_ci LIKE CONCAT('%', :keywords, '%')")
        params["keywords"] = keywords.lower()
    condition = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    direction = "DESC" if desc else "ASC"
    order = " ORDER BY d." + orderby + " " + direction + ", d.id"
    rows: list[DatasetRecord] = []
    count_stmt = text("SELECT COUNT(*) FROM datasets d" + condition)  # noqa: S608 — białe listy
    if limit > 0:
        stmt = text(_RECORD_COLUMNS + condition + order + " LIMIT :limit OFFSET :offset")
        if not visibility.all:
            # expanding IN — także w COUNT (ten sam warunek WHERE).
            stmt = stmt.bindparams(bindparam("owners", expanding=True))
            count_stmt = count_stmt.bindparams(bindparam("owners", expanding=True))
        found = (
            (await session.execute(stmt, {**params, "limit": limit, "offset": offset}))
            .mappings()
            .all()
        )
        rows = [_record(row) for row in found]
    count = cast(int, (await session.execute(count_stmt, params)).scalar_one())
    return rows, count


async def exists(
    session: AsyncSession,
    *,
    visibility: VisibilityFilter,
    dataset_id: str | None = None,
    name: str | None = None,
) -> bool:
    """Czy w zasięgu widoczności istnieje dataset o tym ``dataset_id``/``name`` (C1.1).

    Liczone tym samym predykatem co lista (``limit=1`` — wiersz jest odrzucany, liczy się
    ``total``; ``limit=0`` nie wiąże `owners` w COUNT przy filtrze widoczności), bo istnienie
    filtra sprawdzamy osobno od wyniku listowania (upstream DAS:449-457).
    """
    _, total = await list_records(
        session,
        visibility=visibility,
        offset=0,
        limit=1,
        orderby="create_time",
        desc=True,
        dataset_id=dataset_id,
        name=name,
    )
    return total > 0


async def names_taken(session: AsyncSession, tenant_id: str) -> set[str]:
    """Nazwy wszystkich datasetów tenanta, małymi literami (kontrakt C1.1)."""
    rows = (await session.execute(_TAKEN_SQL, {"tenant_id": tenant_id})).scalars().all()
    return {str(row) for row in rows}


async def document_total_size(session: AsyncSession, dataset_id: str) -> int:
    """Suma rozmiarów dokumentów datasetu; brak dokumentów → 0 (upstream DAS:276)."""
    result = await session.execute(_TOTAL_SIZE_SQL, {"dataset_id": dataset_id})
    return int(cast(int, result.scalar_one()))


async def update_fields(
    session: AsyncSession, dataset_id: str, fields: Mapping[str, Any], *, now_ms: int
) -> None:
    """Aktualizuje podane kolumny + update_time/date; kolumna spoza białej listy → ValueError."""
    unknown = sorted(set(fields) - _UPDATABLE_COLUMNS)
    if unknown:
        raise ValueError(f"unsupported dataset columns: {unknown}")
    assignments = ", ".join(column + " = :" + column for column in fields)
    params: dict[str, Any] = dict(fields)
    if "parser_config" in fields:
        params["parser_config"] = json.dumps(fields["parser_config"], ensure_ascii=False)
    params.update({"dataset_id": dataset_id, "now_ms": now_ms, "now_date": from_ms(now_ms)})
    # Nazwy kolumn z białej listy _UPDATABLE_COLUMNS (walidacja wyżej); wartości — parametrami.
    await session.execute(
        text(
            "UPDATE datasets SET " + assignments + ", update_time = :now_ms,"  # noqa: S608
            " update_date = :now_date WHERE id = :dataset_id"
        ),
        params,
    )


async def delete(session: AsyncSession, dataset_id: str) -> int:
    """Usuwa powiązania chat_datasets (FK RESTRICT), potem dataset; zwraca rowcount (C1.1)."""
    await session.execute(_DELETE_LINKS_SQL, {"dataset_id": dataset_id})
    result = await session.execute(_DELETE_DATASET_SQL, {"dataset_id": dataset_id})
    return cast(CursorResult[Any], result).rowcount


async def list_document_ids(session: AsyncSession, dataset_id: str) -> list[str]:
    """Identyfikatory dokumentów datasetu (kontrakt C1.1)."""
    rows = (await session.execute(_DOC_IDS_SQL, {"dataset_id": dataset_id})).scalars().all()
    return [str(row) for row in rows]
