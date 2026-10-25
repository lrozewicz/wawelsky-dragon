"""Prezentacja wyniku completions (CONTRACT C5; K4 §1.7)."""

from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.sse import chat_reference, sanitize
from app.services.chat import CompletionResult


def completion_data(r: CompletionResult, profile: CompatProfile) -> dict[str, Any]:
    """Koperta ``data`` JSON (K4 §1.7): kolejność kluczy złota; NaN/±Inf → None.

    ``chat_id`` tylko gdy znany i profil ≠ ``ragflow_0_24`` (CONTRACT E2-2b C0 p. 5);
    ``thinking`` tylko gdy niepuste.
    """
    data: dict[str, Any] = {
        "answer": r.answer,
        "reference": chat_reference(r.reference, profile),
        "prompt": r.prompt,
        "created_at": r.created_at,
        "audio_binary": None,
        "id": r.ids.message_id,
        "session_id": r.ids.session_id,
    }
    if r.ids.chat_id is not None and profile != "ragflow_0_24":
        data["chat_id"] = r.ids.chat_id
    if r.thinking:
        data["thinking"] = r.thinking
    cleaned: dict[str, Any] = sanitize(data)
    return cleaned
