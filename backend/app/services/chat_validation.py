"""Walidacja dataset_ids (C2.1), domyślne prompt_config (C2.2) i budowa widoku czatu (R1).

Wydzielone z chats.py (rozbicie sankcjonowane briefem T2b — limit 400 linii pliku);
komunikaty błędów dosłownie z C8, nazwy importowalne dalej z ``app.services.chats``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from app.core.errors import Conflict, NotFound
from app.db.repositories import chat_datasets as chat_datasets_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories.datasets import DatasetRecord
from app.domain.chat.config import DEFAULT_PROMPT_CONFIG
from app.domain.policy import Action, ResourceRef, can

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.repositories.chats import ChatRow
    from app.domain.policy.principal import Principal
    from app.llm.registry import ModelRegistry
    from app.llm.types import ModelType

# Upewniony literał uprawnienia datasetu (ResourceRef.permission); jak w app/services/retrieval.py.
_PERMISSION = Literal["me", "team"]


@dataclass(frozen=True)
class ChatView:
    """Widok czatu (kontrakt C2); llm_id/tenant_llm_id wg R1."""

    id: str
    tenant_id: str
    name: str
    description: str
    icon: str
    language: str
    llm_id: str  # models.id albo "" (R1)
    tenant_llm_id: str | None  # models.id albo None
    llm_setting: dict[str, Any]
    prompt_type: str
    prompt_config: dict[str, Any]
    similarity_threshold: float
    vector_similarity_weight: float
    top_n: int
    top_k: int
    rerank_candidates_count: int
    rerank_id: str  # models.name z bazy (K11 §4)
    tenant_rerank_id: str | None  # models.id albo None
    do_refer: str
    meta_data_filter: dict[str, Any]  # {} gdy w bazie None
    status: str
    dataset_ids: list[str]
    kb_names: list[str]
    nickname: str  # "" poza list (prezenter szczegółu nie emituje)
    tenant_avatar: str | None  # None poza list
    create_time: int
    update_time: int
    llm_name: str = ""  # nazwa modelu z wiersza czatu (E2-2b C2: llm.model_name v0.24)
    datasets: tuple[DatasetRecord, ...] = ()  # wypełniane w liście (E2-2b C2)


def apply_prompt_defaults(
    prompt_config: Mapping[str, Any] | None, has_datasets: bool
) -> dict[str, Any]:
    """Domyślne prompt_config (port chat_api.py:397-414, kontrakt C2.2); głębokie kopie wartości."""
    pc: dict[str, Any] = dict(prompt_config) if prompt_config is not None else {}
    for key, value in DEFAULT_PROMPT_CONFIG.items():
        if (key == "system" and not pc.get(key)) or key not in pc:
            if key == "system" and not has_datasets:
                # Brak datasetów: nie zasiewaj datasetowego promptu systemowego (C2.2).
                pc[key] = ""
            else:
                pc[key] = deepcopy(value)
    if has_datasets and not pc.get("parameters") and "{knowledge}" in pc.get("system", ""):
        pc["parameters"] = [{"key": "knowledge", "optional": False}]
    if not any(p.get("key") == "date" for p in pc.get("parameters", [])):
        pc.setdefault("parameters", []).append({"key": "date", "optional": True})
    return pc


async def validate_dataset_ids(
    session: AsyncSession, principal: Principal, dataset_ids: Sequence[str]
) -> list[str]:
    """Walidacja dataset_ids (C2.1): własność/status, chunk_count, jeden model embeddingu."""
    normalized = [d for d in dataset_ids if d]
    briefs = await chat_datasets_repo.dataset_briefs(session, normalized)
    by_id = {b.id: b for b in briefs}
    for dataset_id in normalized:
        brief = by_id.get(dataset_id)
        if (
            brief is None
            or brief.status != "1"
            or not can(
                principal,
                Action.READ,
                ResourceRef(
                    kind="dataset",
                    owner_id=brief.tenant_id,
                    permission=cast(_PERMISSION, brief.permission),
                    id=brief.id,
                ),
            )
        ):
            raise NotFound(f"You don't own the dataset {dataset_id}")
        if brief.chunk_count == 0:
            raise Conflict(f"The dataset {dataset_id} doesn't own parsed file")
    if len({b.embedding_model.split("@")[0] for b in briefs}) > 1:
        raise Conflict(
            f"Datasets use different embedding models: {[b.embedding_model for b in briefs]}"
        )
    return normalized


async def resolve_model_ids(
    models: ModelRegistry, rows: Sequence[ChatRow]
) -> dict[tuple[str, str], str | None]:
    """(nazwa, typ) → models.id dla llm_id ("chat") i rerank_id ("rerank"); każda nazwa raz (R1)."""
    cache: dict[tuple[str, str], str | None] = {}
    for row in rows:
        await _fill_id(models, cache, row.llm_id, "chat")
        await _fill_id(models, cache, row.rerank_id, "rerank")
    return cache


async def _fill_id(
    models: ModelRegistry,
    cache: dict[tuple[str, str], str | None],
    name: str,
    model_type: ModelType,
) -> None:
    """Rozwiązuje nazwę na models.id; "" → None (puste pole), brak modelu → None (R1)."""
    if (name, model_type) in cache:
        return
    if not name:
        cache[name, model_type] = None
        return
    try:
        cache[name, model_type] = (await models.resolve(name, model_type)).id
    except NotFound:
        cache[name, model_type] = None


def chat_view(
    chat: ChatRow,
    *,
    model_ids: Mapping[tuple[str, str], str | None],
    bindings: Sequence[tuple[str, str]],
    nickname: str,
    tenant_avatar: str | None,
) -> ChatView:
    """ChatRow → ChatView (R1): llm/tenant_llm z models.id; brak → ""/None; meta None → {}.

    ``llm_name`` = nazwa modelu z wiersza (``chat.llm_id``), a ``llm_id`` = models.id.
    """
    llm = model_ids[chat.llm_id, "chat"]
    return ChatView(
        id=chat.id,
        tenant_id=chat.tenant_id,
        name=chat.name,
        description=chat.description,
        icon=chat.icon,
        language=chat.language,
        llm_id=llm if llm is not None else "",
        tenant_llm_id=llm,
        llm_setting=dict(chat.llm_setting),
        prompt_type=chat.prompt_type,
        prompt_config=dict(chat.prompt_config),
        similarity_threshold=chat.similarity_threshold,
        vector_similarity_weight=chat.vector_similarity_weight,
        top_n=chat.top_n,
        top_k=chat.top_k,
        rerank_candidates_count=chat.rerank_candidates_count,
        rerank_id=chat.rerank_id,
        tenant_rerank_id=model_ids[chat.rerank_id, "rerank"],
        do_refer=chat.do_refer,
        meta_data_filter=dict(chat.meta_data_filter) if chat.meta_data_filter is not None else {},
        status=chat.status,
        dataset_ids=[dataset_id for dataset_id, _ in bindings],
        kb_names=[dataset_name for _, dataset_name in bindings],
        nickname=nickname,
        tenant_avatar=tenant_avatar,
        create_time=chat.create_time,
        update_time=chat.update_time,
        llm_name=chat.llm_id,
    )


async def list_dataset_records(
    session: AsyncSession, names: Mapping[str, Sequence[tuple[str, str]]]
) -> dict[str, tuple[DatasetRecord, ...]]:
    """Rekordy datasetów per czat dla listy czatów (E2-2b C2); nieistniejące pomijane."""
    records: dict[str, tuple[DatasetRecord, ...]] = {}
    for chat_id, bindings in names.items():
        found: list[DatasetRecord] = []
        for dataset_id, _ in bindings:
            record = await datasets_repo.get_record(session, dataset_id)
            if record is not None:
                found.append(record)
        records[chat_id] = tuple(found)
    return records
