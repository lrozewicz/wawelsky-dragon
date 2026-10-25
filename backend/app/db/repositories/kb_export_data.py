"""Odczyt danych datasetu do eksportu partiami (CONTRACT E7-1a §3) — Core ``text()``.

Budowa paczki ``.wdkb.zip`` (``app.services.kb_export_build``) czyta dataset strumieniowo:
dokumenty i chunki partiami (keyset), wektory dla id-ów partii chunków. Ten moduł jest jedynym
miejscem tych odczytów — SQL przez ``text()``, bez ``commit``/``rollback`` (transakcję otwiera
wołająca). Liczniki (``count_documents``/``count_chunks``) liczą tylko chunki ``committed=1``,
bo tylko one wchodzą do paczki (K19 §2).
"""

from __future__ import annotations

import struct
from collections.abc import AsyncIterator, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.chunk_vectors import table_name

# Rozmiary partii odczytu (CONTRACT §3: chunki ≤ 1000). Wstrzykiwalne stałą modułu — test
# postępu i Stopu pracuje na małej partii bez seedowania >1000 chunków.
DOCUMENTS_BATCH = 1000
CHUNKS_BATCH = 1000

__all__ = [
    "CHUNKS_BATCH",
    "DOCUMENTS_BATCH",
    "count_chunks",
    "count_documents",
    "dataset_manifest_row",
    "fetch_vectors",
    "iter_chunks",
    "iter_documents",
]

# Wiersz datasetu pod manifest (K19 §2 dataset): wszystkie pola ManifestDataset.
_DATASET_SQL = text(
    "SELECT name, description, language, embedding_model, embedding_dim, chunk_method,"
    " parser_config, similarity_threshold, vector_similarity_weight, pagerank"
    " FROM datasets WHERE id = :dataset_id"
)

_COUNT_DOCUMENTS_SQL = text("SELECT COUNT(*) FROM documents WHERE dataset_id = :dataset_id")

_COUNT_CHUNKS_SQL = text(
    "SELECT COUNT(*) FROM chunks WHERE dataset_id = :dataset_id AND committed = 1"
)

# Keyset po ``id`` (CHAR(32) ascii_bin): deterministyczna kolejność ``d1..``.
_DOCUMENTS_SQL = text(
    "SELECT id, name, suffix, type, size, location, chunk_method, parser_config,"
    " meta_fields, run, progress_msg, token_count, chunk_count"
    " FROM documents WHERE dataset_id = :dataset_id AND id > :after"
    " ORDER BY id LIMIT :limit"
)

# Keyset po ``(document_id, ordinal)`` — kolejność ``chunks.jsonl`` = kolejność wektorów.
_CHUNKS_SQL = text(
    "SELECT id, document_id, ordinal, chunk_type, content, content_llm, keywords, questions,"
    " tags, positions, page_from, page_to, image_id, parent_id, available, embed_source,"
    " token_count FROM chunks"
    " WHERE dataset_id = :dataset_id AND committed = 1"
    " AND (document_id > :after_doc OR (document_id = :after_doc AND ordinal > :after_ord))"
    " ORDER BY document_id, ordinal LIMIT :limit"
)


async def dataset_manifest_row(session: AsyncSession, dataset_id: str) -> RowMapping | None:
    """Wiersz datasetu pod manifest albo ``None``, gdy dataset zniknął w międzyczasie."""
    return (await session.execute(_DATASET_SQL, {"dataset_id": dataset_id})).mappings().first()


async def count_documents(session: AsyncSession, dataset_id: str) -> int:
    """Liczba dokumentów datasetu (licznik postępu etapu ``files``)."""
    return int(
        (await session.execute(_COUNT_DOCUMENTS_SQL, {"dataset_id": dataset_id})).scalar_one()
    )


async def count_chunks(session: AsyncSession, dataset_id: str) -> int:
    """Liczba chunków ``committed=1`` datasetu (licznik etapów ``chunks``/``vectors``)."""
    return int((await session.execute(_COUNT_CHUNKS_SQL, {"dataset_id": dataset_id})).scalar_one())


async def iter_documents(
    session: AsyncSession, dataset_id: str, *, batch: int = DOCUMENTS_BATCH
) -> AsyncIterator[list[RowMapping]]:
    """Strumieniuje dokumenty datasetu partiami po ``batch``, w kolejności ``id``."""
    after = ""
    while True:
        rows = (
            (
                await session.execute(
                    _DOCUMENTS_SQL, {"dataset_id": dataset_id, "after": after, "limit": batch}
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return
        yield list(rows)
        if len(rows) < batch:
            return
        after = str(rows[-1]["id"])


async def iter_chunks(
    session: AsyncSession, dataset_id: str, *, batch: int = CHUNKS_BATCH
) -> AsyncIterator[list[RowMapping]]:
    """Strumieniuje chunki ``committed=1`` partiami po ``batch`` po ``(document_id, ordinal)``."""
    after_doc, after_ord = "", -1
    while True:
        rows = (
            (
                await session.execute(
                    _CHUNKS_SQL,
                    {
                        "dataset_id": dataset_id,
                        "after_doc": after_doc,
                        "after_ord": after_ord,
                        "limit": batch,
                    },
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return
        yield list(rows)
        if len(rows) < batch:
            return
        last = rows[-1]
        after_doc, after_ord = str(last["document_id"]), int(last["ordinal"])


async def fetch_vectors(
    session: AsyncSession, dim: int, chunk_ids: Sequence[str]
) -> dict[str, list[float]]:
    """Wektory chunków partii z ``chunk_vec_d<dim>`` — mapa ``chunk_id → wektor`` (bajty wektora).

    ``HEX(embedding)`` daje surowe bajty kolumny ``VECTOR`` (float32 little-endian, po 4 na
    komponent) — odwracalnie i bez straty. ``VEC_ToText`` nadaje się wyłącznie do podglądu:
    wypisuje float32 z **6 cyframi znaczącymi**, więc paczka niosła wektory różne od źródłowych
    (do ~5e-6 rel. na komponent), a po imporcie wyszukiwanie dostawało inne dystanse (DEC-350).

    Nazwa tabeli tylko z ``table_name(dim)`` (identyfikator DDL z walidowanego ``int``, C2.4).
    """
    if not chunk_ids:
        return {}
    sql = text(
        f"SELECT chunk_id, HEX(embedding) AS vec FROM {table_name(dim)}"  # noqa: S608
        " WHERE chunk_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    rows = (await session.execute(sql, {"ids": list(chunk_ids)})).mappings().all()
    return {
        str(row["chunk_id"]): list(struct.unpack(f"<{dim}f", bytes.fromhex(str(row["vec"]))))
        for row in rows
    }
