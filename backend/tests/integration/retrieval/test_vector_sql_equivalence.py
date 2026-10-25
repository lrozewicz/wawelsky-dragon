"""Test równoważności nowego ``_vector_sql`` (RANK) ze starym SQL (brief T1, kontrakt C1/C2).

Referencja to DOSŁOWNA kopia starego ``_vector_sql`` (porządek całkowity + ``LIMIT``).
Nowy SQL rankuje ``RANK() OVER (ORDER BY dist)`` w podzapytaniu i tnie po ``rk <= :limit``,
a zapytanie zewnętrzne sortuje tym samym porządkiem całkowitym. Test sprawdza, że przy
remisach na granicy progu i przy odpadaniu najbliższych wierszy przez filtry oba zapytania
zwracają dokładnie te same wiersze w tej samej kolejności.
"""

import json
import math
from collections import Counter

import pytest
from sqlalchemy import TextClause, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import retrieval as retrieval_repo
from app.db.repositories.chunk_vectors import table_name
from app.db.uow import transaction
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import insert_chunk, insert_document

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

_LIMITS = (1, 3, 7, 10, 100)
_TIE_LIMIT = 7  # punkt, w którym grupa 5 remisów jest cięta (3 ścisłe bliższe + 4 z 5)
_TIE_IN_RESULT = 4  # liczba remisowych wierszy w wyniku przy limit=7


def _reference_vector_sql(dim: int, *, with_docs: bool) -> TextClause:
    """DOSŁOWNA kopia starego ``_vector_sql`` sprzed zmiany na RANK — referencja C2."""
    stmt = text(
        f"SELECT v.chunk_id, VEC_DISTANCE_COSINE(v.embedding, @qv) AS dist"  # noqa: S608
        f" FROM {table_name(dim)} v JOIN chunks c ON c.id = v.chunk_id"
        + retrieval_repo._candidate_filter("v.dataset_id", with_docs=with_docs)
        + " ORDER BY dist + 0.0, d.name, c.ordinal, v.chunk_id LIMIT :limit"
    ).bindparams(bindparam("ds", expanding=True))
    return stmt.bindparams(bindparam("docs", expanding=True)) if with_docs else stmt


def _unit_vector(dim: int, angle: float) -> list[float]:
    """Wektor jednostkowy [cos t, sin t, 0, ...]; mniejsze ``t`` = bliżej zapytania q."""
    return [math.cos(angle), math.sin(angle)] + [0.0] * (dim - 2)


async def _seed(sm: async_sessionmaker[AsyncSession], *, dim: int) -> tuple[str, tuple[str, str]]:
    """Dane C2: 2 datasety, 4 dokumenty (jeden wyłączony), przypadki (a) i (b) oraz reszta.

    Zwraca ``(dataset_id, (doc_m, doc_z))`` — para dokumentów dla zakresu ``with_docs=True``.
    """
    ds = await seed_dataset(sm, embedding_model=f"fake-embed-{dim}", embedding_dim=dim)
    other = await seed_dataset(sm, embedding_model=f"fake-embed-{dim}", embedding_dim=dim)
    # Drugi dataset ma wektory najbliższe zapytaniu — filtr dataset_id musi je pominąć.
    other_doc = await insert_document(sm, other, name="inny.txt")
    for ordinal, angle in enumerate((0.001, 0.002)):
        await insert_chunk(
            sm,
            other.id,
            other_doc,
            ordinal=ordinal,
            text=f"obcy {ordinal}",
            vector=_unit_vector(dim, angle),
            dim=dim,
        )

    doc_m = await insert_document(sm, ds, name="m.txt")
    doc_z = await insert_document(sm, ds, name="z.txt")
    doc_a = await insert_document(sm, ds, name="a.txt")
    doc_k = await insert_document(sm, ds, name="k.txt", enabled=False)

    # Przypadek (a): 6 najbliższych odrzuconych przez filtry (available/committed/dokument).
    await insert_chunk(
        sm,
        ds.id,
        doc_m,
        ordinal=0,
        text="off avail m",
        available=False,
        vector=_unit_vector(dim, 0.01),
        dim=dim,
    )
    await insert_chunk(
        sm,
        ds.id,
        doc_z,
        ordinal=0,
        text="off avail z",
        available=False,
        vector=_unit_vector(dim, 0.02),
        dim=dim,
    )
    await insert_chunk(
        sm,
        ds.id,
        doc_m,
        ordinal=1,
        text="off commit m",
        committed=False,
        vector=_unit_vector(dim, 0.03),
        dim=dim,
    )
    await insert_chunk(
        sm,
        ds.id,
        doc_z,
        ordinal=1,
        text="off commit z",
        committed=False,
        vector=_unit_vector(dim, 0.04),
        dim=dim,
    )
    await insert_chunk(
        sm, ds.id, doc_k, ordinal=0, text="off doc k0", vector=_unit_vector(dim, 0.05), dim=dim
    )
    await insert_chunk(
        sm, ds.id, doc_k, ordinal=1, text="off doc k1", vector=_unit_vector(dim, 0.06), dim=dim
    )

    # Przypadek (b): 3 ścisłe bliższe, potem grupa 5 identycznych wektorów na granicy limitu.
    await insert_chunk(
        sm, ds.id, doc_m, ordinal=2, text="blisko m", vector=_unit_vector(dim, 0.10), dim=dim
    )
    await insert_chunk(
        sm, ds.id, doc_z, ordinal=2, text="blisko z0", vector=_unit_vector(dim, 0.11), dim=dim
    )
    await insert_chunk(
        sm, ds.id, doc_z, ordinal=3, text="blisko z1", vector=_unit_vector(dim, 0.12), dim=dim
    )
    tie = _unit_vector(dim, 0.20)
    await insert_chunk(sm, ds.id, doc_m, ordinal=3, text="remis m0", vector=tie, dim=dim)
    await insert_chunk(sm, ds.id, doc_m, ordinal=4, text="remis m1", vector=tie, dim=dim)
    await insert_chunk(sm, ds.id, doc_m, ordinal=5, text="remis m2", vector=tie, dim=dim)
    await insert_chunk(sm, ds.id, doc_z, ordinal=4, text="remis z0", vector=tie, dim=dim)
    await insert_chunk(sm, ds.id, doc_z, ordinal=5, text="remis z1", vector=tie, dim=dim)

    # Pozostałe 12 chunków o zróżnicowanych, dalszych kątach (dokument a.txt).
    for index in range(12):
        await insert_chunk(
            sm,
            ds.id,
            doc_a,
            ordinal=index,
            text=f"dalszy {index}",
            vector=_unit_vector(dim, 0.30 + 0.05 * index),
            dim=dim,
        )
    return ds.id, (doc_m, doc_z)


@pytest.mark.parametrize("dim", [1024, 3072])
@pytest.mark.parametrize("with_docs", [False, True])
async def test_new_vector_sql_equals_reference(
    sm: async_sessionmaker[AsyncSession], dim: int, with_docs: bool
) -> None:
    """Nowy SQL (RANK) == stara referencja: te same wiersze, ta sama kolejność (C2)."""
    dataset_id, docs = await _seed(sm, dim=dim)
    params: dict = {"ds": [dataset_id]}
    if with_docs:
        params["docs"] = list(docs)
    async with transaction(sm) as session:
        await session.execute(
            text("SET @qv = VEC_FromText(:qv)"),
            {"qv": json.dumps(_unit_vector(dim, 0.0))},
        )
        for limit in _LIMITS:
            reference = [
                (row[0], float(row[1]))
                for row in (
                    await session.execute(
                        _reference_vector_sql(dim, with_docs=with_docs),
                        params | {"limit": limit},
                    )
                ).all()
            ]
            new = [
                (row[0], float(row[1]))
                for row in (
                    await session.execute(
                        retrieval_repo._vector_sql(dim, with_docs=with_docs),
                        params | {"limit": limit},
                    )
                ).all()
            ]
            assert new == reference
            if limit == _TIE_LIMIT:
                # Przypadek (b): 7 wierszy, wśród nich dokładnie 4 z remisowym dystansem.
                assert len(reference) == _TIE_LIMIT
                assert max(Counter(dist for _, dist in reference).values()) == _TIE_IN_RESULT
