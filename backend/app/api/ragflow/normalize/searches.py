"""Normalizacja wejścia wyszukiwarek (CONTRACT E4-4a §D5) — 101 jak upstream ``validate_request``.

Port ``search_api.py`` v0.27.2: brak wymaganego klucza ciała daje 101 z komunikatem
``required argument are missing: <pola>; `` (``validate_request``, ``api_utils.py:157``),
a walidację wartości nazwy i ``search_config`` prowadzi serwis (→ 102).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.api.ragflow.pagination import parse_page
from app.core.errors import ValidationFailed

# Biała lista sortowań (upstream ``SearchService.get_by_tenant_ids``); nieznane → ``create_time``.
_ORDERBY_ALLOWED = frozenset({"create_time", "update_time", "name"})
_DEFAULT_ORDERBY = "create_time"


@dataclass(frozen=True)
class SearchCreateInput:
    """Ciało POST /searches (§D5): ``name`` surowe (waliduje serwis), reszta opcjonalna."""

    name: Any
    description: str
    avatar: str | None
    search_config: dict[str, Any] | None


@dataclass(frozen=True)
class SearchUpdateInput:
    """Ciało PUT /searches/{id} (§D5): ``name`` i ``search_config`` surowe (waliduje serwis)."""

    name: Any
    search_config: Any
    description: str | None
    avatar: str | None


@dataclass(frozen=True)
class SearchListQuery:
    """Parametry GET /searches (§D5)."""

    keywords: str
    orderby: str
    desc: bool
    page: int
    page_size: int
    owner_ids: list[str]


def _optional_str(body: Mapping[str, object], key: str) -> str | None:
    """Wartość klucza jako łańcuch; brak, ``null`` i inny typ → ``None``."""
    value = body.get(key)
    return value if isinstance(value, str) else None


def _require_present(body: Mapping[str, object], fields: Sequence[str]) -> None:
    """Brak klucza w ciele → 101 (port ``validate_request``; złoto searches--07)."""
    missing = [field for field in fields if field not in body]
    if missing:
        raise ValidationFailed(f"required argument are missing: {','.join(missing)}; ")


def parse_search_create(body: Mapping[str, object]) -> SearchCreateInput:
    """Ciało POST /searches → SearchCreateInput; brak ``name`` → 101 (złoto searches--07).

    Upstream nie sprawdza typu ``search_config`` w ``POST``; nie-obiekt traktujemy jak brak
    klucza (serwis wstawia wtedy wartości domyślne z §D2).
    """
    _require_present(body, ("name",))
    config = body.get("search_config")
    return SearchCreateInput(
        name=body["name"],
        description=_optional_str(body, "description") or "",
        avatar=_optional_str(body, "avatar"),
        search_config=config if isinstance(config, dict) else None,
    )


def parse_search_update(body: Mapping[str, object]) -> SearchUpdateInput:
    """Ciało PUT /searches/{id} → SearchUpdateInput; brak klucza → 101 (upstream PUT)."""
    _require_present(body, ("name", "search_config"))
    return SearchUpdateInput(
        name=body["name"],
        search_config=body["search_config"],
        description=_optional_str(body, "description"),
        avatar=_optional_str(body, "avatar"),
    )


def parse_search_list(
    query: Mapping[str, str], owner_ids: Sequence[str], *, max_size: int
) -> SearchListQuery:
    """Parametry GET /searches → SearchListQuery (§D5).

    ``owner_ids`` to parametr powtarzalny (brane poza tą mapą przez ``getlist``). Upstream
    nie waliduje ``orderby`` — nieznana wartość schodzi do ``create_time``, więc ``parse_page``
    dostaje zapytanie bez tego klucza (jego domyślna wartość to właśnie ``create_time``).
    """
    orderby = query.get("orderby") or _DEFAULT_ORDERBY
    if orderby not in _ORDERBY_ALLOWED:
        orderby = _DEFAULT_ORDERBY
    page = parse_page(
        {key: value for key, value in query.items() if key != "orderby"}, max_size=max_size
    )
    return SearchListQuery(
        keywords=query.get("keywords", ""),
        orderby=orderby,
        desc=page.desc,
        page=page.page,
        page_size=page.page_size,
        owner_ids=list(owner_ids),
    )
