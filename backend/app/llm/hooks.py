"""Hooki zadania w bramce LLM (kontrakt C1, DEC-293 p.4).

Bramka jest współdzielona w kontenerze między slotami, więc stan per zadanie
trzymamy w ``ContextVar`` (kopiowanym przy ``create_task``). Bez zainstalowanych
hooków bramka działa jak dotąd (API czatu itd.) — log i przerywanie są pomijane.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class TaskLlmHooks:
    """Hooki bieżącego zadania parsowania (kontrakt C1)."""

    log: Callable[[str], Awaitable[None]]  # wpis do logu zadania (bieżący procent, bez zmiany)
    check_cancel: Callable[[], Awaitable[None]]  # TaskContext.check_cancel (rzuca TaskCancelled)
    vision_cache_hits: int = 0  # wywołania vision(cache=True) trafione w cache
    vision_model_calls: int = 0  # wywołania vision(cache=True) wysłane do modelu


_HOOKS: ContextVar[TaskLlmHooks | None] = ContextVar("llm_task_hooks", default=None)


def install_hooks(hooks: TaskLlmHooks) -> Token[TaskLlmHooks | None]:
    """Instaluje hooki w bieżącym kontekście; zwraca token do ``reset_hooks`` (C1)."""
    return _HOOKS.set(hooks)


def reset_hooks(token: Token[TaskLlmHooks | None]) -> None:
    """Przywraca stan sprzed ``install_hooks`` (``ContextVar`` token z C1)."""
    _HOOKS.reset(token)


def current_hooks() -> TaskLlmHooks | None:
    """Hooki bieżącego zadania albo ``None`` (bramka bez kontekstu zadania — C1)."""
    return _HOOKS.get()
