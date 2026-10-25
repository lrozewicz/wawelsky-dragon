"""Prezentacja czatów (CONTRACT C5) — klucze dokładnie jak złoto v0.27.2.

Profil ``ragflow_0_24`` deleguje do ``present/chats_v024.py`` (CONTRACT E2-2b C2);
kształt v0.27.2 bez zmian.
"""

from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.present.chats_v024 import (
    chat_detail_v024,
    chat_list_item_v024,
    chat_list_v024,
)
from app.api.ragflow.present.common import date, ts
from app.services.chats import ChatView


def chat_detail(v: ChatView, profile: CompatProfile) -> dict[str, Any]:
    """Szczegół czatu: klucze złota chats/chat_session--01.json; w 0.24 kształt v0.24."""
    if profile == "ragflow_0_24":
        return chat_detail_v024(v)
    return {
        "create_date": date(v.create_time),
        "create_time": ts(v.create_time),
        "dataset_ids": list(v.dataset_ids),
        "description": v.description,
        "do_refer": v.do_refer,
        "icon": v.icon,
        "id": v.id,
        "kb_names": list(v.kb_names),
        "language": v.language,
        "llm_id": v.llm_id,
        "llm_setting": dict(v.llm_setting),
        "meta_data_filter": dict(v.meta_data_filter),
        "name": v.name,
        "prompt_config": dict(v.prompt_config),
        "prompt_type": v.prompt_type,
        "rerank_candidates_count": v.rerank_candidates_count,
        "rerank_id": v.rerank_id,
        "similarity_threshold": v.similarity_threshold,
        "status": v.status,
        "tenant_id": v.tenant_id,
        "tenant_llm_id": v.tenant_llm_id,
        "tenant_rerank_id": v.tenant_rerank_id,
        "top_k": v.top_k,
        "top_n": v.top_n,
        "update_date": date(v.update_time),
        "update_time": ts(v.update_time),
        "vector_similarity_weight": v.vector_similarity_weight,
    }


def chat_list_item(v: ChatView, profile: CompatProfile) -> dict[str, Any]:
    """Wiersz listy: klucze złota chats/chat_session--02.json (bez pól szczegółu)."""
    if profile == "ragflow_0_24":
        return chat_list_item_v024(v)
    return {
        "create_time": ts(v.create_time),
        "dataset_ids": list(v.dataset_ids),
        "description": v.description,
        "do_refer": v.do_refer,
        "icon": v.icon,
        "id": v.id,
        "kb_names": list(v.kb_names),
        "language": v.language,
        "llm_id": v.llm_id,
        "llm_setting": dict(v.llm_setting),
        "name": v.name,
        "nickname": v.nickname,
        "prompt_config": dict(v.prompt_config),
        "prompt_type": v.prompt_type,
        "rerank_candidates_count": v.rerank_candidates_count,
        "rerank_id": v.rerank_id,
        "similarity_threshold": v.similarity_threshold,
        "status": v.status,
        "tenant_avatar": v.tenant_avatar,
        "tenant_id": v.tenant_id,
        "top_k": v.top_k,
        "top_n": v.top_n,
        "update_time": ts(v.update_time),
        "vector_similarity_weight": v.vector_similarity_weight,
    }


def chat_list(
    views: list[ChatView], total: int, profile: CompatProfile
) -> dict[str, Any] | list[dict[str, Any]]:
    """Lista czatów: w 0.27 koperta {"chats": [...], "total": total} (C5), w 0.24 lista (C2)."""
    if profile == "ragflow_0_24":
        return chat_list_v024(views)
    return {"chats": [chat_list_item(v, profile) for v in views], "total": total}
