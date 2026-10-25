"""Testy usługi sterowania przebiegami integracji na MariaDB (brief T7; kontrakt C7, 09 §8 p. 1-3).

Worker jest symulowany osobnym taskiem ``asyncio`` (kooperacyjne anulowanie) albo jego brak —
testem (wymuszone zwolnienie locka).
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import Conflict, NotFound
from app.core.ids import UuidV7Generator
from app.db.repositories import integrations as integrations_repo
from app.db.repositories import tasks as tasks_repo
from app.db.repositories.integrations import IntegrationRow, RunRow
from app.db.uow import transaction
from app.integrations.base import SyncCounts
from app.integrations.config import IntegrationsConfig
from app.services.integration_runs import CancelResult, IntegrationRunsService
from tests.fakes.clock import FrozenClock
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

POLL_S = 0.01  # brief T7 wymaganie 1: testy skracają poll
CANCEL_WAIT_S = 1
SHORT_TIMEOUT_S = 0.05


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener z FrozenClock; sessionmaker kontenera służy też do czytania wierszy w teście."""
    box = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(TIME_MS),
        id_gen=UuidV7Generator(),
    )
    await box.start()
    yield box
    await box.aclose()


@pytest.fixture
def sm(container: Container) -> async_sessionmaker[AsyncSession]:
    """Sessionmaker wystartowanego kontenera (repozytoria i test czytają tę samą bazę)."""
    sessionmaker = container.sessionmaker
    assert sessionmaker is not None
    return sessionmaker


@pytest.fixture
def service(container: Container) -> IntegrationRunsService:
    """Usługa z krótkim pollem i krótkim ``cancel_wait_seconds`` (brief T7 wymaganie 1)."""
    runs = IntegrationRunsService(container, IntegrationsConfig(cancel_wait_seconds=CANCEL_WAIT_S))
    runs._poll_s = POLL_S
    return runs


async def _insert_run(
    sm: async_sessionmaker[AsyncSession], integration_id: int, *, finished: bool
) -> int:
    """Wstawia przebieg ``running`` (albo od razu zakończony ``success``); zwraca ``id``."""
    async with transaction(sm) as session:
        run_id = await integrations_repo.insert_run(
            session,
            integration_id=integration_id,
            integration_type="fake",
            run_trigger="manual",
            now_ms=TIME_MS,
        )
        if finished:
            await integrations_repo.finish_run(
                session, run_id, status="success", counts=SyncCounts(added=1), now_ms=TIME_MS + 1000
            )
    return run_id


async def _hold_lock(sm: async_sessionmaker[AsyncSession], integration_id: int) -> None:
    """Zakłada lock tak, jak zrobiłby to worker (stan ``is_running=1``)."""
    async with transaction(sm) as session:
        locked = await integrations_repo.try_lock(
            session, integration_id, owner="worker-1", now_ms=TIME_MS
        )
    assert locked is True


async def _integration(sm: async_sessionmaker[AsyncSession], integration_id: int) -> IntegrationRow:
    """Wiersz integracji z bazy (testy sprawdzają ``is_running``/``lock_owner``)."""
    async with transaction(sm) as session:
        row = await integrations_repo.get_integration(session, integration_id)
    assert row is not None
    return row


async def _run(sm: async_sessionmaker[AsyncSession], run_id: int) -> RunRow:
    """Wiersz przebiegu z bazy (testy sprawdzają ``status``/``finished_at``)."""
    async with transaction(sm) as session:
        row = await integrations_repo.get_run(session, run_id)
    assert row is not None
    return row


async def _task(sm: async_sessionmaker[AsyncSession], task_id: str) -> RowMapping:
    """Wiersz zadania kolejki po ``public_id``."""
    async with transaction(sm) as session:
        row = await tasks_repo.get(session, public_id=task_id)
    assert row is not None
    return row


def _payload(row: RowMapping) -> dict[str, object]:
    """Payload zadania: sterownik może zwrócić JSON jako ``str``."""
    raw = row["payload"]
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


async def _sync_task_count(sm: async_sessionmaker[AsyncSession]) -> int:
    """Liczba zadań ``integration_sync`` w tabeli ``tasks``."""
    sql = text("SELECT COUNT(*) FROM tasks WHERE task_type = 'integration_sync'")
    async with transaction(sm) as session:
        value = (await session.execute(sql)).scalar()
    return int(value or 0)


async def test_request_sync_enqueues_manual_task(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Zlecenie ręczne: zadanie ``integration_sync`` z priorytetem 1 i zwróconym ``task_id``."""
    integration_id = await make_integration(sm)
    task_id = await service.request_sync(integration_id, full=False)
    row = await _task(sm, task_id)
    assert row["task_type"] == "integration_sync"
    assert int(row["priority"]) == 1
    assert _payload(row) == {"integration_id": integration_id, "trigger": "manual"}


async def test_request_sync_full_sets_full_trigger(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """``full=True`` ⇒ payload z ``trigger="full"``."""
    integration_id = await make_integration(sm)
    task_id = await service.request_sync(integration_id, full=True)
    assert _payload(await _task(sm, task_id))["trigger"] == "full"


async def test_request_sync_conflict_when_running(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Trwający przebieg (``is_running=1``) ⇒ ``Conflict`` i żadnego nowego zadania."""
    integration_id = await make_integration(sm)
    await _hold_lock(sm, integration_id)
    with pytest.raises(Conflict):
        await service.request_sync(integration_id, full=False)
    assert await _sync_task_count(sm) == 0


async def test_request_sync_unknown_integration(service: IntegrationRunsService) -> None:
    """Nieznana integracja ⇒ ``NotFound``."""
    with pytest.raises(NotFound):
        await service.request_sync(999_999, full=False)


async def test_wait_for_run_returns_run_after_since(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Zwraca pierwszy przebieg o ``id > since_run_id``, który nie jest ``running``."""
    integration_id = await make_integration(sm)
    older = await _insert_run(sm, integration_id, finished=True)
    newer = await _insert_run(sm, integration_id, finished=True)
    row = await service.wait_for_run(integration_id, since_run_id=older, timeout_s=SHORT_TIMEOUT_S)
    assert row is not None
    assert row.id == newer
    assert row.status == "success"


async def test_wait_for_run_ignores_running_and_times_out(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Przebieg ``running`` nie jest wynikiem — po czasie zwracane jest ``None``."""
    integration_id = await make_integration(sm)
    await _insert_run(sm, integration_id, finished=False)
    row = await service.wait_for_run(integration_id, since_run_id=None, timeout_s=SHORT_TIMEOUT_S)
    assert row is None


async def test_wait_for_run_polls_until_run_finishes(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Poll trwa do zakończenia przebiegu — symulowany worker kończy go po chwili."""
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id, finished=False)

    async def worker_finish() -> None:
        await asyncio.sleep(SHORT_TIMEOUT_S)
        async with transaction(sm) as session:
            await integrations_repo.finish_run(
                session, run_id, status="success", counts=SyncCounts(), now_ms=TIME_MS + 1000
            )

    worker = asyncio.create_task(worker_finish())
    try:
        row = await service.wait_for_run(integration_id, since_run_id=None, timeout_s=1.0)
    finally:
        await worker
    assert row is not None
    assert row.id == run_id
    assert row.status == "success"


async def test_cancel_cooperative(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Worker reaguje na ``cancel_requested`` ⇒ ``(True, True, 1)``, lock zwolniony."""
    integration_id = await make_integration(sm)
    await _hold_lock(sm, integration_id)
    run_id = await _insert_run(sm, integration_id, finished=False)

    async def worker_release() -> None:
        await _wait_for_cancel_request(sm, integration_id)
        async with transaction(sm) as session:
            released = await integrations_repo.release_lock(
                session,
                integration_id,
                owner="worker-1",
                now_ms=TIME_MS + 500,
                status="cancelled",
            )
            await integrations_repo.finish_run(
                session, run_id, status="cancelled", counts=SyncCounts(), now_ms=TIME_MS + 500
            )
        assert released is True

    worker = asyncio.create_task(worker_release())
    try:
        result = await service.cancel(integration_id)
    finally:
        await worker
    assert result == CancelResult(True, True, 1)
    assert (await _integration(sm, integration_id)).is_running is False


async def _cancel_requested(sm: async_sessionmaker[AsyncSession], integration_id: int) -> bool:
    """Czy worker został poproszony o anulowanie (``cancel_requested=1``)."""
    async with transaction(sm) as session:
        return await integrations_repo.is_cancel_requested(session, integration_id)


async def _wait_for_cancel_request(
    sm: async_sessionmaker[AsyncSession], integration_id: int
) -> None:
    """Czeka, aż symulowany worker zobaczy ``cancel_requested``; brak w 5 s ⇒ błąd testu."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if await _cancel_requested(sm, integration_id):
            return
        await asyncio.sleep(POLL_S)
    raise AssertionError("cancel was not requested")


async def test_cancel_forced_when_worker_dead(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Nikt nie zwalnia locka ⇒ wymuszenie: ``(False, True, 1)``, run ``cancelled``."""
    integration_id = await make_integration(sm)
    await _hold_lock(sm, integration_id)
    run_id = await _insert_run(sm, integration_id, finished=False)
    result = await service.cancel(integration_id)
    assert result == CancelResult(False, True, 1)
    row = await _integration(sm, integration_id)
    assert row.is_running is False
    assert row.lock_owner is None
    run = await _run(sm, run_id)
    assert run.status == "cancelled"
    assert run.finished_at is not None


async def test_cancel_without_run(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Brak przebiegu i brak sierot ⇒ ``(False, False, 0)``."""
    integration_id = await make_integration(sm)
    result = await service.cancel(integration_id)
    assert result == CancelResult(False, False, 0)


async def test_cancel_marks_orphan_run(
    sm: async_sessionmaker[AsyncSession], service: IntegrationRunsService
) -> None:
    """Bez locka, ale z osieroconym runem ``running`` ⇒ ``(False, False, 1)``, run zamknięty."""
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id, finished=False)
    result = await service.cancel(integration_id)
    assert result == CancelResult(False, False, 1)
    assert (await _run(sm, run_id)).status == "cancelled"


async def test_cancel_unknown_integration(service: IntegrationRunsService) -> None:
    """Nieznana integracja ⇒ ``NotFound``."""
    with pytest.raises(NotFound):
        await service.cancel(999_999)
