"""Locki i scheduler integracji — testy na MariaDB (brief T9, kontrakt C6).

Zakres: lock między dwiema replikami, odzyskiwanie stale locka, retencja zdarzeń, wybór
integracji „due”, odporność ticku na wyjątek jednej integracji i zakończenie ``run_forever``.
Heartbeat locka w trakcie przebiegu pokrywa już test T6
(``test_engine_run.py::test_heartbeat_refreshes_lock_between_items``).
"""

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.core.container import Container
from app.db.repositories.integrations import (
    IntegrationRow,
    NewEvent,
    RunRow,
    get_integration,
    get_run,
    insert_events,
    insert_run,
    latest_run,
    list_events,
)
from app.db.uow import transaction
from app.integrations import locks, registry
from app.integrations.base import ChangeSet, RemoteItem, RunTrigger
from app.integrations.base import Container as RemoteContainer
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import RunOutcome, SyncEngine
from app.integrations.scheduler import Scheduler
from tests.fakes.integrations import FakeConnector, fake_load_config, make_item
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

CID = "c1"
CONTAINER_NAME = "Dokumenty"
CURSOR = "cur1"
WORKER_ID = "replica-1"
OTHER_ID = "replica-2"
CONFIG = IntegrationsConfig()
STALE_MS = CONFIG.stale_lock_minutes * 60_000
RETENTION_MS = CONFIG.events_retention_days * 86_400_000
EVENT_RUN_ID = 999  # zdarzenia retencji nie potrzebują wiersza przebiegu (brak FK)


class GatedConnector(FakeConnector):
    """``FakeConnector`` z bramką: sygnalizuje wejście w ``download`` (lock już założony)."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()

    async def download(self, cfg: Any, item: RemoteItem, dest_path: Path, *, max_bytes: int) -> int:
        """Ustawia ``entered`` i czeka na ``block`` — trzyma pierwszy przebieg w locie."""
        self.entered.set()
        return await super().download(cfg, item, dest_path, max_bytes=max_bytes)


@pytest.fixture
def gated_fake() -> Iterator[GatedConnector]:
    """Rejestruje konektor z bramką pobrania; po teście czyści rejestr."""
    connector = GatedConnector()
    registry.register("fake", connector, fake_load_config)
    yield connector
    registry.clear()


async def row_of(container: Container, integration_id: int) -> IntegrationRow:
    """Wiersz integracji (musi istnieć)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_integration(session, integration_id)
    assert row is not None
    return row


async def run_of(container: Container, run_id: int) -> RunRow:
    """Wiersz przebiegu (musi istnieć)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_run(session, run_id)
    assert row is not None
    return row


async def latest_run_of(container: Container, integration_id: int) -> RunRow:
    """Najnowszy przebieg integracji (musi istnieć)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await latest_run(session, integration_id)
    assert row is not None
    return row


async def events_of(container: Container, run_id: int) -> list[tuple[str, str]]:
    """Zdarzenia przebiegu jako pary ``(level, message)``."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        events = await list_events(session, run_id)
    return [(event.level, event.message) for event in events]


async def event_messages(container: Container) -> list[str]:
    """Wszystkie komunikaty zdarzeń w kolejności ``id`` (test retencji)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        result = await session.execute(
            text("SELECT message FROM integration_sync_events ORDER BY id")
        )
    return [str(value) for value in result.scalars().all()]


async def set_running(
    container: Container,
    integration_id: int,
    *,
    acquired_at: int,
    last_sync_at: int | None,
    owner: str = OTHER_ID,
) -> None:
    """Ustawia stan „przebieg trwa” w bazie (setup testów locka)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        await session.execute(
            text(
                "UPDATE integrations SET is_running = 1, lock_owner = :owner,"
                " lock_acquired_at = :acquired_at, last_sync_at = :last_sync_at WHERE id = :id"
            ),
            {
                "owner": owner,
                "acquired_at": acquired_at,
                "last_sync_at": last_sync_at,
                "id": integration_id,
            },
        )


async def start_run_row(container: Container, integration_id: int) -> int:
    """Wstawia wiersz przebiegu ``running`` (setup testów odzyskiwania)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await insert_run(
            session,
            integration_id=integration_id,
            integration_type="fake",
            run_trigger="schedule",
            now_ms=TIME_MS,
        )


async def insert_event_rows(container: Container, rows: list[tuple[int, str]]) -> None:
    """Wstawia zdarzenia ``(created_at, message)`` — bez wiersza przebiegu (brak FK)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        await insert_events(
            session,
            [
                NewEvent(
                    run_id=EVENT_RUN_ID,
                    integration_id=1,
                    integration_type="fake",
                    level="info",
                    message=message,
                    file_path=None,
                    container_id=None,
                    container_name=None,
                    created_at=created_at,
                )
                for created_at, message in rows
            ],
        )


async def test_locks_layer_acquire_heartbeat_release(container: Container) -> None:
    """Cienka warstwa locków: acquire/heartbeat/release wg właściciela (kontrakt C6)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]

    assert await locks.acquire(container, integration_id, owner=WORKER_ID, now_ms=TIME_MS)
    assert not await locks.acquire(container, integration_id, owner=OTHER_ID, now_ms=TIME_MS)
    assert await locks.heartbeat(container, integration_id, owner=WORKER_ID, now_ms=TIME_MS + 1)
    assert not await locks.heartbeat(container, integration_id, owner=OTHER_ID, now_ms=TIME_MS + 1)

    assert await locks.release(
        container, integration_id, owner=WORKER_ID, now_ms=TIME_MS + 2, status="success"
    )

    row = await row_of(container, integration_id)
    assert (row.is_running, row.lock_owner) == (False, None)
    assert (row.last_sync_at, row.last_sync_status) == (TIME_MS + 2, "success")


async def test_two_replicas_hold_lock_once(
    container: Container, engine: SyncEngine, gated_fake: GatedConnector
) -> None:
    """Dwie repliki naraz: tylko pierwszy przebieg dostaje lock, drugi zwraca ``None`` (C5/C6)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    gated_fake.containers = [RemoteContainer(id=CID, name=CONTAINER_NAME)]
    gated_fake.script(CID, [ChangeSet(items=[make_item()], cursor=CURSOR)])
    gated_fake.block = asyncio.Event()
    second_engine = SyncEngine(container, CONFIG)

    first = asyncio.create_task(engine.run(integration_id, trigger="manual", worker_id=WORKER_ID))
    await asyncio.wait_for(gated_fake.entered.wait(), timeout=5.0)
    second = await second_engine.run(integration_id, trigger="manual", worker_id=OTHER_ID)
    gated_fake.block.set()
    first_outcome = await first

    outcomes: list[RunOutcome | None] = [first_outcome, second]
    assert sum(outcome is not None for outcome in outcomes) == 1
    assert first_outcome is not None
    assert first_outcome.status == "success"
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        runs = (await session.execute(text("SELECT id FROM integration_sync_runs"))).scalars().all()
    assert len(runs) == 1


async def test_tick_recovers_stale_lock(container: Container, engine: SyncEngine) -> None:
    """Lock starszy niż ``stale_lock_minutes``: run ``failed``, zdarzenie, lock zdjęty (C6)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    await set_running(
        container, integration_id, acquired_at=TIME_MS - STALE_MS - 60_000, last_sync_at=TIME_MS
    )
    run_id = await start_run_row(container, integration_id)
    scheduler = Scheduler(container, engine, CONFIG, worker_id=WORKER_ID)

    started = await scheduler.tick(TIME_MS)

    assert started == []
    row = await row_of(container, integration_id)
    assert (row.is_running, row.lock_owner) == (False, None)
    run = await run_of(container, run_id)
    assert (run.status, run.finished_at) == ("failed", TIME_MS)
    assert ("error", "stale lock recovered") in await events_of(container, run_id)


async def test_tick_keeps_fresh_lock(container: Container, engine: SyncEngine) -> None:
    """Świeży lock (1 min) nie jest odzyskiwany — przebieg zostaje ``running`` (C6)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    await set_running(container, integration_id, acquired_at=TIME_MS - 60_000, last_sync_at=TIME_MS)
    run_id = await start_run_row(container, integration_id)
    scheduler = Scheduler(container, engine, CONFIG, worker_id=WORKER_ID)

    assert await scheduler.tick(TIME_MS) == []

    row = await row_of(container, integration_id)
    assert (row.is_running, row.lock_owner) == (True, OTHER_ID)
    assert (await run_of(container, run_id)).status == "running"


async def test_tick_purges_events_older_than_retention(
    container: Container, engine: SyncEngine
) -> None:
    """Zdarzenia starsze niż ``events_retention_days`` znikają, młodsze zostają (C6)."""
    await insert_event_rows(container, [(TIME_MS - RETENTION_MS - 60_000, "old"), (TIME_MS, "new")])
    scheduler = Scheduler(container, engine, CONFIG, worker_id=WORKER_ID)

    await scheduler.tick(TIME_MS)

    assert await event_messages(container) == ["new"]


async def test_tick_runs_only_due_integrations(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Tylko aktywne, wolne i po interwale — w kolejności ``id``, z triggerem ``schedule`` (C6)."""
    first = await make_integration(container.sessionmaker, name="due-1")  # type: ignore[arg-type]
    second = await make_integration(container.sessionmaker, name="due-2")  # type: ignore[arg-type]
    await make_integration(container.sessionmaker, name="off", is_active=False)  # type: ignore[arg-type]
    busy = await make_integration(container.sessionmaker, name="busy")  # type: ignore[arg-type]
    await set_running(container, busy, acquired_at=TIME_MS, last_sync_at=None)
    scheduler = Scheduler(container, engine, CONFIG, worker_id=WORKER_ID)

    started = await scheduler.tick(TIME_MS)

    assert started == [first, second]
    run = await latest_run_of(container, first)
    assert (run.run_trigger, run.status) == ("schedule", "success")
    assert (await row_of(container, first)).last_sync_status == "success"


async def test_tick_survives_exception_of_one_integration(
    container: Container,
    engine: SyncEngine,
    registered_fake: FakeConnector,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Wyjątek infrastruktury jednej integracji nie przerywa kolejnych (kontrakt C6)."""
    ghost = await make_integration(container.sessionmaker, name="ghost")  # type: ignore[arg-type]
    working = await make_integration(container.sessionmaker, name="working")  # type: ignore[arg-type]
    real_run = engine.run

    async def exploding_run(
        integration_id: int, *, trigger: RunTrigger, worker_id: str
    ) -> RunOutcome | None:
        if integration_id == ghost:
            raise RuntimeError("infra boom")
        return await real_run(integration_id, trigger=trigger, worker_id=worker_id)

    monkeypatch.setattr(engine, "run", exploding_run)
    caplog.set_level(logging.ERROR, logger="app.integrations.scheduler")
    scheduler = Scheduler(container, engine, CONFIG, worker_id=WORKER_ID)

    started = await scheduler.tick(TIME_MS)

    assert started == [working]
    assert "scheduled run failed" in caplog.text
    assert (await latest_run_of(container, working)).run_trigger == "schedule"
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        assert await latest_run(session, ghost) is None


async def test_run_forever_ticks_and_exits_after_stop(
    container: Container, engine: SyncEngine
) -> None:
    """``run_forever`` wykonuje tick i kończy się po ``stop.set()`` (kontrakt C6)."""
    await insert_event_rows(container, [(TIME_MS - RETENTION_MS - 60_000, "old")])
    config = IntegrationsConfig(tick_seconds=1)
    scheduler = Scheduler(container, engine, config, worker_id=WORKER_ID)
    stop = asyncio.Event()

    task = asyncio.create_task(scheduler.run_forever(stop))
    await asyncio.sleep(0.5)  # czas na pierwszy tick (jedyne realne czekanie, brief T9)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert task.done()
    assert await event_messages(container) == []
