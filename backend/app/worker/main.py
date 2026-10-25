"""Wejście workera — ``python -m app.worker.main`` (K5 §2.3, kontrakt C9).

SIGTERM/SIGINT → ``stop.set()`` → graceful stop pętli i schedulera integracji,
``container.aclose()``, kod 0.
"""

import asyncio
import logging
import multiprocessing
import signal
import sys
from concurrent.futures import Executor, ProcessPoolExecutor

from app.core.config import Settings
from app.core.container import Container
from app.core.logging import configure_logging
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import SyncEngine
from app.integrations.scheduler import Scheduler
from app.integrations.sharepoint.register import register_sharepoint
from app.worker.context import Handler
from app.worker.handlers.integration_sync import make_handler as make_integration_handler
from app.worker.handlers.parse_document import make_handler
from app.worker.kb_cleanup import cleanup_loop
from app.worker.kb_handlers import KB_HANDLERS
from app.worker.loop import Worker, make_worker_id
from app.worker.outline_sweep import outline_sweep_loop
from app.worker.pool import ParsePool

# Rejestr produkcyjny handlerów (kontrakt C8); pula procesów docelowo w ``_amain``.
# ``integration_sync`` i ``build_outline`` dochodzą w ``create_worker`` — leniwy import
# ``build_outline`` trzyma import ``app.worker.main`` lekki (brief T8: bez ``app.parsing``).
# ``KB_HANDLERS`` (eksport/import paczki .wdkb) scala ta sama funkcja — E7-1a/E7-1b
# dopisują swoje handlery w ``kb_handlers.py``, bez dotykania tego pliku.
HANDLERS: dict[str, Handler] = {"parse_document": make_handler(None)}

logger = logging.getLogger("app.worker")


def create_worker(
    settings: Settings | None = None, *, executor: Executor | None = None
) -> tuple[Container, Worker]:
    """Składa kontener i workera bez I/O; bez argumentu czyta ``Settings()`` (kontrakt C9).

    ``executor`` (pula procesów) podmienia handler ``parse_document`` na związaną
    z pulą; ``None`` → konwersja w ``asyncio.to_thread`` (kontrakt C8).
    """
    container = Container(settings if settings is not None else Settings())
    register_sharepoint(container)
    config = IntegrationsConfig.from_settings(container.settings)
    # Leniwy import: ``build_outline`` dołącza ``app.parsing`` — import modułu ma pozostać lekki
    # (brief T8, wymaganie 4), jak w ``Container.ingest``.
    from app.worker.handlers.build_outline import build_outline  # noqa: PLC0415

    handlers: dict[str, Handler] = {
        **HANDLERS,
        **KB_HANDLERS,
        "build_outline": build_outline,
        "integration_sync": make_integration_handler(SyncEngine(container, config)),
    }
    if executor is not None:
        handlers["parse_document"] = make_handler(executor)
    return container, Worker(container, handlers)


def start_scheduler(
    container: Container,
    config: IntegrationsConfig,
    stop: asyncio.Event,
    worker_id: str,
) -> asyncio.Task[None] | None:
    """Scheduler jako drugi task obok ``worker.run``; ``enabled=False`` → ``None`` (kontrakt C7)."""
    if not config.enabled:
        logger.info("integrations disabled")
        return None
    scheduler = Scheduler(container, SyncEngine(container, config), config, worker_id=worker_id)
    return asyncio.create_task(scheduler.run_forever(stop), name="integration-scheduler")


def _new_process_pool(processes: int) -> ProcessPoolExecutor:
    """Pojedyncza pula procesów parsowania z kontekstem forkserver.

    Fork z procesu wielowątkowego grozi zakleszczeniem.
    """
    return ProcessPoolExecutor(
        max_workers=processes, mp_context=multiprocessing.get_context("forkserver")
    )


def make_parse_pool(settings: Settings) -> ParsePool:
    """Pula parsowania odtwarzana po ``BrokenProcessPool``; rozmiar z ``Settings`` (kontrakt C4)."""
    return ParsePool(lambda: _new_process_pool(settings.parse_processes))


async def _amain() -> None:
    """Start: logowanie, kontener, handlery sygnałów, pętla workera i scheduler (C9/C7)."""
    settings = Settings()
    configure_logging(settings)
    pool = make_parse_pool(settings)
    container, worker = create_worker(settings, executor=pool)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.add_signal_handler(signal.SIGINT, stop.set)
    await container.start()
    # Scheduler to drugi ``asyncio.Task`` obok ``worker.run(stop)`` (K12 §5) — wyłączalny env.
    config = IntegrationsConfig.from_settings(settings)
    sched_task = start_scheduler(container, config, stop, f"{make_worker_id()}:sched")
    # Przegląd sprzątania paczek (K19 §5): przebieg przy starcie, potem co godzinę.
    cleanup_task = asyncio.create_task(cleanup_loop(container, stop), name="kb-cleanup")
    # Przegląd uzupełniania profili spisu (K21 §2 p. 4): start + co ``WD_OUTLINE_SWEEP_S``.
    sweep_task = asyncio.create_task(outline_sweep_loop(container, stop), name="outline-sweep")
    try:
        logger.info(
            "worker started",
            extra={
                "concurrency": settings.worker_concurrency,
                "task_types": sorted(worker._handlers),
            },
        )
        await worker.run(stop)
    finally:
        stop.set()
        if sched_task is not None:
            await sched_task
        await cleanup_task
        await sweep_task
        await container.aclose()
        pool.shutdown(wait=True, cancel_futures=True)


def main() -> int:
    """Punkt wejścia procesu; graceful stop daje kod 0 (kontrakt C9)."""
    asyncio.run(_amain())
    return 0


if __name__ == "__main__":
    sys.exit(main())
