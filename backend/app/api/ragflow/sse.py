"""Koder SSE natywny (K4 §1.1-§1.6, CONTRACT C3) — bajtowo zgodny ze złotem v0.27.2.

Profil ``ragflow_0_24`` (CONTRACT E2-2b C0 p. 5) dokłada odmienną kopertę, ogon i terminator
oraz pojedynczą ramkę ``empty_response``; ``profile`` wchodzi tylko w adnotacji (moduł zostaje
czysty w runtime).

Czysty moduł: wyłącznie stdlib + ``app.domain.chat.events`` (bez ``app.db``/``app.services``).
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import AsyncIterator, Callable, Mapping
from typing import TYPE_CHECKING, Any, Final

from app.domain.chat.events import (
    AnswerDelta,
    ChatEvent,
    ErrorEvent,
    StreamIds,
    ThinkDelta,
    ThinkEnd,
    ThinkStart,
    error_message,
)
from app.domain.chat.events import Final as FinalEvent

if TYPE_CHECKING:  # profil wchodzi wyłącznie w adnotacji — moduł nie importuje warstwy usług
    from app.api.ragflow.compat import CompatProfile

logger = logging.getLogger(__name__)

TERMINATOR: Final[bytes] = b'data:{"code":0,"message":"","data":true}\n\n'
TERMINATOR_V024: Final[bytes] = b'data:{"code":0,"data":true}\n\n'

# Klucze chunku referencji nieobecne w v0.24 (upstream chunks_format, rag/prompts/generator.py:40).
_V024_DROPPED_CHUNK_KEYS: Final[frozenset[str]] = frozenset({"row_id", "document_metadata"})


def sanitize(obj: Any) -> Any:
    """float NaN/±Inf → None, rekurencyjnie w dict/list (port _sanitize_json_floats, K4 §1.1)."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


def encode_frame(obj: Any) -> bytes:
    """Ramka K4 §1.1: b"data:" + zwarty JSON (UTF-8, ensure_ascii=False) + b"\\n\\n"."""
    return (
        b"data:"
        + json.dumps(sanitize(obj), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n\n"
    )


def chat_reference(reference: Mapping[str, Any], profile: CompatProfile) -> dict[str, Any]:
    """Referencja czatu wg profilu: v0.24 bez ``row_id``/``document_metadata`` w chunkach.

    Współdzielona przez prezentację JSON (``completion_data``) i ramkę SSE — tak jak ``sanitize``.
    """
    if profile != "ragflow_0_24":
        return dict(reference)
    return {
        **reference,
        "chunks": [
            {key: value for key, value in chunk.items() if key not in _V024_DROPPED_CHUNK_KEYS}
            for chunk in reference.get("chunks") or ()
        ],
    }


def ask_reference(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Referencja ramki ``/sessions/ask`` v0.24 (C0 p. 6): ``total/chunks/doc_aggs``.

    Chunk bez ``row_id``/``document_metadata`` (klucze spoza v0.24, jak ``chat_reference``),
    ``doc_aggs`` tylko ``doc_name/doc_id/count`` — dosłownie ze złota ``chat_extras--18.sse``.
    """
    return {
        "total": reference.get("total", 0),
        "chunks": [
            {key: value for key, value in chunk.items() if key not in _V024_DROPPED_CHUNK_KEYS}
            for chunk in reference.get("chunks") or ()
        ],
        "doc_aggs": [
            {"doc_name": agg["doc_name"], "doc_id": agg["doc_id"], "count": agg["count"]}
            for agg in reference.get("doc_aggs") or ()
        ],
    }


def search_reference(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Referencja ramki completion wyszukiwarki: kształt v0.27 (złoto ``searches--21.sse``).

    Odmiennie od ``ask_reference`` (v0.24 ``/sessions/ask``) NIE usuwa ``row_id``/
    ``document_metadata`` — zachowuje się jak ``chat_reference`` dla profilu v0.27.
    Uzupełnia brakujące ``total``/``doc_aggs`` (przy 0 trafieniach ``chat_pipeline`` oddaje
    samo ``{"chunks": []}``), w kolejności kluczy złota: ``total``, ``chunks``, ``doc_aggs``.
    """
    rest = {
        key: value for key, value in reference.items() if key not in ("total", "chunks", "doc_aggs")
    }
    return {
        "total": reference.get("total", 0),
        "chunks": reference.get("chunks", []),
        "doc_aggs": reference.get("doc_aggs", []),
        **rest,
    }


def ask_frames(
    ev: ChatEvent,
    reference: Callable[[Mapping[str, Any]], dict[str, Any]] = ask_reference,
) -> list[bytes]:
    """Ramki ``/sessions/ask`` v0.24 (C0 p. 6): koperta z ``"message":""``, bez ids/promptu.

    Delta: ``{"answer":<tekst>,"reference":{},"final":false}``. Finalna: ``answer=""``,
    pełna ``reference``, ``final=true``. Błąd: ``code 500`` + ``**ERROR**`` (jak ``ask_about``).
    ``reference`` dobiera kształt referencji — domyślnie v0.24 ``/sessions/ask``.
    """
    if isinstance(ev, ThinkStart | ThinkEnd):
        flag = "start_to_think" if isinstance(ev, ThinkStart) else "end_to_think"
        data: dict[str, Any] = {"answer": "", "reference": {}, "final": False, flag: True}
    elif isinstance(ev, ThinkDelta | AnswerDelta):
        data = {"answer": ev.text, "reference": {}, "final": False}
    elif isinstance(ev, FinalEvent):
        data = {"answer": "", "reference": reference(ev.reference), "final": True}
    else:
        # ErrorEvent (K4 §1.5): koperta z code 500 — jak w ask_about, bez pozostałych kluczy.
        return [
            encode_frame(
                {
                    "code": 500,
                    "message": ev.message,
                    "data": {"answer": "**ERROR**: " + ev.message, "reference": []},
                }
            )
        ]
    return [encode_frame({"code": 0, "message": "", "data": data})]


def _tail(ids: StreamIds, profile: CompatProfile) -> dict[str, Any]:
    """Pola wspólne kończące każde <D>: id, session_id (+ chat_id: v0.27, gdy niepuste)."""
    tail: dict[str, Any] = {"id": ids.message_id, "session_id": ids.session_id}
    if ids.chat_id is not None and profile != "ragflow_0_24":
        tail["chat_id"] = ids.chat_id
    return tail


def _envelope(data: dict[str, Any], profile: CompatProfile) -> dict[str, Any]:
    """Koperta K4 §1.1 każdej ramki danych: v0.27 z ``message``, v0.24 bez (C0 p. 5)."""
    if profile == "ragflow_0_24":
        return {"code": 0, "data": data}
    return {"code": 0, "message": "", "data": data}


def native_frames(
    ev: ChatEvent, ids: StreamIds, profile: CompatProfile = "ragflow_0_27"
) -> list[bytes]:
    """Ramki <D> jednego zdarzenia bez terminatora (K4 §1.2/§1.4/§1.5); profil wg C0 p. 5."""
    tail = _tail(ids, profile)
    body: dict[str, Any]
    if isinstance(ev, ThinkStart):
        body = {
            "answer": "",
            "reference": {"chunks": []},
            "audio_binary": None,
            "final": False,
            "start_to_think": True,
            **tail,
        }
    elif isinstance(ev, ThinkEnd):
        body = {
            "answer": "",
            "reference": {"chunks": []},
            "audio_binary": None,
            "final": False,
            "end_to_think": True,
            **tail,
        }
    elif isinstance(ev, ThinkDelta | AnswerDelta):
        body = {
            "answer": ev.text,
            "reference": {"chunks": []},
            "audio_binary": None,
            "final": False,
            **tail,
        }
    elif isinstance(ev, FinalEvent):
        if not ev.empty:
            body = {
                "answer": ev.answer,
                "reference": chat_reference(ev.reference, profile),
                "prompt": ev.prompt,
                "created_at": ev.created_at,
                "final": True,
                "audio_binary": None,
                **tail,
            }
            return [encode_frame(_envelope(body, profile))]
        # Ścieżka empty_response (K4 §1.4): v0.27 dwie ramki, v0.24 tylko finalna (C0 p. 5).
        final_frame = encode_frame(
            _envelope(
                {
                    "answer": ev.answer,
                    "reference": chat_reference(ev.reference, profile),
                    "prompt": ev.prompt,
                    "audio_binary": None,
                    "final": True,
                    **tail,
                },
                profile,
            )
        )
        if profile == "ragflow_0_24":
            return [final_frame]
        return [
            encode_frame(
                _envelope(
                    {
                        "answer": ev.answer,
                        "reference": {"chunks": []},
                        "prompt": "",
                        "audio_binary": None,
                        "final": False,
                        **tail,
                    },
                    profile,
                )
            ),
            final_frame,
        ]
    else:
        # ErrorEvent (K4 §1.5): koperta z code 500 — tylko tu, bez ids (v0.24 tak samo).
        return [
            encode_frame(
                {
                    "code": 500,
                    "message": ev.message,
                    "data": {"answer": "**ERROR**: " + ev.message, "reference": []},
                }
            )
        ]
    return [encode_frame(_envelope(body, profile))]


def _legacy_frames(
    ev: ChatEvent, ids: StreamIds, acc: str, profile: CompatProfile
) -> tuple[list[bytes], str]:
    """Ramki trybu legacy (K4 §1.6): answer = tekst skumulowany, bez kluczy flag.

    Zwraca (ramki, nowy skumulowany tekst). Pusta delta — brak ramki. Final(empty=True)
    i ErrorEvent — jak nie-legacy.
    """
    tail = _tail(ids, profile)
    if isinstance(ev, FinalEvent | ErrorEvent):
        if isinstance(ev, FinalEvent) and not ev.empty:
            return (
                [
                    encode_frame(
                        _envelope(
                            {
                                "answer": acc,
                                "reference": chat_reference(ev.reference, profile),
                                "prompt": ev.prompt,
                                "created_at": ev.created_at,
                                "final": True,
                                "audio_binary": None,
                                **tail,
                            },
                            profile,
                        )
                    )
                ],
                acc,
            )
        return native_frames(ev, ids, profile), acc
    if isinstance(ev, ThinkDelta | AnswerDelta):
        if not ev.text:
            return [], acc
        acc += ev.text
    elif isinstance(ev, ThinkStart):
        acc += "<think>"
    else:  # ThinkEnd — ostatni wariant ChatEvent (Final i ErrorEvent obsłużone wyżej)
        acc += "</think>"
    frame = encode_frame(
        _envelope(
            {
                "answer": acc,
                "reference": {"chunks": []},
                "audio_binary": None,
                "final": False,
                **tail,
            },
            profile,
        )
    )
    return [frame], acc


async def sse_native(
    events: AsyncIterator[ChatEvent],
    ids: StreamIds,
    *,
    legacy: bool = False,
    profile: CompatProfile = "ragflow_0_27",
) -> AsyncIterator[bytes]:
    """Strumień SSE (K4 §3.2): ramki zdarzeń, wyjątek → ramka §1.5, zawsze na końcu TERMINATOR."""
    acc = ""
    terminator = TERMINATOR_V024 if profile == "ragflow_0_24" else TERMINATOR
    try:
        async for ev in events:
            if legacy:
                frames, acc = _legacy_frames(ev, ids, acc, profile)
            else:
                frames = native_frames(ev, ids, profile)
            for frame in frames:
                yield frame
    except Exception as exc:  # błąd strumienia zamieniamy na ramkę K4 §1.5
        logger.exception("SSE stream error")
        for frame in native_frames(ErrorEvent(error_message(exc)), ids, profile):
            yield frame
    yield terminator


async def sse_ask(
    events: AsyncIterator[ChatEvent],
    *,
    reference: Callable[[Mapping[str, Any]], dict[str, Any]] = ask_reference,
) -> AsyncIterator[bytes]:
    """Strumień SSE ``/sessions/ask``: ramki ``ask_frames`` i terminator v0.27 (C0 p. 6).

    Terminator ``/sessions/ask`` ma ``"message":""`` (upstream ``ask_about``), więc równa się
    ``TERMINATOR`` profilu v0.27 — nie ``TERMINATOR_V024``. ``reference`` pozwala wołającemu
    (completion wyszukiwarki, §D7) wybrać kształt referencji bez zmiany zachowania
    ``/sessions/ask``.
    """
    try:
        async for ev in events:
            for frame in ask_frames(ev, reference):
                yield frame
    except Exception as exc:  # błąd strumienia → ramka §1.5 (upstream: try wokół stream())
        logger.exception("ask SSE stream error")
        for frame in ask_frames(ErrorEvent(error_message(exc))):
            yield frame
    yield TERMINATOR
