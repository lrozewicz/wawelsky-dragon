"""Ponowny embedding chunków importu bazy wiedzy (K19 §5, CONTRACT E7-1b §2).

Etap ``embedding`` importu: chunki zapisane bez wektorów (paczka ``included=false``) albo
importowane modelem innym niż model paczki dostają wektory liczone ISTNIEJĄCĄ ścieżką
embeddingu — tym samym przepisem, co zwykła ingestia (``ingest_pipeline._embed_all``):
tekst = ``embed.recipe_text(content, questions)`` (pytania, a bez nich treść), wektor tytułu
dokumentu (``Path(name).stem``) mieszany wagą ``embed.filename_weight(parser_config)``,
``embed_texts`` z ``batch_size`` i współbieżnością z ustawień ingestii (E5-H8b). Dzięki temu
wektor w ``chunk_vec_d<dim>`` jest identyczny z tym, który powstałby przy parsowaniu
dokumentu, więc import „1:1" i ponowny embedding dają ten sam wynik.

Dokumenty importu są już w bazie (T2), a chunki w ``chunks`` (T3) — moduł tylko czyta treść,
liczy wektory i dopisuje wiersze do tabeli wektorów.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound
from app.db.repositories import chunk_vectors, retrieval
from app.db.repositories import documents as documents_repo
from app.db.uow import transaction
from app.llm.types import ModelRef
from app.services.concurrency import resolve_concurrency
from app.services.embed import combine, embed_texts, filename_weight, recipe_text
from app.services.kb_import_write import ImportPlan, ImportProgress
from app.worker.errors import PermanentError

if TYPE_CHECKING:
    from app.core.container import Container
    from app.llm.gateway import LLMGateway
    from app.llm.registry import ModelRegistry

__all__ = ["embed_chunks"]

# Partia chunków czytana z bazy i zapisywana w jednej transakcji (K19 §5 — partie ≤ 1000).
CHUNK_BATCH = 1000


@dataclass(frozen=True)
class _EmbedItem:
    """Chunk do ponownego embeddingu: tekst, tytuł dokumentu i waga zmieszania wektorów."""

    chunk_id: str
    text: str  # recipe_text(content, questions)
    title: str  # Path(documents.name).stem — jak w ingestii
    weight: float  # filename_weight(documents.parser_config)


async def embed_chunks(
    container: Container,
    *,
    plan: ImportPlan,
    chunk_ids: Sequence[str],
    progress: ImportProgress,
) -> None:
    """Liczy wektory chunków planu istniejącą ścieżką embeddingu i zapisuje do tabeli wektorów.

    Chunki czytamy z bazy partiami ≤ ``CHUNK_BATCH`` (kolejność ``ordinal, id``), liczymy
    wektory tym samym przepisem co ingestia i zapisujemy partię w jednej transakcji; postęp
    ``("embedding", done, total)`` rośnie razem z ukończonymi partiami ``embed_texts``
    (``total`` = liczba przekazanych ``chunk_ids``). ``check_cancel`` idzie do ``embed_texts``
    — jego wyjątek propaguje, a wektory partii już zapisanych zostają (sprząta wołający, T7).
    """
    total = len(chunk_ids)
    if total == 0:
        return
    model = await _resolve_embedding(_models(container), plan.embedding_model)
    concurrency = resolve_concurrency(model, container.settings.embed_concurrency)
    done = 0
    for start in range(0, total, CHUNK_BATCH):
        items = await _read_batch(container, list(chunk_ids[start : start + CHUNK_BATCH]))
        if not items:
            continue
        vectors = await _embed_batch(
            container, model, plan, items, concurrency, progress, done, total
        )
        await _write_vectors(container, plan, items, vectors)
        done += len(items)


async def _read_batch(container: Container, chunk_ids: Sequence[str]) -> list[_EmbedItem]:
    """Partia chunków z bazy: tekst do embeddingu, tytuł i waga z dokumentów (JOIN, C2.3)."""
    async with transaction(_sessionmaker(container)) as session:
        rows = await retrieval.load_chunks(session, chunk_ids)
        document_ids = sorted({row.document_id for row in rows})
        documents = await documents_repo.get_many(session, document_ids)
    configs = {document.id: document.parser_config for document in documents}
    rows.sort(key=lambda row: (row.ordinal, row.id))
    return [
        _EmbedItem(
            chunk_id=row.id,
            text=recipe_text(row.content, row.questions),
            title=Path(row.document_name).stem,
            weight=filename_weight(configs.get(row.document_id, {})),
        )
        for row in rows
    ]


async def _embed_batch(  # noqa: PLR0913, PLR0917 — model, partia i stan postępu z pętli
    container: Container,
    model: ModelRef,
    plan: ImportPlan,
    items: list[_EmbedItem],
    concurrency: int,
    progress: ImportProgress,
    offset: int,
    total: int,
) -> list[list[float]]:
    """Wektory partii: tytuł dokumentu mieszany z treścią, jak krok 10 ingestii (C7)."""
    llm = _llm(container)
    titles = sorted({item.title for item in items})
    title_vectors = await embed_texts(
        llm, model, titles, batch_size=1, expected_dim=plan.embedding_dim
    )
    by_title = dict(zip(titles, title_vectors, strict=True))

    async def on_batch(done_in_batch: int, _total_in_batch: int) -> None:
        await progress.stage("embedding", offset + done_in_batch, total)

    content_vectors = await embed_texts(
        llm,
        model,
        [item.text for item in items],
        batch_size=container.settings.embed_batch_size,
        expected_dim=plan.embedding_dim,
        concurrency=concurrency,
        on_batch=on_batch,
        check_cancel=progress.check_cancel,
    )
    return [
        combine(by_title[item.title], vector, item.weight)
        for item, vector in zip(items, content_vectors, strict=True)
    ]


async def _write_vectors(
    container: Container,
    plan: ImportPlan,
    items: list[_EmbedItem],
    vectors: list[list[float]],
) -> None:
    """Zapisuje wektory partii do ``chunk_vec_d<dim>`` (jedna transakcja na partię)."""
    rows = [
        (item.chunk_id, plan.dataset_id, vector)
        for item, vector in zip(items, vectors, strict=True)
    ]
    async with transaction(_sessionmaker(container)) as session:
        await chunk_vectors.insert_many(session, plan.embedding_dim, rows)


async def _resolve_embedding(models: ModelRegistry, name: str) -> ModelRef:
    """Model embeddingu z planu; nieznany → ``PermanentError`` (jak krok 3 ingestii)."""
    try:
        return await models.resolve(name, "embedding")
    except NotFound as exc:
        raise PermanentError(f"embedding model not found: {name}") from exc


def _models(container: Container) -> ModelRegistry:
    """Rejestr modeli z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
    models = container.models
    if models is None:
        raise RuntimeError("container not started")
    return models


def _llm(container: Container) -> LLMGateway:
    """Bramka LLM z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
    llm = container.llm
    if llm is None:
        raise RuntimeError("container not started")
    return llm


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker
