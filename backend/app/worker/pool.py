"""Pula procesów parsowania odtwarzana po ``BrokenProcessPool`` (WP E5-H2 §1, kontrakt C6/C9).

Proces potomny konwersji padający (np. OOM) psuje ``ProcessPoolExecutor`` trwale — każdy
kolejny ``submit`` kończyłby się ``BrokenProcessPool``, mimo że zasoby są znowu wolne.
``ParsePool`` wykrywa to po wyniku future (bez prywatnego ``_broken``) i przy następnym
``submit`` stawia nową pulę z fabryki; dokument, którego konwersja padła, dostaje od
``convert_document`` czytelny ``TransientError`` (``POOL_BROKEN_MESSAGE``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, TypeVar

logger = logging.getLogger("app.worker")

_T = TypeVar("_T")


class ParsePool(Executor):
    """``Executor`` otaczający ``ProcessPoolExecutor``, odtwarzany po ``BrokenProcessPool``."""

    def __init__(self, factory: Callable[[], ProcessPoolExecutor]) -> None:
        self._factory = factory
        self._executor = factory()
        self._broken = False
        self._generation = 0

    @property
    def generation(self) -> int:
        """0 na starcie, +1 po każdym odtworzeniu puli."""
        return self._generation

    def _recreate(self) -> ProcessPoolExecutor:
        """Nowa pula z fabryki; starą zamyka bez czekania (jej procesy już nie żyją)."""
        stale = self._executor
        self._executor = self._factory()
        self._generation += 1
        self._broken = False
        logger.warning("parse pool recreated", extra={"generation": self._generation})
        stale.shutdown(wait=False, cancel_futures=True)
        return self._executor

    def _on_done(self, future: Future[Any]) -> None:
        """Callback future: ``BrokenProcessPool`` oznacza bieżącą pulę do wymiany."""
        if future.cancelled():
            return
        if isinstance(future.exception(), BrokenProcessPool):
            self._broken = True

    def submit(self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> Future[_T]:
        """Zleca zadanie; zepsuta pula → nowa (jedna próba też przy wyjątku z ``submit``)."""
        if self._broken:
            self._recreate()
        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except BrokenProcessPool:
            # Pula padła między callbackiem a ``submit`` — jedna próba na nowej puli.
            future = self._recreate().submit(fn, *args, **kwargs)
        future.add_done_callback(self._on_done)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        """Zamyka bieżącą pulę (``_amain`` woła z ``wait=True``, kontrakt C9)."""
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __getattr__(self, name: str) -> Any:
        """Deleguje atrybuty puli (np. ``_mp_context`` czytany przez testy, DEC-002).

        Wywoływane tylko dla nazw, których ``ParsePool`` sam nie definiuje; brak puli
        (przed ``__init__``) → ``AttributeError`` zamiast nieskończonej rekurencji.
        """
        executor = self.__dict__.get("_executor")
        if executor is None:
            raise AttributeError(name)
        return getattr(executor, name)
