"""Odtwarzanie puli parsowania po ``BrokenProcessPool`` (WP E5-H2, T1).

Testy na PRAWDZIWEJ puli ``ProcessPoolExecutor`` (forkserver): proces potomny ginie
natychmiast (``os._exit``, symulacja OOM), więc pula faktycznie się psuje. Funkcje-stuby
są modułowe, bo trafiają do procesu potomnego przez pickle (fork/forkserver).
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from app.parsing.types import ConvertOptions
from app.services import ingest_convert
from app.services.ingest_convert import convert_document
from app.worker.errors import POOL_BROKEN_MESSAGE, TransientError
from app.worker.pool import ParsePool


def _crash(*_args: object, **_kwargs: object) -> None:
    """Stub konwertera: proces potomny kończy się natychmiast (padnięcie/OOM)."""
    os._exit(1)


def _square(value: int) -> int:
    """Zwykłe zadanie dla sprawdzenia, że odtworzona pula liczy dalej."""
    return value * value


def _factory() -> ProcessPoolExecutor:
    """Fabryka puli jak produkcyjna: forkserver, jeden proces potomny."""
    return ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("forkserver"))


async def test_submit_recreates_pool_after_broken_process() -> None:
    """Pad procesu potomnego → następny submit na tej SAMEJ instancji liczy (generation == 1)."""
    pool = ParsePool(_factory)
    try:
        loop = asyncio.get_running_loop()
        with pytest.raises(BrokenProcessPool):
            await loop.run_in_executor(pool, _crash)
        assert pool.generation == 0
        value = 3
        assert await loop.run_in_executor(pool, _square, value) == value * value
        assert pool.generation == 1
    finally:
        pool.shutdown()


async def test_convert_document_raises_transient_on_broken_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Konwerter padający w puli → ``TransientError`` z dokładnym ``POOL_BROKEN_MESSAGE``."""
    source = tmp_path / "doc.txt"
    source.write_text("treść dokumentu", encoding="utf-8")
    monkeypatch.setattr(ingest_convert, "convert", _crash)
    pool = ParsePool(_factory)
    try:
        with pytest.raises(TransientError) as excinfo:
            await convert_document(
                source, "txt", ConvertOptions(), executor=pool, ocr=None, vision=None
            )
        assert str(excinfo.value) == POOL_BROKEN_MESSAGE
    finally:
        pool.shutdown()
