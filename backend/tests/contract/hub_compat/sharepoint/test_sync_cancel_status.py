"""`sync`, `cancel` i `status` SVC — AG-21/AG-26/AG-27 (kontrakt E4-3a §3-§4, K7 część 2 §7 p. 8-9).

Zadanie `integration_sync` wykonuje **prawdziwy** `Worker` z handlerem silnika
(`tests/integration/integrations/test_scenario.py`), bez sieci i bez `sleep` na sztywno.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories import integrations as integrations_repo
from app.db.uow import transaction
from app.integrations.base import ChangeSet
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import SyncEngine
from app.worker.handlers.integration_sync import make_handler
from app.worker.loop import Worker
from tests.contract.hub_compat.sharepoint.conftest import (
    CONTAINER_D1,
    CONTAINER_D1_NAME,
    wait_async,
)
from tests.fakes.integrations import make_item

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

OK = 200
ACCEPTED = 202
NOT_FOUND = 404
CONFLICT = 409
NOW_MS = 1_790_157_600_000
OLD_CURSOR = "stary-kursor"
WORKER_SHUTDOWN_S = 15
CANCELLED_RUN_COUNT = 1

CANCEL_KEYS = {"was_running_in_process", "lock_cleared", "runs_marked_cancelled"}


@pytest.fixture
async def worker(container: Container) -> AsyncIterator[None]:
    """Prawdziwy `Worker` z handlerem `integration_sync` (bez `sleep`; poll z `worker_poll_s`)."""
    engine = SyncEngine(container, IntegrationsConfig())
    instance = Worker(container, {"integration_sync": make_handler(engine)})
    stop = asyncio.Event()
    runner = asyncio.create_task(instance.run(stop))
    yield
    stop.set()
    await asyncio.wait_for(runner, timeout=WORKER_SHUTDOWN_S)


async def queued_triggers(sm: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    """Payloady zadań `integration_sync` w kolejności wstawienia (K12 §5)."""
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT payload FROM tasks WHERE task_type = 'integration_sync' ORDER BY id"
                    )
                )
            )
            .scalars()
            .all()
        )
    return [value if isinstance(value, dict) else json.loads(str(value)) for value in rows]


async def run_finished(sm: async_sessionmaker[AsyncSession], integration_id: int) -> bool:
    """Czy najnowszy przebieg integracji wyszedł ze stanu `running` (lock zwolniony)."""
    async with transaction(sm) as session:
        run = await integrations_repo.latest_run(session, integration_id)
    return run is not None and run.status != "running"


async def latest_run_status(sm: async_sessionmaker[AsyncSession], integration_id: int) -> str:
    """Status najnowszego przebiegu (pusty, gdy brak)."""
    async with transaction(sm) as session:
        run = await integrations_repo.latest_run(session, integration_id)
    return "" if run is None else run.status


async def download_seen(connector: Any, item_id: str) -> bool:
    """Czy konektor zaczął pobierać element `d1` (przebieg realnie trwa)."""
    return ("download", CONTAINER_D1, item_id) in connector.calls


async def is_cancelled_run(sm: async_sessionmaker[AsyncSession], integration_id: int) -> bool:
    """Czy najnowszy przebieg jest już zamknięty statusem `cancelled` (K12 §5 p. 3)."""
    return await latest_run_status(sm, integration_id) == "cancelled"


async def cancel_requested(sm: async_sessionmaker[AsyncSession], integration_id: int) -> bool:
    """Czy przebieg dostał żądanie anulowania (K12 §5)."""
    async with transaction(sm) as session:
        return await integrations_repo.is_cancel_requested(session, integration_id)


async def source_cursor(
    sm: async_sessionmaker[AsyncSession], integration_id: int, container_id: str
) -> str | None:
    """`delta_cursor` kontenera w bazie."""
    async with transaction(sm) as session:
        row = await integrations_repo.get_container(session, integration_id, container_id)
    assert row is not None
    return row.delta_cursor


async def test_ag26_sync_flags_and_queued_task(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-26: 202 `{started, full}` (oba zapisy `full`), bez `full` → `false`, zadanie w kolejce."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    url = f"{prefix}/api/integrations/{created['id']}/sync"

    by_one = await svc.post(url, params={"full": "1"})
    by_word = await svc.post(url, params={"full": "true"})
    plain = await svc.post(url)

    assert by_one.status_code == ACCEPTED, by_one.text
    assert set(by_one.json()) == {"data"}
    assert by_one.json() == {"data": {"started": True, "full": True}}
    assert by_word.status_code == ACCEPTED
    assert by_word.json() == {"data": {"started": True, "full": True}}
    assert plain.status_code == ACCEPTED
    assert plain.json() == {"data": {"started": True, "full": False}}

    queued = await queued_triggers(sm)
    assert [task["trigger"] for task in queued] == ["full", "full", "manual"]
    assert all(task["integration_id"] == created["id"] for task in queued)


async def test_ag26_sync_unknown_integration(svc: Any, prefix: str, connector: Any) -> None:
    """AG-26: nieznana integracja → 404 `{error}` SVC."""
    response = await svc.post(f"{prefix}/api/integrations/999999/sync")

    assert response.status_code == NOT_FOUND
    assert response.json() == {"error": "Not found"}


async def test_ag26_sync_conflict_when_running(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-26: zajęty lock (`is_running=1`) → 409 „Sync already running”."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    async with transaction(sm) as session:
        locked = await integrations_repo.try_lock(
            session, created["id"], owner="worker-1", now_ms=NOW_MS
        )
    assert locked

    response = await svc.post(f"{prefix}/api/integrations/{created['id']}/sync")

    assert response.status_code == CONFLICT, response.text
    assert response.json() == {"error": "Sync already running"}


async def test_ag26_full_sync_resets_delta_cursor(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
    worker: None,
) -> None:
    """AG-26: zadanie `trigger:"full"` wykonane prawdziwym Workerem zeruje `delta_cursor`."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    integration_id = created["id"]
    async with transaction(sm) as session:
        await integrations_repo.upsert_container(
            session, integration_id, CONTAINER_D1, name=CONTAINER_D1_NAME, now_ms=NOW_MS
        )
        await integrations_repo.set_container_cursor(
            session, integration_id, CONTAINER_D1, cursor=OLD_CURSOR, now_ms=NOW_MS
        )
    connector.script(CONTAINER_D1, [ChangeSet(items=[], cursor=None)])

    sync_url = f"{prefix}/api/integrations/{integration_id}/sync"
    response = await svc.post(sync_url, params={"full": "1"})

    assert response.status_code == ACCEPTED, response.text
    assert response.json() == {"data": {"started": True, "full": True}}
    await wait_async(lambda: run_finished(sm, integration_id))

    # Sam wynik `None` nie dowodzi resetu — dowodzi go kursor, z jakim silnik zapytał konektor.
    assert ("changes", CONTAINER_D1, None) in connector.calls
    assert await source_cursor(sm, integration_id, CONTAINER_D1) is None


async def test_ag27_cancel_without_running_sync(
    svc: Any, prefix: str, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """AG-27: brak przebiegu → `{false, false, 0}` z dokładnymi kluczami."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)

    response = await svc.post(f"{prefix}/api/integrations/{created['id']}/cancel")

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert set(data) == CANCEL_KEYS
    assert data == {
        "was_running_in_process": False,
        "lock_cleared": False,
        "runs_marked_cancelled": 0,
    }


async def test_ag27_cancel_unknown_integration(svc: Any, prefix: str, connector: Any) -> None:
    """AG-27: nieznana integracja → 404 `{error}` SVC."""
    response = await svc.post(f"{prefix}/api/integrations/999999/cancel")

    assert response.status_code == NOT_FOUND
    assert response.json() == {"error": "Not found"}


async def test_ag27_cancel_stops_running_sync(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
    worker: None,
) -> None:
    """AG-27: cancel przez API realnie przerywa przebieg — run kończy `cancelled`, lock wraca."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    integration_id = created["id"]
    connector.script(
        CONTAINER_D1,
        [
            ChangeSet(
                items=[
                    make_item(container_id=CONTAINER_D1, item_id="i1", name="a.txt", path="/a.txt"),
                    make_item(container_id=CONTAINER_D1, item_id="i2", name="b.txt", path="/b.txt"),
                ],
                cursor="cur-1",
            )
        ],
    )
    connector.block = asyncio.Event()
    base = f"{prefix}/api/integrations/{integration_id}"

    accepted = await svc.post(f"{base}/sync")
    assert accepted.status_code == ACCEPTED, accepted.text
    await wait_async(lambda: download_seen(connector, "i1"))

    cancel_task = asyncio.create_task(svc.post(f"{base}/cancel"))
    await wait_async(lambda: cancel_requested(sm, integration_id))
    connector.block.set()
    cancelled = await cancel_task

    assert cancelled.status_code == OK, cancelled.text
    assert cancelled.json()["data"] == {
        "was_running_in_process": True,
        "lock_cleared": True,
        "runs_marked_cancelled": CANCELLED_RUN_COUNT,
    }
    await wait_async(lambda: is_cancelled_run(sm, integration_id))
    assert await latest_run_status(sm, integration_id) == "cancelled"

    runs = await svc.get(
        f"{prefix}/api/integrations/runs", params={"integration_id": integration_id}
    )
    assert runs.status_code == OK
    assert runs.json()["data"][0]["status"] == "cancelled"


async def test_ag21_status_reports_running_lock(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-21: `is_running` i `last_sync_at`/`last_sync_status` widać po zwolnieniu locka."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    async with transaction(sm) as session:
        await integrations_repo.try_lock(session, created["id"], owner="worker-1", now_ms=NOW_MS)

    locked = await svc.get(f"{prefix}/api/integrations/{created['id']}/status")
    assert locked.status_code == OK, locked.text
    assert locked.json()["data"]["is_running"] is True

    async with transaction(sm) as session:
        released = await integrations_repo.release_lock(
            session, created["id"], owner="worker-1", now_ms=NOW_MS + 10, status="success"
        )
    assert released

    done = await svc.get(f"{prefix}/api/integrations/{created['id']}/status")
    assert done.status_code == OK
    assert done.json()["data"]["is_running"] is False
    assert done.json()["data"]["last_sync_status"] == "success"
    assert done.json()["data"]["latest_run"] is None
