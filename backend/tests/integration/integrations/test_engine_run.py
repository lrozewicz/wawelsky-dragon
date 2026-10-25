"""Przebieg ``SyncEngine.run`` — lock, status końcowy, kursor, heartbeat (brief T6, kontrakt C5).

Testy na prawdziwej MariaDB i ``FakeConnector`` (kontrakt C8): sprawdzają sam przebieg
(status, liczniki, zwolnienie locka), a nie tabelę decyzji per element (ta ma osobny plik
``test_engine_decisions.py``).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Container
from app.db.repositories.integrations import (
    ContainerRow,
    IntegrationRow,
    get_container,
    get_integration,
    latest_run,
    list_events,
    try_lock,
)
from app.db.uow import transaction
from app.integrations import engine as engine_module
from app.integrations import registry
from app.integrations.base import ChangeSet, RemoteItem
from app.integrations.base import Container as RemoteContainer
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import RunOutcome, SyncEngine
from tests.fakes.clock import FrozenClock
from tests.fakes.integrations import FakeConnector, fake_load_config, make_item
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

CID = "c1"
CONTAINER_NAME = "Dokumenty"
CURSOR = "cur1"
SECOND_CURSOR = "cur2"
WORKER_ID = "w1"
OTHER_OWNER = "w2"
CONFIG = IntegrationsConfig()
HEARTBEAT_MS = CONFIG.heartbeat_seconds * 1000


class AdvancingConnector(FakeConnector):
    """``FakeConnector``, który przy każdym pobraniu przesuwa zegar o ``step_ms``.

    Pozwala pokazać heartbeat locka „między elementami”: pierwsze pobranie przesuwa zegar
    poza ``heartbeat_seconds``, więc silnik odświeża ``lock_acquired_at`` przed drugim
    elementem.
    """

    def __init__(self, clock: FrozenClock, step_ms: int) -> None:
        super().__init__()
        self._clock = clock
        self._step_ms = step_ms

    async def download(
        self, cfg: object, item: RemoteItem, dest_path: Path, *, max_bytes: int
    ) -> int:
        self._clock.advance(self._step_ms)
        return await super().download(cfg, item, dest_path, max_bytes=max_bytes)


class BrokenConnector(FakeConnector):
    """``FakeConnector``, któremu ``list_containers`` pada (błąd globalny przebiegu)."""

    async def list_containers(self, cfg: object) -> list[RemoteContainer]:
        raise RuntimeError("boom")


@pytest.fixture
def broken_connector() -> Iterator[FakeConnector]:
    """Rejestruje konektor z padającym ``list_containers``; po teście czyści rejestr."""
    connector = BrokenConnector()
    registry.register("fake", connector, fake_load_config)
    yield connector
    registry.clear()


@pytest.fixture
def advancing_connector(clock: FrozenClock) -> Iterator[FakeConnector]:
    """Rejestruje konektor przesuwający zegar przy pobraniu; po teście czyści rejestr."""
    connector = AdvancingConnector(clock, HEARTBEAT_MS + 1)
    registry.register("fake", connector, fake_load_config)
    yield connector
    registry.clear()


def script_pass(
    fake: FakeConnector, items: list[RemoteItem], *, cursor: str | None = CURSOR
) -> None:
    """Ustawia listę kontenerów i pierwsze przejście ``changes``."""
    fake.containers = [RemoteContainer(id=CID, name=CONTAINER_NAME)]
    fake.script(CID, [ChangeSet(items=items, cursor=cursor)])


async def start_run(engine: SyncEngine, integration_id: int) -> RunOutcome:
    """Uruchamia przebieg, który musi się odbyć (lock wolny)."""
    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)
    assert outcome is not None
    return outcome


def counts_of(outcome: RunOutcome) -> tuple[int, ...]:
    """Liczniki wyniku jako krotka (added, updated, renamed, deleted, failed, skipped)."""
    counts = outcome.counts
    return (
        counts.added,
        counts.updated,
        counts.renamed,
        counts.deleted,
        counts.failed,
        counts.skipped,
    )


async def integration_of(container: Container, integration_id: int) -> IntegrationRow:
    """Wiersz integracji (musi istnieć)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_integration(session, integration_id)
    assert row is not None
    return row


async def stored_container(container: Container, integration_id: int) -> ContainerRow:
    """Wiersz kontenera integracji (musi istnieć)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_container(session, integration_id, CID)
    assert row is not None
    return row


async def run_events(container: Container, run_id: int) -> list[tuple[str, str]]:
    """Zdarzenia przebiegu jako pary ``(level, message)`` w kolejności zapisu."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        events = await list_events(session, run_id)
    return [(event.level, event.message) for event in events]


async def test_lock_taken_returns_none_without_run_row(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Zajęty lock: ``run`` zwraca ``None`` i nie zakłada wiersza przebiegu (kontrakt C5)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        assert await try_lock(session, integration_id, owner=OTHER_OWNER, now_ms=TIME_MS)
    script_pass(registered_fake, [make_item()])

    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)

    assert outcome is None
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        assert await latest_run(session, integration_id) is None
    assert registered_fake.calls == []
    row = await integration_of(container, integration_id)
    assert (row.is_running, row.lock_owner) == (True, OTHER_OWNER)


async def test_missing_integration_after_lock_returns_none(
    container: Container, engine: SyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integracja zniknęła po założeniu locka: brak wiersza runu, ``None``, lock zdjęty."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]

    async def fake_try_lock(
        session: AsyncSession, integration_id: int, *, owner: str, now_ms: int
    ) -> bool:
        return True

    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        await session.execute(
            text("DELETE FROM integrations WHERE id = :id"), {"id": integration_id}
        )
    monkeypatch.setattr(engine_module.repo, "try_lock", fake_try_lock)

    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)

    assert outcome is None
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        assert await get_integration(session, integration_id) is None


async def test_success_run_counts_and_lock_release(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Przebieg bez błędów: status ``success``, liczniki w wierszu runu, lock zwolniony."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    script_pass(registered_fake, [make_item()])

    outcome = await start_run(engine, integration_id)

    assert outcome.status == "success"
    assert counts_of(outcome) == (1, 0, 0, 0, 0, 0)
    assert outcome.run_id > 0
    row = await integration_of(container, integration_id)
    assert (row.is_running, row.lock_owner) == (False, None)
    assert (row.last_sync_at, row.last_sync_status) == (TIME_MS, "success")
    assert row.cancel_requested is False


async def test_partial_status_when_some_items_fail(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Część elementów pada, część się zmienia → status ``partial`` (09 §6 pkt 7)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    registered_fake.fail_download[(CID, "i2")] = RuntimeError("boom")
    script_pass(
        registered_fake,
        [make_item(item_id="i1"), make_item(item_id="i2", name="b.txt", path="/b.txt")],
    )

    outcome = await start_run(engine, integration_id)

    assert outcome.status == "partial"
    assert counts_of(outcome) == (1, 0, 0, 0, 1, 0)
    row = await integration_of(container, integration_id)
    assert (row.is_running, row.last_sync_status) == (False, "partial")


async def test_failed_status_when_nothing_changed(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Same błędy elementów i zero zmian → status ``failed`` (09 §6 pkt 7)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    registered_fake.fail_download[(CID, "i1")] = RuntimeError("boom")
    script_pass(registered_fake, [make_item()])

    outcome = await start_run(engine, integration_id)

    assert outcome.status == "failed"
    assert counts_of(outcome) == (0, 0, 0, 0, 1, 0)
    row = await integration_of(container, integration_id)
    assert (row.is_running, row.last_sync_status) == (False, "failed")


async def test_list_containers_failure_marks_run_failed_and_releases_lock(
    container: Container, engine: SyncEngine, broken_connector: FakeConnector
) -> None:
    """Wyjątek globalny: zdarzenie ``error``, status ``failed``, lock zwolniony."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]

    outcome = await start_run(engine, integration_id)

    assert outcome.status == "failed"
    assert counts_of(outcome) == (0, 0, 0, 0, 0, 0)
    errors = [pair for pair in await run_events(container, outcome.run_id) if pair[0] == "error"]
    assert errors == [("error", "sync failed: boom")]
    row = await integration_of(container, integration_id)
    assert (row.is_running, row.lock_owner) == (False, None)
    assert (row.last_sync_at, row.last_sync_status) == (TIME_MS, "failed")


async def test_container_cursor_saved_and_reused(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Kursor kontenera zapisany po przejściu; drugi przebieg woła ``changes`` z kursorem."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    script_pass(registered_fake, [make_item()])

    await start_run(engine, integration_id)

    stored = await stored_container(container, integration_id)
    assert (stored.delta_cursor, stored.last_sync_at) == (CURSOR, TIME_MS)

    registered_fake.script_run(CID, [ChangeSet(items=[], cursor=SECOND_CURSOR)])
    await start_run(engine, integration_id)

    changes_calls = [call for call in registered_fake.calls if call[0] == "changes"]
    assert changes_calls == [("changes", CID, None), ("changes", CID, CURSOR)]
    stored = await stored_container(container, integration_id)
    assert stored.delta_cursor == SECOND_CURSOR


async def test_cursor_kept_when_page_has_no_cursor(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Strona bez kursora nie zeruje zapisanego kursora kontenera (brief T6 pkt 6)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    script_pass(registered_fake, [make_item()])
    await start_run(engine, integration_id)

    registered_fake.script_run(CID, [ChangeSet(items=[], cursor=None)])
    await start_run(engine, integration_id)

    stored = await stored_container(container, integration_id)
    assert stored.delta_cursor == CURSOR


async def test_heartbeat_refreshes_lock_between_items(
    container: Container, engine: SyncEngine, advancing_connector: FakeConnector
) -> None:
    """Heartbeat: zegar przesunięty między elementami → świeże ``lock_acquired_at`` (C5/C6)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    script_pass(
        advancing_connector,
        [make_item(item_id="i1"), make_item(item_id="i2", name="b.txt", path="/b.txt")],
    )

    outcome = await start_run(engine, integration_id)

    assert counts_of(outcome) == (2, 0, 0, 0, 0, 0)
    row = await integration_of(container, integration_id)
    assert row.lock_acquired_at == TIME_MS + HEARTBEAT_MS + 1
