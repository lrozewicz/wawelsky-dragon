"""Testy jednostkowe wejścia workera — składanie bez I/O (brief T5, wymaganie 3; E4-1c T2)."""

import asyncio
import logging

import pytest

from app.core.config import Settings
from app.core.container import Container
from app.integrations.config import IntegrationsConfig
from app.worker import main as worker_main
from app.worker.kb_handlers import KB_HANDLERS
from app.worker.loop import Worker
from app.worker.main import HANDLERS, create_worker, make_parse_pool, start_scheduler


def test_create_worker_returns_container_and_worker() -> None:
    """create_worker(Settings(env="test")) → krotka (Container, Worker), bez startu (brief T5)."""
    container, worker = create_worker(Settings(env="test"))
    assert isinstance(container, Container)
    assert isinstance(worker, Worker)
    assert container.started is False


def test_handlers_registry_empty() -> None:
    """Rejestr produkcyjny handlerów ma wyłącznie parse_document (kontrakt C8, brief T8)."""
    assert set(HANDLERS) == {"parse_document"}


def test_create_worker_merges_kb_handlers() -> None:
    """``create_worker`` scala ``KB_HANDLERS`` — eksport/import obok parsera (E7-1f §6)."""
    _, worker = create_worker(Settings(env="test"))
    assert set(KB_HANDLERS) == {"export_dataset", "import_dataset"}
    assert set(worker._handlers) >= {"parse_document", "integration_sync", *KB_HANDLERS}


def test_kb_handlers_are_real_functions() -> None:
    """Oba handlery ``KB_HANDLERS`` to wdrożone funkcje z modułów ``handlers/*`` (E7-1a/E7-1b)."""
    assert set(KB_HANDLERS) == {"export_dataset", "import_dataset"}
    assert KB_HANDLERS["export_dataset"].__module__ == "app.worker.handlers.export_dataset"
    assert KB_HANDLERS["import_dataset"].__module__ == "app.worker.handlers.import_dataset"


def test_create_worker_reads_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_worker() bez argumentu czyta Settings() ze zmiennych WD_* (brief T5)."""
    monkeypatch.setenv("WD_ENV", "test")
    container, worker = create_worker()
    assert isinstance(container, Container)
    assert isinstance(worker, Worker)
    assert container.started is False


def test_make_parse_pool_uses_forkserver() -> None:
    """Pula parsowania startuje przez forkserver (DEC-002).

    Fork z procesu wielowątkowego grozi zakleszczeniem.
    """
    pool = make_parse_pool(Settings(env="test"))
    assert pool._mp_context.get_start_method() == "forkserver"
    pool.shutdown()


def test_create_worker_engine_gets_config_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_worker czyta IntegrationsConfig z Settings — tick trafia do silnika (E4-1c T2)."""
    captured: list[IntegrationsConfig] = []
    tick_seconds = 7

    class _SpyEngine:
        def __init__(self, container: Container, config: IntegrationsConfig) -> None:
            captured.append(config)

    monkeypatch.setattr(worker_main, "SyncEngine", _SpyEngine)
    create_worker(Settings(env="test", integrations_tick_seconds=tick_seconds))
    assert captured[0].tick_seconds == tick_seconds


def test_integration_sync_registered_when_disabled() -> None:
    """Wyłączenie schedulera nie usuwa handlera integration_sync (E4-1c T2)."""
    _, worker = create_worker(Settings(env="test", integrations_enabled=False))
    assert "integration_sync" in worker._handlers


def test_start_scheduler_disabled_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    """enabled=False → None i log ``integrations disabled`` (E4-1c T2)."""
    container, _ = create_worker(Settings(env="test"))
    stop = asyncio.Event()
    with caplog.at_level(logging.INFO, logger="app.worker"):
        task = start_scheduler(container, IntegrationsConfig(enabled=False), stop, "w:1")
    assert task is None
    assert "integrations disabled" in caplog.text


async def test_start_scheduler_enabled_returns_task() -> None:
    """enabled=True → asyncio.Task, kończony przez stop.set() (E4-1c T2)."""
    container, _ = create_worker(Settings(env="test"))
    stop = asyncio.Event()
    task = start_scheduler(container, IntegrationsConfig(enabled=True), stop, "w:1")
    assert isinstance(task, asyncio.Task)
    stop.set()
    await task
