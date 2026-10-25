"""Repozytorium tabeli chat_datasets (kontrakt C1) — Core ``text()`` z parametrami wiązanymi.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.policy import VisibilityFilter

_INSERT_MANY_SQL = text(
    "INSERT INTO chat_datasets (chat_id, dataset_id, ordinal)"
    " VALUES (:chat_id, :dataset_id, :ordinal)"
)

_DELETE_BINDINGS_SQL = text("DELETE FROM chat_datasets WHERE chat_id = :chat_id")

# Pola datasetu dla walidacji wiązań czatu (C2.1); id podane listą — expanding (wzorzec niżej).
_BRIEFS_SQL = text(
    "SELECT id, name, tenant_id, permission, chunk_count, embedding_model, status"
    " FROM datasets WHERE id IN :ids"
).bindparams(bindparam("ids", expanding=True))

# Nazwy aktywnych datasetów wielu czatów jednym zapytaniem; kolejność po ordinal (C1).
_NAMES_BY_CHAT_SQL = text(
    "SELECT cd.chat_id AS chat_id, cd.dataset_id AS dataset_id, d.name AS name"
    " FROM chat_datasets AS cd JOIN datasets AS d ON d.id = cd.dataset_id"
    " WHERE cd.chat_id IN :chat_ids AND d.status = '1'"
    " ORDER BY cd.chat_id, cd.ordinal, cd.dataset_id"
).bindparams(bindparam("chat_ids", expanding=True))

_LIST_IDS_SQL = text(
    "SELECT dataset_id FROM chat_datasets WHERE chat_id = :chat_id ORDER BY ordinal, dataset_id"
)

# Jedno zapytanie: dokumenty podanych id należące do datasetów czatu (brief T3).
_DOCS_INSIDE_SQL = text(
    "SELECT id FROM documents WHERE id IN :docs AND dataset_id IN :ds"
).bindparams(bindparam("docs", expanding=True), bindparam("ds", expanding=True))

# Użycie datasetu (K20 §4): czaty widoczne dla aktora (name, potem id) z limitem+1 —
# nadwyżka świadczy o ucięciu; osobny COUNT wiązań niewidocznych (bez nazw i id).
# Zakres widoczności z ``VisibilityFilter`` (wzorzec ``datasets._VISIBILITY_WHERE``).
_USAGE_VISIBLE_SQL = text(
    "SELECT c.id, c.name"
    " FROM chat_datasets AS cd JOIN chats AS c ON c.id = cd.chat_id"
    " WHERE cd.dataset_id = :ds AND c.tenant_id IN :owners"
    " ORDER BY c.name, c.id LIMIT :limit"
).bindparams(bindparam("owners", expanding=True))
_USAGE_VISIBLE_ALL_SQL = text(
    "SELECT c.id, c.name"
    " FROM chat_datasets AS cd JOIN chats AS c ON c.id = cd.chat_id"
    " WHERE cd.dataset_id = :ds"
    " ORDER BY c.name, c.id LIMIT :limit"
)
_USAGE_HIDDEN_SQL = text(
    "SELECT COUNT(*)"
    " FROM chat_datasets AS cd JOIN chats AS c ON c.id = cd.chat_id"
    " WHERE cd.dataset_id = :ds AND c.tenant_id NOT IN :owners"
).bindparams(bindparam("owners", expanding=True))


async def insert_many(session: AsyncSession, chat_id: str, dataset_ids: Sequence[str]) -> None:
    """Wiąże datasety z czatem; ordinal = indeks na liście; [] → bez SQL (C9)."""
    if not dataset_ids:
        return
    await session.execute(
        _INSERT_MANY_SQL,
        [
            {"chat_id": chat_id, "dataset_id": dataset_id, "ordinal": ordinal}
            for ordinal, dataset_id in enumerate(dataset_ids)
        ],
    )


async def list_dataset_ids(session: AsyncSession, chat_id: str) -> list[str]:
    """Id datasetów czatu w kolejności ordinal (C9)."""
    rows = (await session.execute(_LIST_IDS_SQL, {"chat_id": chat_id})).all()
    return [row[0] for row in rows]


@dataclass(frozen=True)
class DatasetBrief:
    """Pola datasetu potrzebne walidacji wiązań czatu (kontrakt C1)."""

    id: str
    name: str
    tenant_id: str
    permission: str
    chunk_count: int
    embedding_model: str
    status: str


async def dataset_briefs(session: AsyncSession, dataset_ids: Sequence[str]) -> list[DatasetBrief]:
    """Pola datasetów po id; kolejność wejścia, brakujące pominięte; [] → [] bez SQL (C1)."""
    if not dataset_ids:
        return []
    rows = (await session.execute(_BRIEFS_SQL, {"ids": list(dataset_ids)})).mappings().all()
    by_id = {row["id"]: row for row in rows}
    return [
        DatasetBrief(
            id=row["id"],
            name=row["name"],
            tenant_id=row["tenant_id"],
            permission=row["permission"],
            chunk_count=int(row["chunk_count"]),
            embedding_model=row["embedding_model"],
            status=row["status"],
        )
        for dataset_id in dataset_ids
        if (row := by_id.get(dataset_id)) is not None
    ]


async def replace(session: AsyncSession, chat_id: str, dataset_ids: Sequence[str]) -> None:
    """Podmienia wiązania czatu: DELETE starych + insert_many nowych (C1)."""
    await session.execute(_DELETE_BINDINGS_SQL, {"chat_id": chat_id})
    await insert_many(session, chat_id, dataset_ids)


async def names_by_chat(
    session: AsyncSession, chat_ids: Sequence[str]
) -> dict[str, list[tuple[str, str]]]:
    """chat_id → [(dataset_id, dataset_name)] po ordinal, tylko datasets.status = '1' (C1).

    Czat bez wiązań (lub bez aktywnych datasetów) → brak klucza; [] → {} bez SQL.
    """
    if not chat_ids:
        return {}
    rows = (await session.execute(_NAMES_BY_CHAT_SQL, {"chat_ids": list(chat_ids)})).all()
    names: dict[str, list[tuple[str, str]]] = {}
    for chat_id, dataset_id, dataset_name in rows:
        names.setdefault(chat_id, []).append((dataset_id, dataset_name))
    return names


async def usage(
    session: AsyncSession, dataset_id: str, *, visibility: VisibilityFilter, limit: int
) -> tuple[list[tuple[str, str]], int, bool]:
    """Czaty powiązane z datasetem: widoczne (id, name), ukryte wiązania, ucięcie (K20 §4).

    Zakres widoczności z ``VisibilityFilter``: ``all`` = superuser (widzi wszystkie wiązania,
    ukryte = 0); inaczej widoczne są tylko czaty ``tenant_id`` z ``owner_ids``. Pobiera
    ``limit + 1`` wierszy — pozycja nad limit świadczy o ucięciu i jest odrzucana.
    Niewidoczne wiązania zlicza osobnym COUNT-em, bez ujawniania nazw i id.
    """
    if not visibility.all and not visibility.owner_ids:
        return [], 0, False
    params: dict[str, Any] = {"ds": dataset_id, "limit": limit + 1}
    if visibility.all:
        stmt = _USAGE_VISIBLE_ALL_SQL
        hidden = 0
    else:
        stmt = _USAGE_VISIBLE_SQL
        params["owners"] = sorted(visibility.owner_ids)
        hidden = int((await session.execute(_USAGE_HIDDEN_SQL, params)).scalar_one())
    rows = (await session.execute(stmt, params)).all()
    truncated = len(rows) > limit
    return [(row[0], row[1]) for row in rows[:limit]], hidden, truncated


async def documents_outside(
    session: AsyncSession, dataset_ids: Sequence[str], doc_ids: Sequence[str]
) -> list[str]:
    """doc_ids (bez duplikatów, w kolejności wejścia) spoza datasetów czatu (C9).

    dataset_ids [] → wszystkie doc_ids; doc_ids [] → [].
    """
    if not doc_ids:
        return []
    unique = list(dict.fromkeys(doc_ids))
    if not dataset_ids:
        return unique
    rows = (
        await session.execute(_DOCS_INSIDE_SQL, {"docs": unique, "ds": list(dataset_ids)})
    ).all()
    inside = {row[0] for row in rows}
    return [doc_id for doc_id in unique if doc_id not in inside]
