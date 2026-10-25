"""Testy jednostkowe handlera ``parse_document`` i składania workera (brief T8, wymaganie 5)."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.config import Settings
from app.worker import main as worker_main
from app.worker.handlers.parse_document import make_handler
from app.worker.main import HANDLERS, create_worker, make_parse_pool

# katalog backend/ — korzeń importu ``app`` dla podprocesu
BACKEND_DIR = Path(__file__).resolve().parents[3]


def _ctx_with_run_parse_task() -> tuple[SimpleNamespace, AsyncMock]:
    """Kontekst z atrapą DocumentIngestService.run_parse_task (SimpleNamespace/AsyncMock)."""
    run_parse_task = AsyncMock()
    container = SimpleNamespace(ingest=SimpleNamespace(run_parse_task=run_parse_task))
    return SimpleNamespace(container=container), run_parse_task


async def test_make_handler_delegates_with_executor() -> None:
    """make_handler(sentinel) → run_parse_task(task, ctx, executor=sentinel) (wymaganie 2)."""
    sentinel = object()
    ctx, run_parse_task = _ctx_with_run_parse_task()
    task = SimpleNamespace(id="t1")

    await make_handler(sentinel)(task, ctx)

    run_parse_task.assert_awaited_once_with(task, ctx, executor=sentinel)


async def test_production_handler_passes_none() -> None:
    """HANDLERS["parse_document"] → run_parse_task z executor=None (kontrakt C8)."""
    ctx, run_parse_task = _ctx_with_run_parse_task()
    task = SimpleNamespace(id="t1")

    await HANDLERS["parse_document"](task, ctx)

    run_parse_task.assert_awaited_once_with(task, ctx, executor=None)


def test_handlers_registry_has_parse_document() -> None:
    """Rejestr produkcyjny ma dokładnie klucz parse_document (kontrakt C8)."""
    assert set(HANDLERS) == {"parse_document"}


def test_parse_pool_size_comes_from_settings(monkeypatch) -> None:
    """Rozmiar puli procesów workera = `Settings.parse_processes` (kontrakt C4)."""
    captured: dict[str, int] = {}

    class _FakePool:
        def __init__(self, *, max_workers: int, mp_context: object) -> None:
            captured["max_workers"] = max_workers

    monkeypatch.setattr(worker_main, "ProcessPoolExecutor", _FakePool)
    make_parse_pool(Settings(env="test", parse_processes=3))
    assert captured["max_workers"] == 3  # noqa: PLR2004 — wartość z ustawień w teście


async def test_create_worker_with_executor_overrides_handler() -> None:
    """create_worker(executor=obj) → inny handler parse_document, związany z pulą (wym. 3)."""
    executor = object()
    container, worker = create_worker(Settings(env="test"), executor=executor)
    assert container.started is False
    assert worker._handlers["parse_document"] is not HANDLERS["parse_document"]

    ctx, run_parse_task = _ctx_with_run_parse_task()
    task = SimpleNamespace(id="t1")

    await worker._handlers["parse_document"](task, ctx)

    run_parse_task.assert_awaited_once_with(task, ctx, executor=executor)


def test_worker_main_import_does_not_pull_parsing() -> None:
    """Import app.worker.main nie ładuje app.parsing ani stempel w podprocesie (wymaganie 4)."""
    code = (
        "import app.worker.main, sys;"
        "print('app.parsing.registry' in sys.modules);"
        "print('stempel' in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603 — stały interpreter testowy, stały kod
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=BACKEND_DIR,
        check=True,
    )
    assert result.stdout.splitlines() == ["False", "False"]
