"""Repozytorium importu chunków (T3, CONTRACT E7-1b §2) — Core ``text()``.

Osobny moduł od ``chunks.py``: import zapisuje pola, których ``ChunkInsert``/``insert_many``
nie znają (``available`` z paczki, ``committed=1`` od razu, ``tags``, ``image_id``, ``parent_id``)
i wstawia ``task_id`` = NULL (kolumna NULL-owalna w DDL 0001; import nie ma wiersza zadania).
Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms


@dataclass(frozen=True)
class ChunkImportRow:
    """Wiersz ``chunks`` z paczki (pola 1:1, kolumny pochodne policzone przez wołającego)."""

    id: str
    document_id: str
    dataset_id: str
    ordinal: int
    chunk_type: str
    content: str
    content_llm: str | None
    content_ft: str
    content_stem: str
    title_ft: str
    keywords: Sequence[str]  # → JSON
    questions: Sequence[str]  # → JSON
    important_ft: str
    question_ft: str
    tags: list[Any] | dict[str, Any]  # → JSON: lista z kolumny ``chunks.tags`` albo obiekt (T12)
    positions: Any  # JSON wprost z paczki (None → NULL)
    page_from: int | None
    page_to: int | None
    image_id: str | None
    parent_id: str | None
    available: bool
    token_count: int
    embed_source: str


# task_id = NULL i committed = 1 na stałe — import wstawia chunki widoczne od razu (T3).
_INSERT_SQL = text(
    "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type, content,"
    " content_llm, content_ft, content_stem, title_ft, keywords, questions, important_ft,"
    " question_ft, tags, positions, page_from, page_to, image_id, parent_id, available,"
    " committed, task_id, token_count, embed_source, create_time, create_date,"
    " update_time, update_date)"
    " VALUES (:id, :document_id, :dataset_id, :ordinal, :chunk_type, :content, :content_llm,"
    " :content_ft, :content_stem, :title_ft, :keywords, :questions, :important_ft,"
    " :question_ft, :tags, :positions, :page_from, :page_to, :image_id, :parent_id,"
    " :available, 1, NULL, :token_count, :embed_source, :now, :now_date, :now, :now_date)"
)

_SET_PARENT_SQL = text(
    "UPDATE chunks SET parent_id = :parent_id, update_time = :now, update_date = :now_date"
    " WHERE id = :id"
)


def _params(row: ChunkImportRow, *, now_ms: int) -> dict[str, Any]:
    """ChunkImportRow → parametry INSERT; kolumny JSON-owe jako listy/dykt z paczki."""
    return {
        "id": row.id,
        "document_id": row.document_id,
        "dataset_id": row.dataset_id,
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
        "tags": json.dumps(row.tags, ensure_ascii=False),
        "positions": None
        if row.positions is None
        else json.dumps(row.positions, ensure_ascii=False),
        "page_from": row.page_from,
        "page_to": row.page_to,
        "image_id": row.image_id,
        "parent_id": row.parent_id,
        "available": int(row.available),
        "token_count": row.token_count,
        "embed_source": row.embed_source,
        "now": now_ms,
        "now_date": from_ms(now_ms),
    }


async def insert_many(
    session: AsyncSession, rows: Sequence[ChunkImportRow], *, now_ms: int
) -> None:
    """Wstawia chunki importu (committed=1, available z paczki); [] → bez SQL."""
    if not rows:
        return
    await session.execute(_INSERT_SQL, [_params(row, now_ms=now_ms) for row in rows])


async def set_parent_ids(session: AsyncSession, parents: Mapping[str, str], *, now_ms: int) -> None:
    """Dopisuje ``parent_id`` chunkiem, których rodzica nie było jeszcze przy insercie.

    ``parents``: ``{chunk_id: parent_id}``; jest to drugi przebieg po wszystkich partiach
    (rodzic zwykle poprzedza dziecko w ``chunks.jsonl``, wyjątek pokrywa ten UPDATE).
    """
    if not parents:
        return
    params = [
        {"id": chunk_id, "parent_id": parent_id, "now": now_ms, "now_date": from_ms(now_ms)}
        for chunk_id, parent_id in parents.items()
    ]
    await session.execute(_SET_PARENT_SQL, params)
