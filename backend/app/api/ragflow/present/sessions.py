"""Prezentacja sesji (CONTRACT C5) — klucze dokładnie jak złoto v0.27.2.

Profil ``ragflow_0_24`` prezentuje kształt v0.24.0 (CONTRACT E2-2b C0 p. 4, C3);
kształt v0.27.2 bez zmian.
"""

from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.present.common import date, ts
from app.api.ragflow.present.references import chunk_reference_v024
from app.services.sessions import MessageView, SessionView

# Puste reference wiadomości assistant (C5): kształt upstream (chat_api.py:150+).
_EMPTY_REFERENCE: dict[str, Any] = {"chunks": [], "doc_aggs": []}


def _message(m: MessageView) -> dict[str, Any]:
    """Kształt wiadomości wg roli i seq (C5): prologue bez id, user bez created_at.

    ``thumbup``/``feedback`` dokładane tylko, gdy ustawione (złoto chat_extras--12).
    """
    if m.seq == 0 and m.role == "assistant":
        return {"role": m.role, "content": m.content}
    if m.role == "user":
        return {"role": m.role, "content": m.content, "id": m.id}
    message: dict[str, Any] = {
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at,
        "id": m.id,
    }
    if m.thumbup is not None:
        message["thumbup"] = m.thumbup
    if m.feedback is not None:
        message["feedback"] = m.feedback
    return message


def _reference(v: SessionView) -> list[dict[str, Any]]:
    """Reference wiadomości assistant z seq > 0 (C5); None → puste chunks/doc_aggs."""
    return [
        m.reference if m.reference is not None else dict(_EMPTY_REFERENCE)
        for m in v.messages
        if m.role == "assistant" and m.seq > 0
    ]


def _messages_v024(v: SessionView) -> list[dict[str, Any]]:
    """Wiadomości sesji v0.24 (C3): kształt v0.27 + ``reference`` przy odpowiedziach asystenta.

    Port ``list_session`` v0.24: n-ta niepusta referencja (kolejność ``reference``) trafia do
    n-tej wiadomości roli ≠ user, przy czym prolog (pierwsza wiadomość) nie jest celem —
    referencja z pary pytanie/odpowiedź ląduje przy odpowiedzi, nie przy prologu (brief T3 p. 3).
    """
    references = [m.reference for m in v.messages if m.reference]
    messages: list[dict[str, Any]] = []
    ref_index = 0
    for index, m in enumerate(v.messages):
        message = _message(m)
        if index > 0 and m.role != "user" and ref_index < len(references):
            chunks = references[ref_index].get("chunks") or ()
            message["reference"] = [chunk_reference_v024(chunk) for chunk in chunks]
            ref_index += 1
        messages.append(message)
    return messages


def session_detail(
    v: SessionView, profile: CompatProfile, *, with_avatar: bool = False
) -> dict[str, Any]:
    """Szczegół sesji: klucze złota chats___sessions/chat_session--03.json; avatar wg GET.

    Profil 0.24: klucze C0 p. 4 (bez ``reference`` na górze i bez ``avatar``) i referencje
    przy wiadomościach asystenta (C3).
    """
    if profile == "ragflow_0_24":
        return {
            "chat_id": v.chat_id,
            "create_date": date(v.create_time),
            "create_time": ts(v.create_time),
            "id": v.id,
            "messages": _messages_v024(v),
            "name": v.name,
            "update_date": date(v.update_time),
            "update_time": ts(v.update_time),
            "user_id": v.user_id,
        }
    detail: dict[str, Any] = {
        "chat_id": v.chat_id,
        "create_date": date(v.create_time),
        "create_time": ts(v.create_time),
        "id": v.id,
        "messages": [_message(m) for m in v.messages],
        "name": v.name,
        "reference": _reference(v),
        "update_date": date(v.update_time),
        "update_time": ts(v.update_time),
        "user_id": v.user_id,
    }
    if with_avatar:
        detail["avatar"] = v.avatar
    return detail
