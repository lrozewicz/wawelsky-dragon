"""Testy ``RunRecorder`` na prawdziwej MariaDB (brief T5, kontrakt C4)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories.integrations import EventRow, get_run, list_events
from app.db.uow import transaction
from app.integrations.audit import FILE_PATH_LIMIT, MESSAGE_LIMIT, RunRecorder
from app.integrations.config import IntegrationsConfig
from tests.fakes.clock import FrozenClock
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]
CONFIG = IntegrationsConfig()
ADVANCE_PAST_FLUSH_MS = int(CONFIG.events_flush_seconds * 1000) + 100
LONG_MESSAGE_LEN = MESSAGE_LIMIT + 500
LONG_FILE_PATH_LEN = FILE_PATH_LIMIT + 476
UPDATED_COUNT = 3
FINISH_EVENT_COUNT = 2


@pytest.fixture
def clock() -> FrozenClock:
    """Zegar zamrożony na stałym czasie testów."""
    return FrozenClock(TIME_MS)


@pytest.fixture
def container(migrated_db: Settings, sm: SM, clock: FrozenClock) -> Container:
    """Kontener bez I/O: ustawienia, wstrzyknięty zegar i ``sessionmaker`` ze świeżej bazy."""
    instance = Container(migrated_db, clock=clock)
    instance.sessionmaker = sm
    return instance


async def start_recorder(container: Container, *, trigger: str = "manual") -> RunRecorder:
    """Tworzy integrację i rejestrator z otwartym przebiegiem."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    recorder = RunRecorder(
        container, CONFIG, integration_id=integration_id, integration_type="fake"
    )
    await recorder.start(trigger)  # type: ignore[arg-type]
    return recorder


async def events_of(container: Container, run_id: int) -> list[EventRow]:
    """Zdarzenia przebiegu z bazy."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await list_events(session, run_id)


async def test_start_inserts_running_run(container: Container) -> None:
    recorder = await start_recorder(container)

    assert recorder.run_id > 0
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_run(session, recorder.run_id)
    assert row is not None
    assert row.integration_type == "fake"
    assert row.run_trigger == "manual"
    assert row.status == "running"
    assert row.started_at == TIME_MS
    assert row.finished_at is None
    assert (row.added, row.updated, row.renamed, row.deleted, row.failed, row.skipped) == (
        0,
        0,
        0,
        0,
        0,
        0,
    )


async def test_buffer_below_threshold_is_not_flushed(container: Container) -> None:
    recorder = await start_recorder(container)
    for index in range(CONFIG.events_flush_every - 1):
        recorder.event("info", f"msg-{index}")

    await recorder.maybe_flush()

    assert await events_of(container, recorder.run_id) == []


async def test_threshold_flush_writes_whole_buffer(container: Container) -> None:
    recorder = await start_recorder(container)
    for index in range(CONFIG.events_flush_every):
        recorder.event("info", f"msg-{index}")

    await recorder.maybe_flush()

    assert len(await events_of(container, recorder.run_id)) == CONFIG.events_flush_every


async def test_time_based_flush_writes_buffer(container: Container, clock: FrozenClock) -> None:
    recorder = await start_recorder(container)
    recorder.event("warn", "late")

    clock.advance(ADVANCE_PAST_FLUSH_MS)
    await recorder.maybe_flush()

    assert len(await events_of(container, recorder.run_id)) == 1


async def test_maybe_flush_with_empty_buffer_keeps_elapsed_time(
    container: Container, clock: FrozenClock
) -> None:
    recorder = await start_recorder(container)
    clock.advance(ADVANCE_PAST_FLUSH_MS)

    await recorder.maybe_flush()  # pusty bufor: bez zapisu i bez resetu licznika czasu

    assert await events_of(container, recorder.run_id) == []
    recorder.event("info", "after")
    await recorder.maybe_flush()
    assert len(await events_of(container, recorder.run_id)) == 1


async def test_event_trims_message_and_file_path(container: Container) -> None:
    recorder = await start_recorder(container)
    recorder.event("error", "m" * LONG_MESSAGE_LEN, file_path="/" + "p" * LONG_FILE_PATH_LEN)
    recorder.event("info", "short", file_path=None)

    await recorder.flush()

    events = await events_of(container, recorder.run_id)
    assert len(events[0].message) == MESSAGE_LIMIT
    assert events[0].message.endswith("…")
    assert events[0].file_path is not None
    assert len(events[0].file_path) == FILE_PATH_LIMIT
    assert events[1].file_path is None


async def test_flush_updates_counts_and_does_not_duplicate_events(container: Container) -> None:
    recorder = await start_recorder(container)
    recorder.event("info", "x")
    recorder.counts.updated = UPDATED_COUNT

    await recorder.flush()
    await recorder.flush()

    assert len(await events_of(container, recorder.run_id)) == 1
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_run(session, recorder.run_id)
    assert row is not None
    assert row.updated == UPDATED_COUNT


async def test_finish_flushes_events_counts_and_finished_at(
    container: Container, clock: FrozenClock
) -> None:
    recorder = await start_recorder(container)
    recorder.event("info", "a")
    recorder.event("error", "b")
    recorder.counts.added = 2
    recorder.counts.failed = 1

    clock.advance(500)
    await recorder.finish("partial")

    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_run(session, recorder.run_id)
    assert row is not None
    assert row.status == "partial"
    assert row.finished_at == TIME_MS + 500
    assert (row.added, row.failed) == (2, 1)
    assert len(await events_of(container, recorder.run_id)) == FINISH_EVENT_COUNT


async def test_events_keep_call_order(container: Container) -> None:
    recorder = await start_recorder(container)
    for index in range(5):
        recorder.event("info", f"e{index}")

    await recorder.finish("success")

    events = await events_of(container, recorder.run_id)
    assert [event.message for event in events] == [f"e{index}" for index in range(5)]
    assert [event.id for event in events] == sorted(event.id for event in events)
