"""Scenariusz przekrojowy cyklu integracji (brief E4-1/T10, wymaganie 1).

Jeden przebieg życia integracji na ``FakeConnector`` bez HTTP: zlecenie przez kolejkę
(``IntegrationRunsService.request_sync``) → wykonanie przez prawdziwy ``Worker`` z handlerem
``integration_sync`` → dokumenty i mapowania w bazie → rename w źródle bez re-parsowania →
delete z propagacją → cancel w trakcie długiego przebiegu → konflikt przy drugim zleceniu.

Sprawdzane są artefakty w bazie (``documents``, ``integration_item_mappings``,
``integration_containers``, ``tasks``, ``datasets.document_count``), nie tylko kod wyjścia.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import Conflict
from app.db.repositories import documents as documents_repo
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.documents import DocumentRow
from app.db.repositories.integrations import ContainerRow, IntegrationRow, MappingRow, RunRow
from app.db.uow import transaction
from app.integrations.base import ChangeSet
from app.integrations.base import Container as RemoteContainer
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import SyncEngine
from app.services.integration_runs import IntegrationRunsService
from app.worker.handlers.integration_sync import make_handler
from app.worker.loop import Worker
from tests.fakes.clock import FrozenClock
from tests.fakes.integrations import FakeConnector, make_item
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

CID = "c1"
CONTAINER_NAME = "Dokumenty"
SCAN_INTERVAL_S = 30
RUN_TIMEOUT_S = 30.0
POLL_S = 0.01
WAIT_TIMEOUT_S = 5.0
WORKER_SHUTDOWN_S = 15


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie z ``FrozenClock`` i szybkim pollem workera (wymaganie 1)."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path), "worker_poll_s": 0.02}),
        clock=FrozenClock(TIME_MS),
    )
    await instance.start()
    yield instance
    await instance.aclose()


async def wait_async(
    predicate: Callable[[], Awaitable[bool]], *, timeout_s: float = WAIT_TIMEOUT_S
) -> None:
    """Czeka na asynchroniczny warunek (krótkie uśpienia) do ``timeout_s``."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not await predicate():
        if loop.time() >= deadline:
            raise AssertionError("warunek nie został osiągnięty")
        await asyncio.sleep(POLL_S)


def doc_ref(integration_id: int, item_id: str) -> str:
    """``source_ref`` dokumentu elementu (kontrakt C5)."""
    return f"{integration_id}:{CID}:{item_id}"


def wd_source(integration_id: int, item_id: str, path: str) -> dict[str, object]:
    """``meta_fields.wd_source`` elementu (kontrakt C5)."""
    return {
        "integration_id": integration_id,
        "type": "fake",
        "container_id": CID,
        "item_id": item_id,
        "path": path,
        "web_url": None,
    }


async def task_status(container: Container, task_id: str) -> str:
    """Status zadania po ``public_id``."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        value = (
            await session.execute(
                text("SELECT status FROM tasks WHERE public_id = :id"), {"id": task_id}
            )
        ).scalar()
    return str(value)


async def parse_task_count(container: Container) -> int:
    """Liczba zadań ``parse_document`` w bazie (świeża baza na test)."""
    sql = text("SELECT COUNT(*) FROM tasks WHERE task_type = 'parse_document'")
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return int((await session.execute(sql)).scalar_one())


async def dataset_document_count(container: Container, integration_id: int) -> int:
    """``datasets.document_count`` datasetu integracji."""
    sql = text(
        "SELECT document_count FROM datasets"
        " WHERE id = (SELECT dataset_id FROM integrations WHERE id = :id)"
    )
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return int((await session.execute(sql, {"id": integration_id})).scalar_one())


async def documents_by_ref(container: Container, integration_id: int) -> dict[str, str]:
    """Mapa ``source_ref -> document_id`` dla dokumentów datasetu integracji."""
    sql = text(
        "SELECT id, source_ref FROM documents"
        " WHERE dataset_id = (SELECT dataset_id FROM integrations WHERE id = :id)"
    )
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        rows: list[RowMapping] = (
            (await session.execute(sql, {"id": integration_id})).mappings().all()
        )
    return {str(row["source_ref"]): str(row["id"]) for row in rows}


async def fetch_document(container: Container, document_id: str) -> DocumentRow | None:
    """Dokument z bazy (odczyt w osobnej transakcji)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await documents_repo.get(session, document_id)


async def list_mappings(container: Container, integration_id: int) -> list[MappingRow]:
    """Mappingi kontenera ``c1`` integracji."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await integrations_repo.list_mappings(session, integration_id, CID)


async def container_row(container: Container, integration_id: int) -> ContainerRow | None:
    """Wiersz kontenera ``c1`` z bazy."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await integrations_repo.get_container(session, integration_id, CID)


async def integration_row(container: Container, integration_id: int) -> IntegrationRow:
    """Wiersz integracji (musi istnieć)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await integrations_repo.get_integration(session, integration_id)
    assert row is not None
    return row


async def lock_released(container: Container, integration_id: int) -> bool:
    """Czy przebieg zwolnił lock (``is_running=0``)."""
    return not (await integration_row(container, integration_id)).is_running


async def task_done(container: Container, task_id: str) -> bool:
    """Czy zadanie zostało zakończone statusem ``done``."""
    return await task_status(container, task_id) == "done"


async def completed_run(
    service: IntegrationRunsService,
    container: Container,
    integration_id: int,
    *,
    since_run_id: int | None,
) -> RunRow:
    """Czeka na zakończony przebieg i zwolniony lock — kolejne zlecenie nie może dostać 409."""
    run = await service.wait_for_run(
        integration_id, since_run_id=since_run_id, timeout_s=RUN_TIMEOUT_S
    )
    assert run is not None
    await wait_async(lambda: lock_released(container, integration_id))
    return run


async def is_cancel_requested(container: Container, integration_id: int) -> bool:
    """Czy przebieg dostał żądanie anulowania."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await integrations_repo.is_cancel_requested(session, integration_id)


async def download_seen_since(fake: FakeConnector, start: int, item_id: str) -> bool:
    """Czy po indeksie ``start`` konektor wywołał ``download`` elementu."""
    return ("download", CID, item_id) in fake.calls[start:]


def script_container(fake: FakeConnector, items: list, cursor: str) -> None:
    """Ustawia pojedyncze przejście ``changes`` kontenera ``c1`` (kontrakt C8)."""
    fake.containers = [RemoteContainer(id=CID, name=CONTAINER_NAME)]
    fake.script(CID, [ChangeSet(items=items, cursor=cursor)])


async def test_integration_lifecycle_scenario(  # noqa: PLR0915 — jeden scenariusz przekrojowy
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Pełny cykl: zlecenie → worker → artefakty → rename → delete → cancel → 409."""
    integration_id = await make_integration(
        container.sessionmaker,  # type: ignore[arg-type]
        scan_interval_seconds=SCAN_INTERVAL_S,
        name="Scenariusz",
    )
    service = IntegrationRunsService(container, IntegrationsConfig())
    service._poll_s = POLL_S  # krótki poll (wymaganie 1)
    script_container(
        registered_fake,
        [
            make_item(item_id="i1", name="a.txt", path="/a.txt"),
            make_item(item_id="i2", name="b.txt", path="/b.txt"),
        ],
        "cur1",
    )

    # a) zlecenie: zadanie integration_sync w kolejce, jeszcze nie wykonane
    task_id = await service.request_sync(integration_id, full=False)
    assert await task_status(container, task_id) == "queued"

    # b) worker wykonuje zadanie: run success, added=2
    worker = Worker(container, {"integration_sync": make_handler(engine)})
    stop = asyncio.Event()
    worker_task = asyncio.create_task(worker.run(stop))
    try:
        run = await completed_run(service, container, integration_id, since_run_id=None)
        assert (run.status, run.added, run.failed) == ("success", 2, 0)
        await wait_async(lambda: task_done(container, task_id))

        # c) artefakty w bazie: 2 dokumenty sharepoint, mapowania ok, 2 zadania parse_document
        refs = await documents_by_ref(container, integration_id)
        assert set(refs) == {doc_ref(integration_id, "i1"), doc_ref(integration_id, "i2")}
        for item_id, path in (("i1", "/a.txt"), ("i2", "/b.txt")):
            document = await fetch_document(container, refs[doc_ref(integration_id, item_id)])
            assert document is not None
            assert document.source_type == "sharepoint"
            assert document.meta_fields["wd_source"] == wd_source(integration_id, item_id, path)
        mappings = await list_mappings(container, integration_id)
        assert [(m.item_id, m.last_status) for m in mappings] == [("i1", "ok"), ("i2", "ok")]
        assert all(m.document_id == refs[doc_ref(integration_id, m.item_id)] for m in mappings)
        assert await parse_task_count(container) == 2  # noqa: PLR2004 — 2 elementy skryptu

        # d) rename w źródle: nowa nazwa, ten sam dokument, bez nowego parse_document
        script_container(
            registered_fake,
            [
                make_item(
                    item_id="i1",
                    name="a2.txt",
                    path="/a2.txt",
                    content_tag="c1",
                    meta_tag="m2",
                )
            ],
            "cur2",
        )
        await service.request_sync(integration_id, full=False)
        renamed_run = await completed_run(service, container, integration_id, since_run_id=run.id)
        assert (renamed_run.status, renamed_run.renamed) == ("success", 1)
        document = await fetch_document(container, refs[doc_ref(integration_id, "i1")])
        assert document is not None
        assert (document.id, document.name) == (refs[doc_ref(integration_id, "i1")], "a2.txt")
        mapping = next(
            m for m in await list_mappings(container, integration_id) if m.item_id == "i1"
        )
        assert (mapping.document_id, mapping.name, mapping.path) == (
            refs[doc_ref(integration_id, "i1")],
            "a2.txt",
            "/a2.txt",
        )
        assert await parse_task_count(container) == 2  # noqa: PLR2004 — bez nowego parsowania

        # e) delete w źródle z propagacją: dokument i mapowanie znikają, licznik datasetu spada
        script_container(
            registered_fake,
            [make_item(item_id="i1", name="a2.txt", path="/a2.txt", deleted=True)],
            "cur3",
        )
        await service.request_sync(integration_id, full=False)
        deleted_run = await completed_run(
            service, container, integration_id, since_run_id=renamed_run.id
        )
        assert (deleted_run.status, deleted_run.deleted) == ("success", 1)
        remaining = await documents_by_ref(container, integration_id)
        assert set(remaining) == {doc_ref(integration_id, "i2")}
        assert await fetch_document(container, refs[doc_ref(integration_id, "i1")]) is None
        mapping_ids = [m.item_id for m in await list_mappings(container, integration_id)]
        assert mapping_ids == ["i2"]
        assert await dataset_document_count(container, integration_id) == 1

        # f) cancel w trakcie długiego przebiegu + g) drugie zlecenie → Conflict (409)
        script_container(
            registered_fake,
            [
                make_item(item_id="i1", name="a3.txt", path="/a3.txt"),
                make_item(item_id="i2", name="b.txt", path="/b.txt"),
            ],
            "cur4",
        )
        registered_fake.block = asyncio.Event()
        mark = len(registered_fake.calls)  # tylko pobrania bieżącego przebiegu
        await service.request_sync(integration_id, full=True)
        await wait_async(lambda: download_seen_since(registered_fake, mark, "i1"))

        # g) przebieg trwa (is_running=1) → kolejne zlecenie to Conflict
        with pytest.raises(Conflict):
            await service.request_sync(integration_id, full=False)

        # anulowanie w tle; żądanie musi trafić do bazy, zanim pętla dojdzie do kolejnego elementu
        cancel_task = asyncio.create_task(service.cancel(integration_id))
        await wait_async(lambda: is_cancel_requested(container, integration_id))
        registered_fake.block.set()
        cancelled_run = await service.wait_for_run(
            integration_id, since_run_id=deleted_run.id, timeout_s=RUN_TIMEOUT_S
        )
        cancel_result = await cancel_task

        assert cancelled_run is not None
        assert cancelled_run.status == "cancelled"
        assert cancel_result.was_running_in_process is True
        assert cancel_result.lock_cleared is True
        stored = await container_row(container, integration_id)
        assert stored is not None
        assert stored.delta_cursor is None  # anulowany przebieg nie zapisuje kursora
        row = await integration_row(container, integration_id)
        assert (row.is_running, row.lock_owner) == (False, None)
    finally:
        stop.set()
        await asyncio.wait_for(worker_task, timeout=WORKER_SHUTDOWN_S)
