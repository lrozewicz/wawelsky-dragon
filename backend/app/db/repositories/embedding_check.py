"""Odczyt danych do ``POST /datasets/{id}/embedding/check`` (zadanie DS2) — Core ``text()``.

Upstream bierze losowe chunki z doc-store'u (``sample_random_chunks_with_vectors``) razem
z zapisanym wektorem. WD trzyma wektory w tabeli ``chunk_vec_d<dim>`` (K5 §6.1), a treść
w ``chunks`` — stąd dwa zapytania: próbka chunków dostępnych w datasecie i odczyt wektora
(``VEC_ToText``). Bez ``commit``/``rollback`` — transakcję otwiera wywołująca.
"""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.chunk_vectors import table_name

# Próbka jak upstream (available_int = 1); kolejność deterministyczna (ordinal, id) —
# upstream losuje (random.sample), co uniemożliwiałoby powtarzalny golden/replay.
_SAMPLE_SQL = text(
    "SELECT c.id, c.document_id, d.name AS document_name, c.content, c.questions,"
    " c.embed_source, d.parser_config FROM chunks c JOIN documents d ON d.id = c.document_id"
    " WHERE c.dataset_id = :dataset_id AND c.committed = 1 AND c.available = 1"
    " ORDER BY c.ordinal, c.id LIMIT :limit"
)


@dataclass(frozen=True)
class ChunkSample:
    """Chunk wybrany do sprawdzenia embeddingu: tożsamość, dokument i tekst pod embedding."""

    id: str
    document_id: str
    document_name: str
    content: str
    questions: list[str]
    embed_source: str
    parser_config: dict[str, Any]


def _sample(row: RowMapping) -> ChunkSample:
    """RowMapping → ChunkSample; ``questions`` i ``parser_config`` z JSON-ów (str) na obiekty."""
    questions = row["questions"]
    parser_config = row["parser_config"]
    return ChunkSample(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        document_name=str(row["document_name"]),
        content=str(row["content"]),
        questions=list(
            map(str, json.loads(questions) if isinstance(questions, str) else questions)
        ),
        embed_source=str(row["embed_source"]),
        parser_config=(
            json.loads(parser_config) if isinstance(parser_config, str) else parser_config
        ),
    )


async def sample_chunks(session: AsyncSession, dataset_id: str, limit: int) -> list[ChunkSample]:
    """Do ``limit`` chunków datasetu z zapisanym wektorem (committed i available)."""
    rows = (
        await session.execute(_SAMPLE_SQL, {"dataset_id": dataset_id, "limit": limit})
    ).mappings()
    return [_sample(row) for row in rows]


async def fetch_vector(session: AsyncSession, dim: int, chunk_id: str) -> list[float] | None:
    """Wektor zapisany dla chunka w ``chunk_vec_d<dim>``; brak wiersza → None.

    ``VEC_ToText`` zwraca tekst JSON listy liczb (C2.4 używa ``VEC_FromText`` przy zapisie).
    """
    # Nazwa tabeli z walidowanego table_name(dim) — identyfikator DDL, nie wartość.
    sql = text(
        f"SELECT VEC_ToText(embedding) FROM {table_name(dim)} WHERE chunk_id = :chunk_id"  # noqa: S608
    )
    raw = (await session.execute(sql, {"chunk_id": chunk_id})).scalar_one_or_none()
    if raw is None:
        return None
    return [float(value) for value in json.loads(raw)]
