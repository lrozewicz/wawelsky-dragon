"""Normalizacja wejścia sesji (CONTRACT C4) — komunikaty dosłownie z chat_api.py v0.27.2."""

from collections.abc import Mapping

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.pagination import parse_page
from app.core.errors import Conflict, ValidationFailed
from app.services.sessions import SessionListQuery

# Dopuszczalne sortowania listy sesji (chat_api.py:880).
_ORDERBY_ALLOWED = frozenset({"create_time", "update_time", "name"})

# Domyślne sortowanie listy sesji zależne od profilu (A4, decyzja WP E2-5): konto
# serwisowe 0.24 chce ostatnio używane rozmowy na górze (``update_time``), upstream
# 0.27 zostaje przy ``create_time``.
_DEFAULT_ORDERBY: dict[CompatProfile, str] = {
    "ragflow_0_24": "update_time",
    "ragflow_0_27": "create_time",
}


def parse_session_create(body: Mapping[str, object]) -> str:
    """Ciało POST /chats/{chat_id}/sessions → nazwa sesji (C4, chat_api.py:845)."""
    name = body.get("name", "New session")
    if not isinstance(name, str) or not name.strip():
        raise Conflict("`name` can not be empty")
    return name.strip()[:255]


def parse_session_user_v024(body: Mapping[str, object]) -> str:
    """``user_id`` z ciała sesji w 0.24 (upstream ``create``: ``req.get("user_id", "")``)."""
    user_id = body.get("user_id", "")
    return user_id if isinstance(user_id, str) else ""


def parse_session_rename(body: Mapping[str, object]) -> str | None:
    """Ciało PATCH/PUT sesji → nowa nazwa albo None (C4, chat_api.py:927-933)."""
    if "message" in body or "messages" in body:
        raise Conflict("`messages` cannot be changed")
    if "reference" in body:
        raise Conflict("`reference` cannot be changed")
    name = body.get("name")
    if name is None:
        return None
    if not isinstance(name, str) or not name.strip():
        raise Conflict("`name` can not be empty")
    return name.strip()[:255]


def parse_message_feedback(body: Mapping[str, object]) -> tuple[bool, str | None]:
    """Ciało PUT feedbacku → (thumbup, feedback) (C4, chat_api.py:1034-1040).

    ``thumbup`` musi być typu bool (liczba 1/0 nie przechodzi); ``feedback`` niebędący
    napisem jest pomijany. Odmowa to ``get_data_error_result`` upstream (chat_api.py:1038),
    czyli code 102 — stąd ``Conflict`` (K11 §10c p. 9), nie ``ValidationFailed`` (101).
    """
    thumbup = body.get("thumbup")
    if not isinstance(thumbup, bool):
        raise Conflict("thumbup must be a boolean")
    feedback = body.get("feedback")
    return thumbup, feedback if isinstance(feedback, str) else None


def parse_session_list(
    query: Mapping[str, str], profile: CompatProfile, *, max_size: int
) -> SessionListQuery:
    """Parametry GET /chats/{chat_id}/sessions → SessionListQuery (C4, chat_api.py:880).

    Domyślne ``orderby`` zależy od profilu zgodności (A4): 0.24 → ``update_time``,
    0.27 → ``create_time``. Jawne ``orderby`` w zapytaniu wygrywa z domyślnym;
    ``desc`` bez wartości zostaje ``true`` (C5).
    """
    default_orderby = _DEFAULT_ORDERBY[profile]
    orderby = query.get("orderby", default_orderby)
    if orderby not in _ORDERBY_ALLOWED:
        raise ValidationFailed(f"invalid orderby field: {orderby}")
    page = parse_page(
        query,
        max_size=max_size,
        orderby_allowed=_ORDERBY_ALLOWED,
        default_orderby=default_orderby,
        allow_zero_size=True,
    )
    return SessionListQuery(
        page=page.page,
        page_size=page.page_size,
        orderby=page.orderby,
        desc=page.desc,
        session_id=query.get("id") or None,
        name=query.get("name") or None,
        user_id=query.get("user_id") or None,
    )
