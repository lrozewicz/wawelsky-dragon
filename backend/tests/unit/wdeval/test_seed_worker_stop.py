"""running_worker: zatrzymanie workera po terminie nie przykrywa oryginalnego wyjątku."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from wdeval import seed


class _FakeContainer:
    def __init__(self) -> None:
        self.closed = False

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


class _StuckWorker:
    async def run(self, stop: asyncio.Event) -> None:
        await asyncio.sleep(3600)  # ignoruje stop, jak worker w długim zadaniu


@pytest.mark.asyncio
async def test_original_error_survives_worker_stop_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    container = _FakeContainer()
    monkeypatch.setattr(
        seed, "create_worker", lambda settings, executor: (container, _StuckWorker())
    )
    monkeypatch.setattr(seed, "_WORKER_STOP_TIMEOUT_S", 0.05)
    settings: Any = object()

    with pytest.raises(seed.SeedTimeout):
        async with seed.running_worker(settings):
            raise seed.SeedTimeout("eval-fast: parsowanie nie skończyło się")

    assert container.closed
