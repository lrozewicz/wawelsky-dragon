"""Zdarzenia czatu (K4 §3.1, CONTRACT C1) — czyste dataclassy, bez I/O."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.errors import WDError


@dataclass(frozen=True)
class ThinkStart:
    """Początek bloku myślenia modelu."""


@dataclass(frozen=True)
class ThinkDelta:
    """Delta treści myślenia."""

    text: str


@dataclass(frozen=True)
class ThinkEnd:
    """Koniec bloku myślenia modelu."""


@dataclass(frozen=True)
class AnswerDelta:
    """Delta odpowiedzi modelu (złożenie delt = surowa odpowiedź, K4 §1.3)."""

    text: str


@dataclass(frozen=True)
class Final:
    """Ramka finalna odpowiedzi.

    ``answer``: ``""`` w ścieżce zwykłej, ``E`` w ścieżce empty_response (§1.4).
    ``reference``: R z §1.2, gotowe do JSON. ``prompt``: P już po WD_EXPOSE_PROMPT.
    ``created_at``: ``None`` w ścieżce empty_response (brak klucza w ramce).
    ``final_answer``: odpowiedź po finalize_answer, bez ``<think>`` (OpenAI final_content,
    complete_once). ``thinking``: treść myślenia albo ``None``. ``usage``:
    (prompt_tokens, completion_tokens) ze StreamEnd. ``empty``: True = ścieżka §1.4
    (koder wybiera układ kluczy §1.4).
    """

    answer: str
    reference: Mapping[str, Any]
    prompt: str
    created_at: float | None
    final_answer: str
    thinking: str | None
    usage: tuple[int, int]
    empty: bool


@dataclass(frozen=True)
class ErrorEvent:
    """Błąd w strumieniu (K4 §1.5)."""

    message: str


@dataclass(frozen=True)
class StreamIds:
    """Identyfikatory ramek: id wiadomości asystenta, sesja (lub None),
    chat_id (None → brak klucza) — K4 §3.2.
    """

    message_id: str
    session_id: str | None
    chat_id: str | None


ChatEvent = ThinkStart | ThinkDelta | ThinkEnd | AnswerDelta | Final | ErrorEvent


def error_message(exc: BaseException) -> str:
    """K4 §1.5: WDError → exc.message (komunikat K3); inny wyjątek → "Internal server error"."""
    if isinstance(exc, WDError):
        return exc.message
    return "Internal server error"
