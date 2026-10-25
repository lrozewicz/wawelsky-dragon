"""Repozytorium retrievalu (kontrakt M7) — Core ``text()`` z parametrami wiązanymi.

Wyjątek od zasady „plik = tabela” nadany przez K5 §8 p. 8: zapytania łączą chunks,
documents i tabele wektorów. Bez ``commit``/``rollback`` — transakcję otwiera
wywołująca (``app.db.uow.transaction``). Nazwa tabeli wektorów pochodzi WYŁĄCZNIE
z ``chunk_vectors.table_name(dim)``. Warianty łańcuchów SQL (z/bez ``document_id IN``)
różnią się tylko stałymi fragmentami — żadna wartość nie trafia do tekstu zapytania.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import TextClause, bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.chunk_vectors import table_name

# Operatory boolean mode FULLTEXT — usuwane z łańcuchów zapytań przed wiązaniem (M7).
_FT_OPERATORS = re.compile(r'[+\-<>()~*"@]')

_TABLE_EXISTS_SQL = text(
    "SELECT COUNT(*) FROM information_schema.tables"
    " WHERE table_schema = DATABASE() AND table_name = :t"
)

# Zmienna użytkownika @qv ustawiana w TEJ SAMEJ sesji, co późniejszy SELECT (M7).
_SET_QV_SQL = text("SET @qv = VEC_FromText(:qv)")

_GET_DATASETS_SQL = text(
    "SELECT id, tenant_id, permission, embedding_model, embedding_dim"
    " FROM datasets WHERE id IN :ids"
).bindparams(bindparam("ids", expanding=True))

# Tylko włączone dokumenty — metadane do filtra metadata_condition (R0 p. 5).
_DOCUMENT_METAS_SQL = text(
    "SELECT id, meta_fields FROM documents WHERE dataset_id IN :ds AND enabled = 1"
).bindparams(bindparam("ds", expanding=True))

_LOAD_CHUNKS_SQL = text(
    "SELECT c.id, c.document_id, c.dataset_id, c.ordinal, d.name AS document_name,"
    " d.meta_fields,"
    " c.content, c.content_llm, c.content_stem, c.title_ft, c.important_ft, c.question_ft,"
    " c.keywords, c.questions, c.positions, c.chunk_type"
    " FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id IN :ids"
).bindparams(bindparam("ids", expanding=True))


@dataclass(frozen=True)
class DatasetInfo:
    """Dane datasetu potrzebne usłudze retrievalu (kontrakt M7)."""

    id: str
    tenant_id: str
    permission: str  # 'me' | 'team'
    embedding_model: str
    embedding_dim: int


@dataclass(frozen=True)
class Scope:
    """Zakres zapytania: datasety i opcjonalny filtr po dokumentach (kontrakt M7)."""

    dataset_ids: tuple[str, ...]
    document_ids: tuple[str, ...] | None = None  # None = bez filtra; () → [] bez SQL


@dataclass(frozen=True)
class ChunkRow:
    """Pełny wiersz chunku z danymi dokumentu (kontrakt M7)."""

    id: str
    document_id: str
    dataset_id: str
    ordinal: int  # chunks.ordinal — pozycja chunku w dokumencie (klucz wtórny remisów, C3)
    document_name: str
    document_meta: dict[str, Any]  # documents.meta_fields (JSON → dict)
    content: str
    content_llm: str | None
    content_stem: str
    title_ft: str
    important_ft: str
    question_ft: str
    keywords: list[str]  # JSON → list
    questions: list[str]  # JSON → list
    positions: list[list[int]]  # JSON; NULL → []
    chunk_type: str


def _candidate_filter(ds_column: str, *, with_docs: bool) -> str:
    """Wspólny filtr kandydatów (M7); wariant z document_id IN tylko gdy scope filtruje."""
    sql = (
        " JOIN documents d ON d.id = c.document_id"
        f" WHERE {ds_column} IN :ds AND c.available = 1 AND c.committed = 1 AND d.enabled = 1"
    )
    return sql + (" AND c.document_id IN :docs" if with_docs else "")


def _vector_sql(dim: int, *, with_docs: bool) -> TextClause:
    """SELECT kandydatów wektorowych z dystansem cosinusowym do @qv, ranked RANK() (M7).

    Podzapytanie ``r`` liczy dystans wyłącznie dla wierszy przechodzących filtry (dataset,
    flagi chunku, włączony dokument), więc odrzucone wiersze nie zajmują miejsc w rankingu.
    Podzapytanie ``k`` nadaje ``RANK() OVER (ORDER BY r.dist)`` — wszystkie wiersze o remisowym
    dystansie na granicy progu dostają ten sam numer, więc zbiór ``rk <= :limit`` obejmuje całą
    grupę remisową. Zapytanie zewnętrzne sortuje ten zbiór pełnym porządkiem
    ``(dist, documents.name, chunks.ordinal, chunk_id)`` i tnie do ``:limit``.
    """
    # Nazwa tabeli z walidowanego table_name(dim) — identyfikator DDL, nie wartość (C2.4).
    stmt = text(
        "SELECT k.chunk_id, k.dist FROM ("  # noqa: S608
        " SELECT r.chunk_id AS chunk_id, r.dist AS dist,"
        " RANK() OVER (ORDER BY r.dist) AS rk FROM ("
        " SELECT v.chunk_id AS chunk_id,"
        " VEC_DISTANCE_COSINE(v.embedding, @qv) + 0.0 AS dist"
        f" FROM {table_name(dim)} v JOIN chunks c ON c.id = v.chunk_id"
        " WHERE v.dataset_id IN :ds AND c.available = 1 AND c.committed = 1"
        " AND c.document_id IN (SELECT id FROM documents WHERE enabled = 1)"
        + (" AND c.document_id IN :docs" if with_docs else "")
        + " ) r ) k JOIN chunks c ON c.id = k.chunk_id"
        " JOIN documents d ON d.id = c.document_id"
        " WHERE k.rk <= :limit"
        " ORDER BY k.dist, d.name, c.ordinal, k.chunk_id LIMIT :limit"
    ).bindparams(bindparam("ds", expanding=True))
    return stmt.bindparams(bindparam("docs", expanding=True)) if with_docs else stmt


def _vector_scores_sql(dim: int) -> str:
    """SELECT podobieństw po chunk_id — bez filtrów kandydatów (M7)."""
    # Nazwa tabeli z walidowanego table_name(dim) — identyfikator DDL, nie wartość (C2.4).
    return (
        f"SELECT v.chunk_id, VEC_DISTANCE_COSINE(v.embedding, @qv) AS dist"  # noqa: S608
        f" FROM {table_name(dim)} v WHERE v.chunk_id IN :ids"
    )


def _fulltext_sql(*, with_docs: bool) -> TextClause:
    """SELECT kandydatów FULLTEXT; ranking: treść, stem, tytuł (x10), słowa (x30), pytania (x20)."""
    stmt = text(
        "SELECT c.id,"  # noqa: S608 — stałe fragmenty SQL, wartości tylko przez bindparamy
        " MATCH(c.content_ft) AGAINST(:q_raw IN BOOLEAN MODE) AS s_content,"
        " MATCH(c.content_stem) AGAINST(:q_stem IN BOOLEAN MODE) AS s_stem,"
        " MATCH(c.title_ft) AGAINST(:q_raw IN BOOLEAN MODE) AS s_title,"
        " MATCH(c.important_ft) AGAINST(:q_raw IN BOOLEAN MODE) AS s_kwd,"
        " MATCH(c.question_ft) AGAINST(:q_raw IN BOOLEAN MODE) AS s_q"
        " FROM chunks c"
        + _candidate_filter("c.dataset_id", with_docs=with_docs)
        + " AND (MATCH(c.content_ft) AGAINST(:q_raw IN BOOLEAN MODE)"
        " OR MATCH(c.content_stem) AGAINST(:q_stem IN BOOLEAN MODE)"
        " OR MATCH(c.important_ft) AGAINST(:q_raw IN BOOLEAN MODE)"
        " OR MATCH(c.question_ft) AGAINST(:q_raw IN BOOLEAN MODE))"
        " ORDER BY (s_content + s_stem + 10 * s_title + 30 * s_kwd + 20 * s_q) DESC,"
        " d.name, c.ordinal, c.id"
        " LIMIT :limit"
    ).bindparams(bindparam("ds", expanding=True))
    return stmt.bindparams(bindparam("docs", expanding=True)) if with_docs else stmt


def _json(value: Any) -> Any:
    """JSON z bazy może przyjść jako str — wtedy parsowany (jak w documents)."""
    return json.loads(value) if isinstance(value, str) else value


def _chunk_row(row: RowMapping) -> ChunkRow:
    """RowMapping → ChunkRow; JSON-y jako str → listy, positions NULL → []."""
    return ChunkRow(
        id=row["id"],
        document_id=row["document_id"],
        dataset_id=row["dataset_id"],
        ordinal=int(row["ordinal"]),
        document_name=row["document_name"],
        document_meta=_json(row["meta_fields"]),
        content=row["content"],
        content_llm=row["content_llm"],
        content_stem=row["content_stem"],
        title_ft=row["title_ft"],
        important_ft=row["important_ft"],
        question_ft=row["question_ft"],
        keywords=_json(row["keywords"]),
        questions=_json(row["questions"]),
        positions=_json(row["positions"]) if row["positions"] is not None else [],
        chunk_type=row["chunk_type"],
    )


def _scope_params(scope: Scope) -> dict[str, Any]:
    """Parametry wiązane zakresu: ds zawsze, docs tylko gdy scope filtruje dokumenty."""
    params: dict[str, Any] = {"ds": list(scope.dataset_ids)}
    if scope.document_ids is not None:
        params["docs"] = list(scope.document_ids)
    return params


async def get_datasets(session: AsyncSession, dataset_ids: Sequence[str]) -> list[DatasetInfo]:
    """Dane datasetów po identyfikatorach; brakujące id po prostu pominięte (M7)."""
    if not dataset_ids:
        return []
    rows = (await session.execute(_GET_DATASETS_SQL, {"ids": list(dataset_ids)})).mappings().all()
    return [
        DatasetInfo(
            id=row["id"],
            tenant_id=row["tenant_id"],
            permission=row["permission"],
            embedding_model=row["embedding_model"],
            embedding_dim=int(row["embedding_dim"]),
        )
        for row in rows
    ]


async def document_metas(
    session: AsyncSession, dataset_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """meta_fields włączonych dokumentów datasetów (id → dict); [] → {} bez SQL (M7, R0 p. 5)."""
    if not dataset_ids:
        return {}
    rows = (await session.execute(_DOCUMENT_METAS_SQL, {"ds": list(dataset_ids)})).mappings().all()
    return {row["id"]: _json(row["meta_fields"]) for row in rows}


async def vector_candidates(
    session: AsyncSession,
    dim: int,
    query_vector: Sequence[float],
    scope: Scope,
    limit: int,
) -> list[tuple[str, float]]:
    """Kandydaci wektorowi (chunk_id, 1 - dystans cosinusowy), rosnąco po dystansie (M7).

    `SET @qv` i SELECT w tej samej sesji; brak tabeli wektorów → [].
    """
    if scope.document_ids == ():
        return []
    found = (await session.execute(_TABLE_EXISTS_SQL, {"t": table_name(dim)})).scalar_one()
    if not found:
        return []
    await session.execute(_SET_QV_SQL, {"qv": json.dumps([float(x) for x in query_vector])})
    sql = _vector_sql(dim, with_docs=scope.document_ids is not None)
    rows = (await session.execute(sql, _scope_params(scope) | {"limit": limit})).all()
    return [(row[0], 1.0 - float(row[1])) for row in rows]


async def vector_scores(
    session: AsyncSession,
    dim: int,
    query_vector: Sequence[float],
    chunk_ids: Sequence[str],
) -> dict[str, float]:
    """Podobieństwa wektorowe dla podanych chunków; [] → {} i brak tabeli → {} (M7)."""
    if not chunk_ids:
        return {}
    found = (await session.execute(_TABLE_EXISTS_SQL, {"t": table_name(dim)})).scalar_one()
    if not found:
        return {}
    await session.execute(_SET_QV_SQL, {"qv": json.dumps([float(x) for x in query_vector])})
    sql = text(_vector_scores_sql(dim)).bindparams(bindparam("ids", expanding=True))
    rows = (await session.execute(sql, {"ids": list(chunk_ids)})).all()
    return {row[0]: 1.0 - float(row[1]) for row in rows}


async def fulltext_candidates(
    session: AsyncSession, q_raw: str, q_stem: str, scope: Scope, limit: int
) -> list[str]:
    """Kandydaci FULLTEXT po rankingu wag M7; oba łańcuchy puste po czyszczeniu → [] (M7)."""
    if scope.document_ids == ():
        return []
    raw = _FT_OPERATORS.sub(" ", q_raw).strip()
    stem = _FT_OPERATORS.sub(" ", q_stem).strip()
    if not raw and not stem:
        return []
    sql = _fulltext_sql(with_docs=scope.document_ids is not None)
    params = _scope_params(scope) | {"q_raw": raw, "q_stem": stem, "limit": limit}
    rows = (await session.execute(sql, params)).all()
    return [row[0] for row in rows]


async def load_chunks(session: AsyncSession, chunk_ids: Sequence[str]) -> list[ChunkRow]:
    """Pełne wiersze chunków w kolejności podanych id; [] → [] bez SQL (M7)."""
    if not chunk_ids:
        return []
    rows = (await session.execute(_LOAD_CHUNKS_SQL, {"ids": list(chunk_ids)})).mappings().all()
    by_id = {row["id"]: _chunk_row(row) for row in rows}
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]
