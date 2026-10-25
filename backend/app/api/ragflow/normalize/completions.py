"""Normalizacja żądania completions (CONTRACT C4 p. 1-6; port chat_api.py v0.27.2).

Czysty moduł: mapowanie body → CompletionRequest bez I/O.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from app.api.ragflow.compat import CompatProfile
from app.core.errors import ValidationFailed
from app.services.chat import CompletionRequest


@dataclass(frozen=True)
class CompletionCall:
    """Żądanie completions po normalizacji: req + flagi obsługiwane przez trasę (C4)."""

    req: CompletionRequest  # z app.services.chat
    stream: bool
    legacy: bool


def _messages(body: Mapping[str, object]) -> tuple[Mapping[str, Any], ...]:
    """Port _normalize_completion_messages (chat_api.py:242-293); błędy → ValidationFailed."""
    raw = body.get("messages")
    if raw is None:
        question = body.get("question")
        if question is None:
            raise ValidationFailed("required argument are missing: messages")
        raw = [{"role": "user", "content": question}]
    if not isinstance(raw, list) or not raw:
        raise ValidationFailed("`messages` must be a non-empty list.")
    for message in raw:
        if not isinstance(message, dict):
            raise ValidationFailed("Every item in `messages` must be an object.")
        if "role" not in message or "content" not in message:
            raise ValidationFailed("Every item in `messages` must include `role` and `content`.")
    filtered: list[Mapping[str, Any]] = []
    for message in raw:
        if message["role"] == "system":
            continue
        if message["role"] == "assistant" and not filtered:
            continue
        filtered.append(message)
    if not filtered:
        raise ValidationFailed("`messages` must contain a user message.")
    if filtered[-1]["role"] != "user":
        raise ValidationFailed("The last message must be from user.")
    return tuple(filtered)


def _flag(body: Mapping[str, object], *names: str, default: bool) -> bool:
    """Port _get_bool_request_flag (chat_api.py:231-239): pierwsza obecna nazwa wygrywa."""
    for name in names:
        if name not in body:
            continue
        value = body[name]
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    return default


# Port _generation_params.py: klucze parametrów i ich przełączniki „enabled”.
_GENERATION_KEYS: Final[tuple[str, ...]] = (
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "max_tokens",
)
_GENERATION_ENABLED: Final[dict[str, tuple[str, ...]]] = {
    "temperature": ("temperatureEnabled", "temperature_enabled"),
    "top_p": ("topPEnabled", "top_p_enabled"),
    "frequency_penalty": ("frequencyPenaltyEnabled", "frequency_penalty_enabled"),
    "presence_penalty": ("presencePenaltyEnabled", "presence_penalty_enabled"),
    "max_tokens": ("maxTokensEnabled", "max_tokens_enabled"),
}


def _generation_config(body: Mapping[str, object]) -> dict[str, Any] | None:
    """Port extract_generation_config (_generation_params.py); pusty wynik → None."""
    config = {
        key: body[key]
        for key in _GENERATION_KEYS
        if key in body
        and body[key] is not None
        and not any(body.get(enabled) is False for enabled in _GENERATION_ENABLED[key])
    }
    return config or None


def _doc_ids(value: object) -> tuple[str, ...] | None:
    """C4 p. 5: łańcuch CSV / lista → krotka niepustych; pusta krotka lub inny typ → None."""
    if isinstance(value, str):
        ids = tuple(x for x in value.split(",") if x)
    elif isinstance(value, list):
        ids = tuple(str(x) for x in value if x)
    else:
        return None
    return ids or None


def openai_request_error(body: Mapping[str, object]) -> str | None:
    """Walidacja kształtu żądania trasy OpenAI-compat; komunikat błędu albo ``None``.

    Port ``openai_api.py:243-262`` (v0.27.2) i ``sdk/session.py:270-287`` (v0.24.0) — kolejność
    i semantyka dosłownie: ``extra_body``/``reference_metadata`` sprawdzane prawdziwościowo
    (pusty słownik jest OK), ``fields`` tylko gdy nie jest ``None``, ``messages`` niepuste,
    a ostatnia wiadomość z rolą ``user``. Trasa woła to przed sprawdzeniem czatu (DEC-092 p. 2);
    treści wiadomości nie normalizujemy (``_normalize_openai_messages`` — brak w porcie).
    """
    raw_extra = body.get("extra_body")
    if raw_extra and not isinstance(raw_extra, dict):
        return "extra_body must be an object."
    extra_body: Mapping[str, object] = raw_extra if isinstance(raw_extra, dict) else {}
    raw_metadata = extra_body.get("reference_metadata")
    if raw_metadata and not isinstance(raw_metadata, dict):
        return "reference_metadata must be an object."
    reference_metadata: Mapping[str, object] = (
        raw_metadata if isinstance(raw_metadata, dict) else {}
    )
    fields = reference_metadata.get("fields")
    if fields is not None and not isinstance(fields, list):
        return "reference_metadata.fields must be an array."
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return "You have to provide messages."
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return "The last content of this conversation is not from user."
    return None


def parse_completion(
    body: Mapping[str, object],
    profile: CompatProfile,
    *,
    path_chat_id: str | None,
    stream_default: bool = True,
) -> CompletionCall:
    """Body completions → CompletionCall (C4 p. 1-6); ``profile`` zarezerwowany dla E2-2.

    ``stream_default`` to wartość przy braku klucza ``stream``: true na trasach natywnych
    (K4 §1); trasa OpenAI-compat podaje ją z profilu — false w v0.27 (upstream
    ``openai_api.py:333``), true w v0.24 (upstream v0.24 czyta flagę wprost).
    """
    # Ciało wygrywa z ścieżką, pusto → None (chat_api.py:1256-1257).
    chat_id = str(body.get("chat_id") or path_chat_id or "") or None
    raw_session = body.get("session_id") or body.get("conversation_id")
    raw_meta = body.get("metadata_condition")
    metadata = cast("Mapping[str, Any]", raw_meta) if isinstance(raw_meta, dict) else None
    return CompletionCall(
        req=CompletionRequest(
            chat_id=chat_id,
            session_id=str(raw_session) if raw_session else None,
            messages=_messages(body),
            llm_id=str(body["llm_id"]) if body.get("llm_id") else None,
            llm_setting=_generation_config(body),
            quote=_flag(body, "quote", default=True),
            reasoning=_flag(body, "reasoning", default=False),
            pass_all_history_messages=_flag(
                body, "pass_all_history_messages", "pass_all_history", default=False
            ),
            store_history_messages=_flag(
                body, "store_history_messages", "store_history", default=True
            ),
            doc_ids=_doc_ids(body.get("doc_ids")),
            metadata_condition=metadata,
            user_id=None,
            source="api",
        ),
        # R8: łańcuch "false" jest truthy, jak upstream
        stream=bool(body.get("stream", stream_default)),
        legacy=_flag(body, "legacy", default=False),
    )
