"""Etap ``chats``: ``dialog`` → ``chats`` + ``chat_datasets`` (kontrakt §2, WP E4-6b2).

Rozstrzyganie wiersza ``dialog`` (czyste funkcje, bez bazy) mieszka obok, w
:mod:`app.tools.ragflow_migrate.stages.chats_rows` — razem przekraczały limit 400 linii pliku;
BRIEF WP E4-6b2 dopuszcza pomocnicze moduły w pakiecie narzędzia.
"""

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageInventory, StageResult
from app.tools.ragflow_migrate.stages.chats_rows import resolve_chats

#: Kolumny celu pisane przez etap (kolejność = lista INSERT); źródło: alembic ``0001_initial``.
COLUMNS: tuple[str, ...] = (
    "id",
    "tenant_id",
    "created_by",
    "name",
    "description",
    "icon",
    "language",
    "llm_id",
    "llm_setting",
    "prompt_type",
    "prompt_config",
    "similarity_threshold",
    "vector_similarity_weight",
    "top_n",
    "top_k",
    "rerank_candidates_count",
    "rerank_id",
    "do_refer",
    "meta_data_filter",
    "status",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

#: Kolumny ``chats`` z wartościami JSON — przy idempotencji porównywane po ``json.loads``.
JSON_COLUMNS: frozenset[str] = frozenset({"llm_setting", "prompt_config", "meta_data_filter"})

_COLUMN_LIST = ", ".join(COLUMNS)
# Nazwy kolumn pochodzą ze stałej ``COLUMNS`` (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = f"INSERT INTO chats ({_COLUMN_LIST}) VALUES ({', '.join(':' + c for c in COLUMNS)})"  # noqa: S608
_UPDATE = f"UPDATE chats SET {', '.join(f'{c} = :{c}' for c in COLUMNS)} WHERE id = :id"  # noqa: S608
_SELECT_EXISTING = f"SELECT {_COLUMN_LIST} FROM chats WHERE id IN :ids"  # noqa: S608
_SELECT_IDS = "SELECT id FROM chats WHERE id IN :ids"
_SELECT_DATASETS = "SELECT id, embedding_model, embedding_dim FROM datasets"
_SELECT_LINKS = (
    "SELECT chat_id, dataset_id FROM chat_datasets WHERE chat_id IN :ids ORDER BY chat_id, ordinal"
)
_INSERT_LINK = (
    "INSERT INTO chat_datasets (chat_id, dataset_id, ordinal)"
    " VALUES (:chat_id, :dataset_id, :ordinal)"
)
_DELETE_LINKS = "DELETE FROM chat_datasets WHERE chat_id = :chat_id"


def _source_users(src: Source) -> set[str]:
    """Id użytkowników źródła — właściciele bez konsultowania celu (``plan``, kontrakt §2)."""
    return {str(row["id"]) for row in src.rows("user")}


def _shared_model_names(ctx: RunContext) -> dict[str, str]:
    """Nazwy modeli z etapu ``models`` (``ctx.shared['model_names']``, kontrakt §2)."""
    return {str(key): str(value) for key, value in ctx.shared.get("model_names", {}).items()}


async def _owner_ids(session: AsyncSession, ctx: RunContext) -> set[str]:
    """Id właścicieli: z ``ctx.shared['user_ids']``, inaczej z celu (kontrakt §2)."""
    shared = ctx.shared.get("user_ids")
    if shared is not None:
        return {str(value) for value in shared}
    result = await session.execute(text("SELECT id FROM users"))
    return {str(value) for value in result.scalars().all()}


async def _target_datasets(
    session: AsyncSession,
) -> tuple[set[str], dict[str, tuple[Any, Any]]]:
    """Id datasetów celu i ich ``(embedding_model, embedding_dim)`` — do uwag czatu (§2)."""
    dataset_ids: set[str] = set()
    embeddings: dict[str, tuple[Any, Any]] = {}
    for dataset_id, embedding_model, embedding_dim in (
        await session.execute(text(_SELECT_DATASETS))
    ).all():
        dataset_ids.add(str(dataset_id))
        embeddings[str(dataset_id)] = (embedding_model, embedding_dim)
    return dataset_ids, embeddings


def _normalized(column: str, value: Any) -> Any:
    """Wartość kolumny do porównania idempotencji; kolumny JSON porównujemy po ``json.loads``."""
    if column in JSON_COLUMNS:
        return None if value is None else json.loads(str(value))
    return str(value)


def _unchanged(existing: Mapping[str, Any], computed: Mapping[str, Any]) -> bool:
    """True, gdy każda kolumna wiersza istniejącego równa się wyliczonej (idempotencja)."""
    return all(
        _normalized(column, existing[column]) == _normalized(column, computed[column])
        for column in COLUMNS
    )


async def _fetch_existing(session: AsyncSession, ids: list[str]) -> dict[str, Mapping[str, Any]]:
    """Wiersze celu dla podanych id (klucz = id); puste ``ids`` → pusta mapa."""
    if not ids:
        return {}
    statement = text(_SELECT_EXISTING).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {
        str(row["id"]): {column: row[column] for column in COLUMNS}
        for row in result.mappings().all()
    }


async def _fetch_links(session: AsyncSession, ids: list[str]) -> dict[str, list[str]]:
    """Powiązania czatów z datasetami celu w kolejności ``ordinal`` (klucz = ``chat_id``)."""
    if not ids:
        return {}
    statement = text(_SELECT_LINKS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    links: dict[str, list[str]] = {}
    for chat_id, dataset_id in result.all():
        links.setdefault(str(chat_id), []).append(str(dataset_id))
    return links


async def _write_links(session: AsyncSession, chat_id: str, dataset_ids: list[str]) -> None:
    """Pisze powiązania czatu (``ordinal`` = indeks listy); pusta lista → bez SQL."""
    for ordinal, dataset_id in enumerate(dataset_ids):
        await session.execute(
            text(_INSERT_LINK),
            {"chat_id": chat_id, "dataset_id": dataset_id, "ordinal": ordinal},
        )


async def _target_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w ``chats`` po etapie."""
    if not ids:
        return set()
    statement = text(_SELECT_IDS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


class ChatsStage:
    """``dialog`` → ``chats`` z powiązaniami ``chat_datasets`` (kontrakt §2)."""

    name = "chats"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz: licznik ``dialog`` i uwagi (bez zapisu, kontrakt §2).

        Uwagi liczy ta sama droga co ``run`` (``resolve_chats``); ``plan`` nie czyta celu, więc
        niezgodność embeddingów wykrywa po ``embd_id`` datasetów źródła (CONTRACT §7, WP E4-6c).
        """
        if not src.has_table("dialog"):
            return StageInventory(stage=self.name, source_counts={}, issues=[], not_migrated={})
        rows = src.rows("dialog")
        datasets = src.rows("knowledgebase") if src.has_table("knowledgebase") else []
        dataset_ids = {str(row["id"]) for row in datasets}
        embeddings = {str(row["id"]): row["embd_id"] for row in datasets}
        _targets, _links, issues = resolve_chats(
            rows,
            _source_users(src),
            _shared_model_names(ctx),
            ctx.model_map,
            dataset_ids,
            embeddings,
            {},
            0,
        )
        return StageInventory(
            stage=self.name,
            source_counts={"dialog": len(rows)},
            issues=issues,
            not_migrated={},
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapis ``dialog`` → ``chats`` + ``chat_datasets``; idempotencja po kolumnach i linkach.

        ``--since`` (kontrakt §2) zawęża upsert do czatów zmienionych po ``since_ms``;
        ``ctx.shared['chat_ids']`` liczymy z pełnej tabeli, by etap ``sessions`` nie zgłosił
        fałszywych ``session_chat_missing``.
        """
        if not src.has_table("dialog"):
            return StageResult(
                stage=self.name,
                source_count=0,
                created=0,
                updated=0,
                skipped=0,
                target_count=0,
                issues=[],
            )
        rows = src.rows("dialog")
        changed = rows if ctx.since_ms is None else src.rows_changed("dialog", ctx.since_ms)
        source_ids = [str(row["id"]) for row in rows]
        existing = await _fetch_existing(session, source_ids)
        stored_times = {
            chat_id: (int(row["create_time"]), int(row["update_time"]))
            for chat_id, row in existing.items()
        }
        dataset_ids, embeddings = await _target_datasets(session)
        targets, links, issues = resolve_chats(
            changed,
            await _owner_ids(session, ctx),
            _shared_model_names(ctx),
            ctx.model_map,
            dataset_ids,
            embeddings,
            stored_times,
            ctx.clock.now_ms(),
        )
        stored_links = await _fetch_links(session, source_ids)
        created = updated = skipped = 0
        for target in targets:
            chat_id = str(target["id"])
            expected = links[chat_id]
            current = existing.get(chat_id)
            if current is None:
                await session.execute(text(_INSERT), target)
                await _write_links(session, chat_id, expected)
                created += 1
            elif _unchanged(current, target) and stored_links.get(chat_id, []) == expected:
                skipped += 1
            else:
                await session.execute(text(_UPDATE), target)
                await session.execute(text(_DELETE_LINKS), {"chat_id": chat_id})
                await _write_links(session, chat_id, expected)
                updated += 1
        skipped += len(changed) - len(targets)  # wiersze świadomie pominięte (Issue critical)
        present = await _target_ids(session, source_ids)
        ctx.shared["chat_ids"] = present
        return StageResult(
            stage=self.name,
            source_count=len(changed),
            created=created,
            updated=updated,
            skipped=skipped,
            target_count=len(present),
            issues=issues,
        )
