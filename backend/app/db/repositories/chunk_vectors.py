"""Repozytorium tabel wektorów ``chunk_vec_d<dim>`` (kontrakt C2.4) — Core ``text()``.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca. UWAGA: ``ensure_table``
wykonuje DDL, a DDL w MariaDB robi niejawny COMMIT — wołać w OSOBNEJ transakcji (C2.4).
Nazwa tabeli pochodzi wyłącznie z ``table_name(dim)`` — identyfikator DDL z walidowanego
``int`` (nie da się jej wiązać parametrem), stąd f-string i ``noqa: S608``.
"""

import json
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VEC_BATCH = 200  # rozmiar partii executemany przy wstawianiu wektorów (C2.4)


def table_name(dim: int) -> str:
    """Nazwa tabeli wektorów dla wymiaru; walidacja: ``int`` (nie ``bool``) > 0."""
    if isinstance(dim, bool) or not isinstance(dim, int) or dim <= 0:
        raise ValueError(f"invalid embedding dimension: {dim!r}")
    return f"chunk_vec_d{dim}"


def _create_table_sql(dim: int) -> str:
    """DDL tabeli wektorów — kopia chunk_vec_d1536 z alembic/versions/0001_initial.py,
    z zamianą 1536 → dim (nazwa tabeli, VECTOR(dim), fk_vec{dim}_chunk); IF NOT EXISTS."""
    name = table_name(dim)
    # Identyfikatory (nazwa tabeli, ograniczenia) z walidowanego int — bez wartości użytkownika.
    return (
        f"CREATE TABLE IF NOT EXISTS {name} (\n"
        "  chunk_id CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n"
        "  dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n"
        f"  embedding VECTOR({dim}) NOT NULL,\n"
        "  PRIMARY KEY (chunk_id),\n"
        "  KEY ix_dataset (dataset_id),\n"
        f"  CONSTRAINT fk_vec{dim}_chunk FOREIGN KEY (chunk_id) REFERENCES chunks (id)"
        " ON DELETE CASCADE\n"
        ") ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4"
        " COLLATE=utf8mb4_uca1400_ai_ci"
    )


async def ensure_table(session: AsyncSession, dim: int) -> None:
    """Tworzy tabelę wektorów, jeśli jej nie ma; DDL → niejawny COMMIT (uwaga wyżej)."""
    await session.execute(text(_create_table_sql(dim)))


def _insert_sql(dim: int) -> str:
    """INSERT wektora: VEC_FromText czyta tekst JSON listy liczb (C2.4)."""
    # Nazwa tabeli z walidowanego table_name(dim) — identyfikator DDL, nie wartość.
    sql = (
        f"INSERT INTO {table_name(dim)} (chunk_id, dataset_id, embedding)"  # noqa: S608
        " VALUES (:chunk_id, :dataset_id, VEC_FromText(:v))"
    )
    return sql


def _count_sql(dim: int) -> str:
    """Licznik wektorów dokumentu — JOIN chunks po chunk_id (C2.4)."""
    # Nazwa tabeli z walidowanego table_name(dim) — identyfikator DDL, nie wartość.
    sql = (
        f"SELECT COUNT(*) FROM {table_name(dim)} v"  # noqa: S608
        " JOIN chunks c ON c.id = v.chunk_id WHERE c.document_id = :document_id"
    )
    return sql


async def insert_many(
    session: AsyncSession, dim: int, rows: Sequence[tuple[str, str, Sequence[float]]]
) -> None:
    """Wstawia wektory (chunk_id, dataset_id, wektor) partiami po VEC_BATCH (C2.4)."""
    stmt = text(_insert_sql(dim))
    batch: list[dict[str, Any]] = []
    for chunk_id, dataset_id, vector in rows:
        values = list(vector)
        if len(values) != dim:
            raise ValueError(
                f"embedding dimension {len(values)} does not match table dimension {dim}"
            )
        batch.append(
            {
                "chunk_id": chunk_id,
                "dataset_id": dataset_id,
                "v": json.dumps(values),
            }
        )
        if len(batch) == VEC_BATCH:
            await session.execute(stmt, batch)
            batch = []
    if batch:
        await session.execute(stmt, batch)


async def count_by_document(session: AsyncSession, dim: int, document_id: str) -> int:
    """Liczba wektorów dokumentu w tabeli o danym wymiarze (C2.4)."""
    result = await session.execute(text(_count_sql(dim)), {"document_id": document_id})
    return cast("int", result.scalar_one())


def _upsert_sql(dim: int) -> str:
    """INSERT wektora z nadpisaniem przy powtórce chunk_id — ON DUPLICATE KEY UPDATE (C3.1)."""
    # Nazwa tabeli z walidowanego table_name(dim) — identyfikator DDL, nie wartość.
    sql = (
        f"INSERT INTO {table_name(dim)} (chunk_id, dataset_id, embedding)"  # noqa: S608
        " VALUES (:chunk_id, :dataset_id, VEC_FromText(:v))"
        " ON DUPLICATE KEY UPDATE embedding = VALUES(embedding)"
    )
    return sql


async def upsert(
    session: AsyncSession, dim: int, chunk_id: str, dataset_id: str, vector: Sequence[float]
) -> None:
    """Wstawia wektor chunka albo nadpisuje istniejący wiersz (C3.1)."""
    await session.execute(
        text(_upsert_sql(dim)),
        {"chunk_id": chunk_id, "dataset_id": dataset_id, "v": json.dumps(list(vector))},
    )
