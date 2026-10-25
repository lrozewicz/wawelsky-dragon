"""Normalizacja wejścia czatów (CONTRACT C4) — kolejność sprawdzeń 1-6 dosłownie."""

from collections.abc import Mapping
from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.normalize.chats_v024 import to_canonical
from app.api.ragflow.normalize.common import Command, parse_model
from app.api.ragflow.pagination import parse_page
from app.core.errors import Conflict, ValidationFailed
from app.services.chats import CHAT_INPUT_KEYS, ChatInput, ChatListQuery

# Limity nazwy z upstream _validate_name (chat_api.py:150-162).
_NAME_MAX_BYTES = 255

# Dozwolone sortowania listy czatów (chat_api.py:518-521).
_ORDERBY_ALLOWED = frozenset({"create_time", "update_time", "name"})

# Klucze pól prostych p. 6 — ciała zgodne z modelem _ScalarFields.
_SCALAR_KEYS = (
    "icon",
    "description",
    "similarity_threshold",
    "vector_similarity_weight",
    "top_n",
    "top_k",
    "rerank_candidates_count",
    "prompt_type",
    "language",
    "meta_data_filter",
)


class _ScalarFields(Command):
    """Pola proste żądania czatu (C4 p. 6): liczby, łańcuchy i meta_data_filter."""

    similarity_threshold: float | None = None
    vector_similarity_weight: float | None = None
    top_n: int | None = None
    top_k: int | None = None
    rerank_candidates_count: int | None = None
    icon: str | None = None
    description: str | None = None
    language: str | None = None
    prompt_type: str | None = None
    meta_data_filter: dict[str, Any] | None = None


def _reject_tenant_id(body: Mapping[str, object]) -> None:
    """Sprawdzenie 1: tenant_id nie może być podany (chat_api.py:428)."""
    if body.get("tenant_id"):
        raise Conflict("`tenant_id` must not be provided")


def _validate_name(name: object, *, required: bool) -> str | None:
    """Port _validate_name (chat_api.py:150-162); None = klucz pominięty (PATCH name null)."""
    if name is None:
        if required:
            raise Conflict("`name` is required")
        return None
    if not isinstance(name, str):
        raise Conflict("chat name must be a string")
    name = name.strip()
    if not name:
        raise Conflict("`name` is required" if required else "`name` cannot be empty")
    if len(name.encode("utf-8")) > _NAME_MAX_BYTES:
        length = len(name.encode("utf-8"))
        raise Conflict(f"chat name length is {length} which is larger than {_NAME_MAX_BYTES}")
    return name


def _check_prompt_parameters(prompt_config: Mapping[str, object]) -> None:
    """Duplikaty parameters[].key (port _validate_prompt_parameters, chat_api.py:172-187)."""
    parameters = prompt_config.get("parameters")
    if not isinstance(parameters, list):
        return
    keys: list[object] = []
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        key = parameter.get("key")
        if key is None:
            continue
        if key in keys:
            raise Conflict(f"`parameters` contains duplicate key: {key}")
        keys.append(key)


def _normalize(body: Mapping[str, object], fields: dict[str, Any]) -> None:
    """Sprawdzenia 3-6 i zebranie kluczy obecnych w body ∩ CHAT_INPUT_KEYS (C4)."""
    if (
        "dataset_ids" in body
        and body["dataset_ids"] is not None
        and not isinstance(body["dataset_ids"], list)
    ):
        raise Conflict("`dataset_ids` should be a list.")
    if "llm_setting" in body and not isinstance(body["llm_setting"], dict):
        raise Conflict("`llm_setting` should be an object.")
    if "prompt_config" in body:
        if not isinstance(body["prompt_config"], dict):
            raise Conflict("`prompt_config` should be an object.")
        _check_prompt_parameters(body["prompt_config"])
    for field in ("llm_id", "rerank_id"):
        if field in body and body[field] is not None and not isinstance(body[field], str):
            raise Conflict(f"`{field}` must be a string")
    parsed = parse_model(_ScalarFields, body)
    for key in CHAT_INPUT_KEYS:
        if key == "name" or key not in body:
            continue
        if key == "dataset_ids":
            fields[key] = [] if body[key] is None else body[key]
        elif key in _SCALAR_KEYS:
            fields[key] = getattr(parsed, key)
        else:
            fields[key] = body[key]


def parse_chat_create(body: Mapping[str, object], profile: CompatProfile) -> ChatInput:
    """Ciało POST /chats → ChatInput (C4, sprawdzenia 1-6); w profilu 0.24 wejście po shimie."""
    if profile == "ragflow_0_24":
        body = to_canonical(body)
    _reject_tenant_id(body)
    name = _validate_name(body.get("name"), required=True)
    fields: dict[str, Any] = {"name": name}
    _normalize(body, fields)
    return ChatInput(fields=fields)


def parse_chat_update(
    body: Mapping[str, object], profile: CompatProfile, *, patch: bool
) -> ChatInput:
    """Ciało PUT/PATCH /chats/{id} → ChatInput; name tylko gdy klucz obecny (C4)."""
    if profile == "ragflow_0_24":
        body = to_canonical(body)
    _reject_tenant_id(body)
    fields: dict[str, Any] = {}
    if "name" in body:
        name = _validate_name(body["name"], required=not patch)
        if name is not None:
            fields["name"] = name
    _normalize(body, fields)
    return ChatInput(fields=fields)


def parse_chat_list(
    query: Mapping[str, str], profile: CompatProfile, *, max_size: int
) -> ChatListQuery:
    """Parametry GET /chats → ChatListQuery; orderby sprawdzone przed parse_page (C4)."""
    del profile
    orderby = query.get("orderby", "create_time")
    if orderby not in _ORDERBY_ALLOWED:
        raise ValidationFailed(f"invalid orderby field: {orderby}")
    page = parse_page(query, max_size=max_size, orderby_allowed=_ORDERBY_ALLOWED)
    chat_id = query.get("id") or None
    name = query.get("name") or None
    keywords = "" if (chat_id or name) else query.get("keywords", "")
    return ChatListQuery(
        page=page.page,
        page_size=page.page_size,
        orderby=page.orderby,
        desc=page.desc,
        chat_id=chat_id,
        name=name,
        keywords=keywords,
    )


def parse_delete_ids(body: Mapping[str, object]) -> tuple[list[str] | None, bool]:
    """Ciało DELETE /chats → (ids, delete_all); ids tylko z listy, delete_all = is True (C4)."""
    ids = body.get("ids")
    normalized = [str(value) for value in ids] if isinstance(ids, list) else None
    return normalized, body.get("delete_all") is True


def parse_recommendation(body: Mapping[str, object]) -> str:
    """Ciało POST /chat/recommendation → pytanie (C4, api_utils.py:176 dosłownie)."""
    question = body.get("question")
    if not isinstance(question, str):
        raise ValidationFailed("required argument are missing: question; ")
    return question


def parse_recommendation_search_id(body: Mapping[str, object]) -> str | None:
    """``search_id`` z ciała recommendation; fałszywa wartość → ``None`` (T4, DEC-176).

    Upstream ``chat_api.py:1207``: ``req.get("search_id", "")`` pod ``if search_id:`` —
    brak, ``None`` i ``""`` znaczą „bez wyszukiwarki”, bez własnego komunikatu walidacji.
    """
    search_id = body.get("search_id")
    return str(search_id) if search_id else None
