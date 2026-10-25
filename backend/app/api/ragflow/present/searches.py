"""Prezentacja wyszukiwarek (CONTRACT E4-4a §D5) — klucze dokładnie jak złoto v0.27.2.

``search_config`` w odpowiedzi to zapisany obiekt plus ``kb_ids`` złożone z wiązań
``search_datasets`` w kolejności ``ordinal`` (§D1); ``create_date``/``update_date``
formatowane jak w istniejących prezenterach (``present/common.py``).
"""

from typing import Any

from app.api.ragflow.present.common import date, ts
from app.services.searches import SearchView


def _search_config(view: SearchView) -> dict[str, Any]:
    """Zapisany ``search_config`` + ``kb_ids`` z wiązań (§D1, §D5)."""
    return {**view.row.search_config, "kb_ids": list(view.kb_ids)}


def search_create_result(search_id: str) -> dict[str, Any]:
    """Data ``searches_create`` (złoto searches--05): ``{"search_id": …}``."""
    return {"search_id": search_id}


def search_list_item(view: SearchView) -> dict[str, Any]:
    """Wiersz listy (złoto searches--09): bez ``search_config``, z danymi właściciela."""
    row = view.row
    return {
        "avatar": row.avatar,
        "create_time": ts(row.create_time),
        "created_by": row.created_by,
        "description": row.description,
        "id": row.id,
        "name": row.name,
        "nickname": view.owner_nickname,
        "status": row.status,
        "tenant_avatar": view.tenant_avatar,
        "tenant_id": row.tenant_id,
        "update_time": ts(row.update_time),
    }


def search_list(views: list[SearchView], total: int) -> dict[str, Any]:
    """Data ``searches_list`` (złoto searches--09): ``{"search_apps": [...], "total": n}``."""
    return {"search_apps": [search_list_item(view) for view in views], "total": total}


def search_detail(view: SearchView) -> dict[str, Any]:
    """Data ``searches_get`` (złoto searches--14): bez ``create_*``/``status``/``nickname``."""
    row = view.row
    return {
        "avatar": row.avatar,
        "created_by": row.created_by,
        "description": row.description,
        "id": row.id,
        "name": row.name,
        "search_config": _search_config(view),
        "tenant_id": row.tenant_id,
        "update_time": ts(row.update_time),
    }


def search_full(view: SearchView) -> dict[str, Any]:
    """Data ``searches_update`` (złoto searches--15): pełny wiersz z datami."""
    row = view.row
    return {
        "avatar": row.avatar,
        "create_date": date(row.create_time),
        "create_time": ts(row.create_time),
        "created_by": row.created_by,
        "description": row.description,
        "id": row.id,
        "name": row.name,
        "search_config": _search_config(view),
        "status": row.status,
        "tenant_id": row.tenant_id,
        "update_date": date(row.update_time),
        "update_time": ts(row.update_time),
    }
