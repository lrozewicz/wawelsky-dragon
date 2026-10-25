"""Scenariusz 09 §15 przez całe API SVC `sharepoint-sync` (brief E4-3a/T5b).

Cykl życia integracji idzie wyłącznie przez HTTP (fixture `prefix`: `""` oraz
`/sharepoint-sync-api`): ``POST /api/integrations`` → ``POST .../sync`` → ``GET .../status``
z licznikami → artefakt w datasecie (baza + ``GET /api/v1/datasets/{ds}/documents``) →
rename w źródle bez nowego parsowania → delete z propagacją → cancel długiego przebiegu.

Zadanie ``integration_sync`` wykonuje **prawdziwy** ``Worker`` z handlerem silnika (wzorzec
``tests/integration/integrations/test_scenario.py``), więc sprawdzane są realne artefakty
w bazie (``documents``, ``tasks``, ``audit_log``), a nie tylko kody HTTP. Bez ``sleep`` na
sztywno — pętla ``wait_async`` z conftest T5a.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import RunRow
from app.db.uow import transaction
from app.integrations.base import ChangeSet, RemoteItem
from app.integrations.base import Container as RemoteContainer
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import SyncEngine
from app.worker.handlers.integration_sync import make_handler
from app.worker.loop import Worker
from tests.contract.hub_compat.sharepoint.conftest import (
    CreateIntegration,
    SeedDataset,
    SharePointFake,
    wait_async,
)
from tests.fakes.integrations import make_item

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

OK = 200
ACCEPTED = 202
CID = "c1"
CID_NAME = "Dokumenty"
WORKER_SHUTDOWN_S = 15


@pytest.fixture
async def worker(container: Container) -> AsyncIterator[None]:
    """Prawdziwy `Worker` z handlerem `integration_sync` (poll z `worker_poll_s` = 0.02)."""
    engine = SyncEngine(container, IntegrationsConfig())
    instance = Worker(container, {"integration_sync": make_handler(engine)})
    stop = asyncio.Event()
    runner = asyncio.create_task(instance.run(stop))
    yield
    stop.set()
    await asyncio.wait_for(runner, timeout=WORKER_SHUTDOWN_S)


def item(
    item_id: str, name: str, path: str, *, meta_tag: str = "m1", deleted: bool = False
) -> RemoteItem:
    """Element źródła w kontenerze `c1` (kontrakt C8)."""
    return make_item(
        container_id=CID,
        item_id=item_id,
        name=name,
        path=path,
        content_tag="c1",
        meta_tag=meta_tag,
        deleted=deleted,
    )


async def download_seen(connector: SharePointFake, item_id: str) -> bool:
    """Czy konektor zaczął pobierać element (przebieg realnie trwa)."""
    return ("download", CID, item_id) in connector.calls


async def status_data(svc: httpx.AsyncClient, base: str) -> dict[str, Any]:
    """`data` z `GET .../status` (kontrakt E4-3a §4)."""
    response = await svc.get(f"{base}/status")
    assert response.status_code == OK, response.text
    return dict(response.json()["data"])


async def is_running(svc: httpx.AsyncClient, base: str) -> bool:
    """`is_running` z trasy statusu (lock zajęty w trakcie przebiegu)."""
    return bool((await status_data(svc, base))["is_running"])


async def fetch_latest_run(
    sm: async_sessionmaker[AsyncSession], integration_id: int
) -> RunRow | None:
    """Najnowszy przebieg integracji z bazy."""
    async with transaction(sm) as session:
        return await integrations_repo.latest_run(session, integration_id)


async def run_cancelled(sm: async_sessionmaker[AsyncSession], integration_id: int) -> bool:
    """Czy najnowszy przebieg jest już zamknięty statusem `cancelled`."""
    run = await fetch_latest_run(sm, integration_id)
    return run is not None and run.status == "cancelled"


async def finished_run(
    sm: async_sessionmaker[AsyncSession], integration_id: int, *, after: int
) -> RunRow:
    """Czeka na nowy (id > `after`) przebieg w stanie końcowym i zwraca jego wiersz."""
    await wait_async(lambda: new_run_finished(sm, integration_id, after=after))
    run = await fetch_latest_run(sm, integration_id)
    assert run is not None
    return run


async def new_run_finished(
    sm: async_sessionmaker[AsyncSession], integration_id: int, *, after: int
) -> bool:
    """Czy jest przebieg nowszy niż `after`, który wyszedł już ze stanu `running`."""
    run = await fetch_latest_run(sm, integration_id)
    return run is not None and run.id > after and run.status != "running"


async def cancel_requested(sm: async_sessionmaker[AsyncSession], integration_id: int) -> bool:
    """Czy przebieg dostał żądanie anulowania (K12 §5)."""
    async with transaction(sm) as session:
        return await integrations_repo.is_cancel_requested(session, integration_id)


async def container_cursor(sm: async_sessionmaker[AsyncSession], integration_id: int) -> str | None:
    """`delta_cursor` kontenera `c1` (anulowany przebieg nie zapisuje kursora)."""
    async with transaction(sm) as session:
        row = await integrations_repo.get_container(session, integration_id, CID)
    assert row is not None
    return row.delta_cursor


async def document_by_ref(sm: async_sessionmaker[AsyncSession], ref: str) -> dict[str, Any] | None:
    """Wiersz dokumentu po `source_ref` (artefakt synchronizacji)."""
    async with transaction(sm) as session:
        row = (
            (
                await session.execute(
                    text("SELECT id, name, source_type FROM documents WHERE source_ref = :ref"),
                    {"ref": ref},
                )
            )
            .mappings()
            .first()
        )
    return None if row is None else dict(row)


async def documents_in_dataset(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> int:
    """Liczba wierszy `documents` datasetu."""
    async with transaction(sm) as session:
        return int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM documents WHERE dataset_id = :id"),
                    {"id": dataset_id},
                )
            ).scalar_one()
        )


async def parse_task_count(sm: async_sessionmaker[AsyncSession]) -> int:
    """Liczba zadań `parse_document` (świeża baza na test)."""
    async with transaction(sm) as session:
        return int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM tasks WHERE task_type = 'parse_document'")
                )
            ).scalar_one()
        )


async def dataset_summary(
    svc: httpx.AsyncClient, prefix: str, dataset_id: str
) -> dict[str, Any] | None:
    """Wiersz `GET /api/datasets` datasetu (licznik `document_count`, kontrakt §4)."""
    response = await svc.get(f"{prefix}/api/datasets")
    assert response.status_code == OK, response.text
    for row in response.json()["data"]:
        if row["id"] == dataset_id:
            return dict(row)
    return None


async def sync_audit(
    sm: async_sessionmaker[AsyncSession], integration_id: int
) -> list[dict[str, Any]]:
    """`details` wpisów `integration_sync_requested` (kolumna JSON) w kolejności wstawienia."""
    async with transaction(sm) as session:
        raw = (
            (
                await session.execute(
                    text(
                        "SELECT details FROM audit_log"
                        " WHERE action = 'integration_sync_requested' AND target_id = :id"
                        " ORDER BY id"
                    ),
                    {"id": str(integration_id)},
                )
            )
            .scalars()
            .all()
        )
    return [value if isinstance(value, dict) else json.loads(str(value)) for value in raw]


async def test_scenario_09_15_full_lifecycle(  # noqa: PLR0913, PLR0915, PLR0917 — scenariusz
    svc: httpx.AsyncClient,
    prefix: str,
    connector: SharePointFake,
    container: Container,
    create_integration: CreateIntegration,
    seed_dataset: SeedDataset,
    sm: async_sessionmaker[AsyncSession],
    worker: None,
) -> None:
    """Create → sync → status → artefakt → rename → delete → cancel przez API SVC (§15)."""
    owner_id, dataset_id = await seed_dataset()
    connector.containers = [RemoteContainer(id=CID, name=CID_NAME)]
    connector.script(CID, [ChangeSet(items=[item("i1", "a.txt", "/a.txt")], cursor="cur-1")])
    connector.block = asyncio.Event()  # przebieg utknie na pobraniu (krok 2)

    # 1. utworzenie integracji: 201 na datasecie z `seed_dataset`
    created = await create_integration(dataset_id)
    integration_id = int(created["id"])
    base = f"{prefix}/api/integrations/{integration_id}"
    assert created["dataset_id"] == dataset_id

    # 2. sync: 202 `{started, full}`; w trakcie `is_running`, po zwolnieniu bloku run `success`
    accepted = await svc.post(f"{base}/sync")
    assert accepted.status_code == ACCEPTED, accepted.text
    assert accepted.json() == {"data": {"started": True, "full": False}}
    await wait_async(lambda: is_running(svc, base))
    connector.block.set()
    first = await finished_run(sm, integration_id, after=0)
    assert (first.status, first.added, first.failed) == ("success", 1, 0)

    # 3. status i przebiegi przez API: liczniki i zdarzenia przebiegu
    status = await status_data(svc, base)
    latest = status["latest_run"]
    assert latest is not None
    assert (latest["id"], latest["status"]) == (first.id, "success")
    assert (latest["added"], latest["deleted"]) == (1, 0)
    runs = await svc.get(
        f"{prefix}/api/integrations/runs", params={"integration_id": integration_id}
    )
    assert runs.status_code == OK, runs.text
    assert [run["id"] for run in runs.json()["data"]] == [first.id]
    events = await svc.get(f"{prefix}/api/integrations/runs/{first.id}/events")
    assert events.status_code == OK, events.text
    assert len(events.json()["data"]) > 0
    assert await sync_audit(sm, integration_id) == [{"full": False, "wait": False}]

    # 4. artefakt: dokument w datasecie — baza, licznik SVC i API RAGFlow
    ref = f"{integration_id}:{CID}:i1"
    stored = await document_by_ref(sm, ref)
    assert stored is not None
    document_id = str(stored["id"])
    assert stored["source_type"] == "sharepoint"
    summary = await dataset_summary(svc, prefix, dataset_id)
    assert summary is not None
    assert summary["document_count"] == 1
    assert container.users is not None and container.api_keys is not None
    key = await container.api_keys.create(
        container.users.principal_of(await container.users.get(owner_id))
    )
    listed = await svc.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"Authorization": f"Bearer {key.token}"},
    )
    assert listed.status_code == OK, listed.text
    assert [(doc["id"], doc["source_type"]) for doc in listed.json()["data"]["docs"]] == [
        (document_id, "sharepoint")
    ]

    # 5. rename w źródle: ten sam `content_tag`, nowa nazwa → brak nowego parsowania
    connector.script(
        CID,
        [ChangeSet(items=[item("i1", "a2.txt", "/a2.txt", meta_tag="m2")], cursor="cur-2")],
    )
    accepted = await svc.post(f"{base}/sync")
    assert accepted.status_code == ACCEPTED, accepted.text
    renamed = await finished_run(sm, integration_id, after=first.id)
    assert (renamed.status, renamed.renamed, renamed.added) == ("success", 1, 0)
    updated = await document_by_ref(sm, ref)
    assert updated is not None
    assert (updated["id"], updated["name"]) == (document_id, "a2.txt")
    assert await parse_task_count(sm) == 1

    # 6. delete w źródle: dokument i licznik datasetu znikają
    connector.script(
        CID,
        [ChangeSet(items=[item("i1", "a2.txt", "/a2.txt", deleted=True)], cursor="cur-3")],
    )
    accepted = await svc.post(f"{base}/sync")
    assert accepted.status_code == ACCEPTED, accepted.text
    deleted = await finished_run(sm, integration_id, after=renamed.id)
    assert (deleted.status, deleted.deleted) == ("success", 1)
    assert await documents_in_dataset(sm, dataset_id) == 0
    assert await document_by_ref(sm, ref) is None
    summary = await dataset_summary(svc, prefix, dataset_id)
    assert summary is not None
    assert summary["document_count"] == 0

    # 7. cancel długiego przebiegu: nowe pliki + blokada pobrania (anulowanie między elementami)
    connector.script(
        CID,
        [
            ChangeSet(
                items=[item("i9", "c.txt", "/c.txt"), item("i10", "d.txt", "/d.txt")],
                cursor="cur-4",
            )
        ],
    )
    connector.block = asyncio.Event()
    cursor_before = await container_cursor(sm, integration_id)
    accepted = await svc.post(f"{base}/sync")
    assert accepted.status_code == ACCEPTED, accepted.text
    await wait_async(lambda: download_seen(connector, "i9"))
    cancel_task = asyncio.create_task(svc.post(f"{base}/cancel"))
    await wait_async(lambda: cancel_requested(sm, integration_id))
    connector.block.set()
    cancelled = await cancel_task
    assert cancelled.status_code == OK, cancelled.text
    assert cancelled.json()["data"]["lock_cleared"] is True
    await wait_async(lambda: run_cancelled(sm, integration_id))
    assert await container_cursor(sm, integration_id) == cursor_before  # anulowany bez kursora
    status = await status_data(svc, base)
    assert status["latest_run"] is not None
    assert status["latest_run"]["status"] == "cancelled"
