"""Prezentacja odpowiedzi OpenAI-compat (brief OC p. 3; 02-api §8.2/§9, złoto openai_compat).

Kształt jest OpenAI, nie kopertą RAGFlow: JSON ``chat.completion`` (upstream :380-420)
i ramki ``chat.completion.chunk`` zakończone ``data:[DONE]`` (upstream :102-170).
``usage`` liczone jest z tekstu (tiktoken cl100k_base — ``num_tokens_from_string``
u upstreamu), nie ze zużycia bramki LLM.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.api.ragflow.sse import encode_frame
from app.domain.chat.events import (
    ChatEvent,
    ErrorEvent,
    ThinkEnd,
    ThinkStart,
)
from app.domain.chat.events import Final as FinalEvent
from app.llm.tokens import count_tokens

SSE_MEDIA_TYPE = "text/event-stream; charset=utf-8"
# Terminator strumienia OpenAI (upstream :170) — bez spacji, jak nagrany w złocie.
DONE_FRAME = b"data:[DONE]\n\n"
ERROR_PREFIX = "**ERROR**: "


@dataclass(frozen=True)
class CompletionMeta:
    """Identyfikatory odpowiedzi OpenAI: id, model i czas (upstream :262, :270, :398)."""

    id: str
    model: str
    created: int


def completion_id(chat_id: str) -> str:
    """Id odpowiedzi OpenAI (upstream :262): ``chatcmpl-<chat_id>``."""
    return f"chatcmpl-{chat_id}"


def _content_text(content: object) -> str:
    """Treść wiadomości jako tekst (upstream ``_normalize_message_content``, :189-210)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text", "")
            if text is not None:
                parts.append(str(text))
    return "\n".join(parts)


def request_tokens(messages: Sequence[Mapping[str, Any]]) -> tuple[str, int]:
    """(prompt, reasoning_tokens): treść ostatniej wiadomości i suma tokenów wszystkich.

    Port upstream :255-256 (``prompt`` i ``context_token_used``) — liczone po normalizacji
    wiadomości, przed odsianiem ``system``/pierwszego ``assistant``.
    """
    texts = [_content_text(message.get("content")) for message in messages]
    return texts[-1], sum(count_tokens(text) for text in texts)


def _usage(prompt_tokens: int, completion_tokens: int) -> dict[str, int]:
    """Liczniki w kolejności kluczy upstreamu (:150-153, :398-403)."""
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def completion_json(
    *,
    meta: CompletionMeta,
    content: str,
    prompt: str,
    reasoning_tokens: int,
) -> dict[str, Any]:
    """Ciało HTTP 200 ``chat.completion`` (upstream :380-420) — klucze w kolejności złota."""
    prompt_tokens = count_tokens(prompt)
    completion_tokens = count_tokens(content)
    usage: dict[str, Any] = _usage(prompt_tokens, completion_tokens)
    usage["completion_tokens_details"] = {
        "reasoning_tokens": reasoning_tokens,
        "accepted_prediction_tokens": completion_tokens,
        "rejected_prediction_tokens": 0,
    }
    return {
        "id": meta.id,
        "object": "chat.completion",
        "created": meta.created,
        "model": meta.model,
        "usage": usage,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "logprobs": None,
                "finish_reason": "stop",
                "index": 0,
            }
        ],
    }


def _chunk_frame(
    meta: CompletionMeta,
    delta: dict[str, Any],
    *,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
) -> bytes:
    """Ramka ``chat.completion.chunk`` (upstream :74-99) — klucze w kolejności złota."""
    return encode_frame(
        {
            "id": meta.id,
            "choices": [
                {
                    "delta": delta,
                    "finish_reason": finish_reason,
                    "index": 0,
                    "logprobs": None,
                }
            ],
            "created": meta.created,
            "model": meta.model,
            "object": "chat.completion.chunk",
            "system_fingerprint": "",
            "usage": usage,
        }
    )


def _delta(content: str | None, reasoning: str | None) -> dict[str, Any]:
    """Delta ramki OpenAI — pełny zestaw kluczy w kolejności upstreamu (:79-92)."""
    return {
        "content": content,
        "role": "assistant",
        "function_call": None,
        "tool_calls": None,
        "reasoning_content": reasoning,
    }


async def sse_chunks(
    events: AsyncIterator[ChatEvent], *, meta: CompletionMeta, prompt: str
) -> AsyncIterator[bytes]:
    """Strumień SSE OpenAI: delty treści, ramka końcowa z ``usage``, ``data:[DONE]``.

    Port upstream :102-170: ``start_to_think``/``end_to_think`` przestawiają tylko tryb
    (bez ramki), delta myślenia idzie w ``reasoning_content``, pusta delta bez ramki,
    ``final`` pomijany (brak ``extra_body.reference``), błąd strumienia → treść
    ``**ERROR**: …`` (:144-146).
    """
    in_think = False
    token_used = 0
    async for event in events:
        if isinstance(event, ThinkStart | ThinkEnd):
            in_think = not isinstance(event, ThinkEnd)
            continue
        if isinstance(event, FinalEvent):
            continue
        if isinstance(event, ErrorEvent):
            text = ERROR_PREFIX + event.message
            token_used += count_tokens(text)
            yield _chunk_frame(meta, _delta(text, None))
            break
        if not event.text:  # pusta delta bez ramki (upstream :136-138)
            continue
        token_used += count_tokens(event.text)
        if in_think:  # myślenie idzie w ``reasoning_content`` (upstream :139-142)
            yield _chunk_frame(meta, _delta(None, event.text))
        else:
            yield _chunk_frame(meta, _delta(event.text, None))
    usage = _usage(count_tokens(prompt), token_used)
    yield _chunk_frame(meta, _delta(None, None), finish_reason="stop", usage=usage)
    yield DONE_FRAME
