"""Ponawianie transakcji zapisu chunków przy konflikcie blokad InnoDB (brief T6, DEC-088).

InnoDB przy deadlocku (1213) albo przekroczeniu czasu oczekiwania na blokadę (1205)
cofa CAŁĄ transakcję. Parse i wektory są już policzone w pamięci, więc ponawiamy
wyłącznie transakcję zapisu — każda próba to nowa transakcja od początku.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy.exc import OperationalError

from app.db.repositories import chunk_vectors
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.uow import transaction

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.db.repositories.chunks import ChunkInsert
    from app.db.repositories.datasets import DatasetRow
    from app.db.repositories.documents import DocumentRow

logger = logging.getLogger(__name__)

RETRY_CODES = frozenset({1213, 1205})  # deadlock, lock wait timeout
MAX_ATTEMPTS = 3
BACKOFF_S: tuple[float, ...] = (0.2, 0.5)  # przerwa po 1. i 2. nieudanej próbie


def is_lock_conflict(exc: BaseException) -> bool:
    """True dla ``OperationalError``, którego ``exc.orig.args[0]`` jest w ``RETRY_CODES``."""
    if not isinstance(exc, OperationalError):
        return False
    orig = exc.orig
    if orig is None or not orig.args:
        return False
    return orig.args[0] in RETRY_CODES


async def retry_lock_conflicts[T](
    op: Callable[[], Awaitable[T]], *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> T:
    """Wykonuje ``op()`` do ``MAX_ATTEMPTS`` razy, ponawiając po konflikcie blokad InnoDB.

    Po konflikcie blokad czeka ``BACKOFF_S[attempt - 1]`` i próbuje od nowa; ostatnia
    próba albo wyjątek innego rodzaju (także ``OperationalError`` spoza ``RETRY_CODES``)
    leci dalej.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await op()
        except OperationalError as exc:
            if attempt >= MAX_ATTEMPTS or not is_lock_conflict(exc):
                raise
            logger.warning(
                "chunk commit retried after lock conflict",
                extra={"attempt": attempt},
            )
            await sleep(BACKOFF_S[attempt - 1])
    raise AssertionError("unreachable")


async def write_parse_result(  # noqa: PLR0913 — pola bloku (c) z _save
    sm: async_sessionmaker[AsyncSession],
    *,
    ds: DatasetRow,
    doc: DocumentRow,
    task_pk: int,
    rows: list[ChunkInsert],
    vectors: list[list[float]],
    t0: float,
    now_ms: int,
) -> None:
    """Zapisuje wynik parse w JEDNEJ transakcji, ponawianej przy konflikcie blokad (blok (c))."""

    async def op() -> None:
        async with transaction(sm) as session:
            # Blokada datasetu przed zapisem (kolejność blokad; deadlock 1213 — DEC-088 p. 3).
            await datasets_repo.lock(session, ds.id)
            await chunks_repo.delete_uncommitted_by_task(session, task_pk)
            await chunks_repo.insert_many(session, rows, now_ms=now_ms)
            vec_rows = [(r.id, ds.id, v) for r, v in zip(rows, vectors, strict=True)]
            await chunk_vectors.insert_many(session, ds.embedding_dim, vec_rows)
            await chunks_repo.commit_task(session, doc.id, task_pk, now_ms=now_ms)
            await documents_repo.finish_done(
                session, doc.id, duration_s=time.monotonic() - t0, now_ms=now_ms
            )
            await datasets_repo.recount(session, ds.id, now_ms=now_ms)

    await retry_lock_conflicts(op)
