"""Testy jednostkowe przeglądu ``build_outline`` (K21 §2 p. 4).

Pętla bez bazy i ``sleep`` (atrapa ``sweep_once``); ``sweep_once`` na atrapach repozytoriów
i kolejki — bez MariaDB. Semantyka na prawdziwej bazie: ``tests/integration/ingest``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.worker import outline_sweep
from app.worker.outline_sweep import SWEEP_BATCH, outline_sweep_loop, sweep_once

_DISABLED = 0
_ACTIVE_ID = "a" * 32
_NEW_ID = "b" * 32


class _FakeTransaction:
    """Atrapa transakcji sesji (async context manager)."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    """Atrapa sesji: ``sweep_once`` nie wykonuje SQL (repozytoria podmienione)."""

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSessionmaker:
    """Atrapa async_sessionmaker: każde wywołanie zwraca tę samą sesję."""

    def __call__(self) -> _FakeSession:
        return _FakeSession()


class _FakeQueue:
    """Atrapa ``DbTaskQueue``: rejestruje ``NewTask`` przekazane do ``enqueue``."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.enqueued: list[Any] = []

    async def enqueue(self, task: Any) -> str:
        self.enqueued.append(task)
        return "id"


def _container(*, outline_sweep_s: int = 600) -> Container:
    """Kontener testowy z atrapą sesji (bez startu, bez I/O)."""
    container = Container(Settings(env="test", outline_sweep_s=outline_sweep_s))
    container.sessionmaker = cast(async_sessionmaker[AsyncSession], _FakeSessionmaker())
    return container


def _patch_repos(monkeypatch: pytest.MonkeyPatch, ids: list[str], active: set[str]) -> None:
    """Podmienia repozytoria przeglądu na zwracające ``ids`` i ``active``."""

    async def _ids(_session: Any, _limit: int) -> list[str]:
        return list(ids)

    async def _active(_session: Any, _document_ids: Any) -> set[str]:
        return set(active)

    monkeypatch.setattr(outline_sweep.document_profiles, "ids_without_profile", _ids)
    monkeypatch.setattr(outline_sweep.task_lookup, "active_build_outline_documents", _active)


async def test_sweep_once_enqueues_background_tasks_and_skips_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Porcja bez profilu → zadania ``build_outline`` (priorytet -1); duplikat pominięty."""
    _patch_repos(monkeypatch, [_ACTIVE_ID, _NEW_ID], active={_ACTIVE_ID})
    queue = _FakeQueue()
    monkeypatch.setattr(outline_sweep, "DbTaskQueue", lambda *_a, **_k: queue)

    enqueued = await sweep_once(_container())

    assert enqueued == 1
    task = queue.enqueued[0]
    assert task.task_type == "build_outline"
    assert task.payload == {"document_id": _NEW_ID}
    assert task.document_id == _NEW_ID
    assert task.priority == -1


async def test_sweep_once_uses_batch_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rozmiar porcji przeglądu to dosłownie 50 z K21 §2 p. 4 (nie stała z kodu)."""
    captured: list[int] = []

    async def _ids(_session: Any, limit: int) -> list[str]:
        captured.append(limit)
        return []

    async def _active(_session: Any, _document_ids: Any) -> set[str]:
        return set()

    monkeypatch.setattr(outline_sweep.document_profiles, "ids_without_profile", _ids)
    monkeypatch.setattr(outline_sweep.task_lookup, "active_build_outline_documents", _active)
    monkeypatch.setattr(outline_sweep, "DbTaskQueue", lambda *_a, **_k: _FakeQueue())

    await sweep_once(_container())

    assert captured == [50]
    assert SWEEP_BATCH == 50  # noqa: PLR2004 — stała modułu zgodna z kontraktem


async def test_loop_runs_first_pass_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Przegląd przy starcie i wyjście na ``stop`` — bez realnego czekania (§2 p. 4)."""
    passes: list[int] = []
    stop = asyncio.Event()

    async def _fake_sweep(_container: Container) -> int:
        passes.append(1)
        stop.set()
        return 0

    monkeypatch.setattr(outline_sweep, "sweep_once", _fake_sweep)
    await asyncio.wait_for(outline_sweep_loop(_container(), stop, interval_s=3600), timeout=2)

    assert passes == [1]


async def test_loop_repeats_until_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kolejne przebiegi co ``interval_s`` aż do ``stop`` (§2 p. 4)."""
    passes: list[int] = []
    stop = asyncio.Event()

    async def _fake_sweep(_container: Container) -> int:
        passes.append(1)
        if len(passes) == 3:  # noqa: PLR2004 — trzy przebiegi wystarczą za dowód pętli
            stop.set()
        return 0

    monkeypatch.setattr(outline_sweep, "sweep_once", _fake_sweep)
    await asyncio.wait_for(outline_sweep_loop(_container(), stop, interval_s=0.01), timeout=2)

    assert len(passes) == 3  # noqa: PLR2004 — dokładnie trzy przebiegi


async def test_loop_survives_a_failing_pass(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Błąd przebiegu nie zabija przeglądu — kolejny idzie dalej (§2 p. 4)."""
    passes: list[int] = []
    stop = asyncio.Event()

    async def _fake_sweep(_container: Container) -> int:
        passes.append(1)
        if len(passes) == 1:
            raise RuntimeError("MariiDB niedostępna")
        stop.set()
        return 0

    monkeypatch.setattr(outline_sweep, "sweep_once", _fake_sweep)
    with caplog.at_level(logging.ERROR, logger="app.worker"):
        await asyncio.wait_for(outline_sweep_loop(_container(), stop, interval_s=0.01), timeout=2)

    assert len(passes) == 2  # noqa: PLR2004 — przebieg błędu + przebieg kończący
    assert "outline sweep pass failed" in caplog.text


async def test_loop_disabled_when_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """``WD_OUTLINE_SWEEP_S=0`` wyłącza przegląd — ``sweep_once`` nie jest wołane (§2 p. 4)."""
    called = False

    async def _fake_sweep(_container: Container) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(outline_sweep, "sweep_once", _fake_sweep)
    stop = asyncio.Event()

    await asyncio.wait_for(
        outline_sweep_loop(_container(outline_sweep_s=_DISABLED), stop), timeout=2
    )

    assert called is False
