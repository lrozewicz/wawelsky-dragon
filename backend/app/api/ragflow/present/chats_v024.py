"""Prezentacja czatów w kształcie v0.24.0 (CONTRACT C2) — klucze dokładnie jak złoto.

Wejście: ``ChatView`` po kanonicznym tłumaczeniu (T1); wyjście: obiekty v0.24
(``git show v0.24.0:api/apps/sdk/chat.py``, funkcje ``create``/``list_chat``).
"""

from typing import Any

from app.api.ragflow.present.common import date, ts
from app.api.ragflow.present.datasets import dataset
from app.services.chats import ChatView

# Pięć ustawień modelu w ``llm`` (C0 p. 2); ``model_name`` dokładane osobno, na końcu.
LLM_SETTING_KEYS = (
    "frequency_penalty",
    "max_tokens",
    "presence_penalty",
    "temperature",
    "top_p",
)

# Domyślne ``llm_setting`` upstreamu v0.24 (``api/db/db_models.py:942``, ``Dialog``): czyta je
# złoto ``chats/chat_session--01/02.json``, a WD zapisuje wiersz z pustym ``llm_setting``
# (w 0.27.2 upstream też wysyła ``{}`` — dekret TL z 2026-09-29, wyjątek od zakazu dotykania
# ``present/**`` w briefie T5). Wartości z ``llm_setting`` mają pierwszeństwo.
_DEFAULT_LLM_SETTING_V024: dict[str, Any] = {
    "temperature": 0.1,
    "top_p": 0.3,
    "frequency_penalty": 0.7,
    "presence_penalty": 0.4,
    "max_tokens": 512,
}


def _llm(v: ChatView) -> dict[str, Any]:
    """``llm`` v0.24 (C0 p. 2): domyślne ustawienia dopełnione ``llm_setting`` + ``model_name``."""
    settings = {**_DEFAULT_LLM_SETTING_V024, **v.llm_setting}
    llm: dict[str, Any] = {key: settings[key] for key in LLM_SETTING_KEYS if key in settings}
    llm["model_name"] = v.llm_name
    return llm


def _prompt(v: ChatView) -> dict[str, Any]:
    """``prompt`` v0.24 (C0 p. 2): 11 kluczy; brak w ``prompt_config`` → wartości ze złota.

    ``keywords_similarity_weight`` = dopełnienie ``vector_similarity_weight`` (C0 p. 2).
    """
    pc = v.prompt_config
    return {
        "empty_response": pc.get("empty_response", ""),
        "keywords_similarity_weight": round(1 - v.vector_similarity_weight, 6),
        "opener": pc.get("prologue", ""),
        "prompt": pc.get("system", ""),
        "refine_multiturn": pc.get("refine_multiturn", True),
        "rerank_model": v.rerank_id,
        "show_quote": pc.get("quote", True),
        "similarity_threshold": v.similarity_threshold,
        "top_n": v.top_n,
        "tts": pc.get("tts", False),
        "variables": pc.get("parameters") or [],
    }


def chat_detail_v024(v: ChatView) -> dict[str, Any]:
    """Szczegół czatu v0.24 (POST/PUT/GET): klucze złota ``chats/chat_session--01.json``."""
    return {
        "avatar": v.icon,
        "create_date": date(v.create_time),
        "create_time": ts(v.create_time),
        "dataset_ids": list(v.dataset_ids),
        "description": v.description,
        "do_refer": v.do_refer,
        "id": v.id,
        "language": v.language,
        "llm": _llm(v),
        "meta_data_filter": dict(v.meta_data_filter),
        "name": v.name,
        "prompt": _prompt(v),
        "prompt_type": v.prompt_type,
        "status": v.status,
        "tenant_id": v.tenant_id,
        "update_date": date(v.update_time),
        "update_time": ts(v.update_time),
    }


def chat_list_item_v024(v: ChatView) -> dict[str, Any]:
    """Wiersz listy (GET /chats): złoto ``chats/chat_session--02.json`` (bez ``dataset_ids``)."""
    return {
        "avatar": v.icon,
        "create_date": date(v.create_time),
        "create_time": ts(v.create_time),
        "datasets": [dataset(rec, "ragflow_0_24") for rec in v.datasets],
        "description": v.description,
        "do_refer": v.do_refer,
        "id": v.id,
        "language": v.language,
        "llm": _llm(v),
        "meta_data_filter": dict(v.meta_data_filter),
        "name": v.name,
        "prompt": _prompt(v),
        "prompt_type": v.prompt_type,
        "status": v.status,
        "tenant_id": v.tenant_id,
        "top_k": v.top_k,
        "update_date": date(v.update_time),
        "update_time": ts(v.update_time),
    }


def chat_list_v024(views: list[ChatView]) -> list[dict[str, Any]]:
    """Lista czatów v0.24: zwykła lista elementów, bez koperty ``{"chats", "total"}`` (C2)."""
    return [chat_list_item_v024(v) for v in views]
