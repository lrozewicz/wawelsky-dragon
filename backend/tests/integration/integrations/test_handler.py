"""Handler ``integration_sync`` — kolejka → silnik (brief T9, kontrakt C7).

Sprawdza payload (``manual``/``full``), zachowanie przy zajętym locku, dorejestrowanie
handlera przez ``create_worker`` oraz pełną ścieżkę kolejki: zadanie przez ``DbTaskQueue``
wykonane przez ``Worker``.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories.integrations import RunRow, latest_run, try_lock
from app.db.uow import transaction
from app.integrations.base import ChangeSet
from app.integrations.base import Container as RemoteContainer
from app.integrations.engine import SyncEngine
from app.worker.handlers.integration_sync import make_handler
from app.worker.loop import Worker
from app.worker.main import create_worker
from app.worker.queue import DbTaskQueue, NewTask
from tests.fakes.integrations import FakeConnector, make_item
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

CID = "c1"
CONTAINER_NAME = "Dokumenty"
CURSOR = "cur1"
WORKER_ID = "w1"
POLL_TRIES = 300  # 300 prob x 0.05 s = 15 s na wykonanie zadania


def task_stub(integration_id: int, trigger: str) -> SimpleNamespace:
    """Atrapa ``TaskRow`` z payloadem handlera (styl ``test_parse_handler``)."""
    return SimpleNamespace(id="t1", payload={"integration_id": integration_id, "trigger": trigger})


def ctx_stub(logger: logging.Logger | None = None) -> SimpleNamespace:
    """Atrapa ``TaskContext``: handler używa tylko ``worker_id`` i ``logger``."""
    return SimpleNamespace(
        worker_id=WORKER_ID,
        logger=logger if logger is not None else logging.getLogger("app.worker.task"),
    )


async def latest_run_of(container: Container, integration_id: int) -> RunRow | None:
    """Najnowszy przebieg integracji (``None``, gdy brak wiersza)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await latest_run(session, integration_id)


async def task_status(container: Container, task_id: str) -> str:
    """Status zadania z tabeli ``tasks`` po ``public_id``."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        value = (
            await session.execute(
                text("SELECT status FROM tasks WHERE public_id = :id"), {"id": task_id}
            )
        ).scalar()
    return str(value)


async def wait_for_done(container: Container, task_id: str) -> None:
    """Czeka na ``tasks.status = 'done'`` (poll 0.05 s; wzorzec ``test_worker.py``)."""
    for _ in range(POLL_TRIES):
        if await task_status(container, task_id) == "done":
            return
        await asyncio.sleep(0.05)
    raise AssertionError("zadanie nie osiągnęło statusu done")


async def test_handler_manual_trigger(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Payload ``manual`` → przebieg z ``run_trigger='manual'`` w bazie (kontrakt C7)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    registered_fake.containers = [RemoteContainer(id=CID, name=CONTAINER_NAME)]
    registered_fake.script(CID, [ChangeSet(items=[make_item()], cursor=CURSOR)])

    await make_handler(engine)(task_stub(integration_id, "manual"), ctx_stub())

    run = await latest_run_of(container, integration_id)
    assert run is not None
    assert (run.run_trigger, run.status) == ("manual", "success")


async def test_handler_full_trigger(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Payload ``full`` → przebieg z ``run_trigger='full'`` w bazie (kontrakt C7)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]

    await make_handler(engine)(task_stub(integration_id, "full"), ctx_stub())

    run = await latest_run_of(container, integration_id)
    assert run is not None
    assert (run.run_trigger, run.status) == ("full", "success")


async def test_handler_lock_busy_skips_without_run(
    container: Container, engine: SyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """Zajęty lock: brak wyjątku, brak wiersza runu i log ``skipped`` (kontrakt C7)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        assert await try_lock(session, integration_id, owner="other", now_ms=TIME_MS)
    caplog.set_level(logging.INFO, logger="app.worker.task")

    await make_handler(engine)(task_stub(integration_id, "manual"), ctx_stub())

    assert await latest_run_of(container, integration_id) is None
    assert "integration_sync skipped: lock busy" in caplog.text


def test_create_worker_registers_integration_sync() -> None:
    """``create_worker`` dorejestrowuje handler ``integration_sync`` (kontrakt C7)."""
    _, worker = create_worker(Settings(env="test"))

    assert "integration_sync" in worker._handlers
    assert "parse_document" in worker._handlers


async def test_worker_runs_integration_sync_task(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Zadanie z kolejki → ``tasks.status='done'`` i przebieg ``full`` w bazie (wymaganie 3)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    registered_fake.containers = [RemoteContainer(id=CID, name=CONTAINER_NAME)]
    registered_fake.script(CID, [ChangeSet(items=[make_item()], cursor=CURSOR)])
    queue = DbTaskQueue(
        container.sessionmaker,
        container.clock,
        container.id_gen,  # type: ignore[arg-type]
    )
    task_id = await queue.enqueue(
        NewTask("integration_sync", payload={"integration_id": integration_id, "trigger": "full"})
    )
    worker = Worker(container, {"integration_sync": make_handler(engine)})
    stop = asyncio.Event()
    run_task = asyncio.create_task(worker.run(stop))
    try:
        await wait_for_done(container, task_id)
    finally:
        stop.set()
        await asyncio.wait_for(run_task, timeout=15)

    assert await task_status(container, task_id) == "done"
    run = await latest_run_of(container, integration_id)
    assert run is not None
    assert (run.run_trigger, run.status) == ("full", "success")
