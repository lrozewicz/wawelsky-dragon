"""Silnik zaawansowany: anulowanie, ``full``, ``reset_required``, kontenery zniknięte (brief T8).

Testy na prawdziwej MariaDB i ``FakeConnector`` (kontrakt C8) sprawdzają artefakty w bazie:
``documents``, ``integration_containers``, ``integration_item_mappings``, ``integration_sync_runs``
i ``integration_sync_events``. Anulowanie idzie przez ``cancel_requested`` w bazie (K12 §0 pkt 5).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.repositories import integrations as repo
from app.db.repositories.documents import DocumentRow
from app.db.repositories.integrations import (
    ContainerRow,
    IntegrationRow,
    MappingRow,
    get_container,
    get_integration,
    get_mapping,
    upsert_mapping,
)
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.base import ChangeSet, RemoteItem
from app.integrations.base import Container as RemoteContainer
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import RunOutcome, SyncEngine
from app.services.ingest import UploadSource
from tests.fakes.integrations import FakeConnector, fake_load_config, make_item
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

CID = "c1"
CID2 = "c2"
CONTAINER_NAME = "Dokumenty"
CONTAINER_NAME2 = "Archiwum"
CURSOR = "cur1"
SECOND_CURSOR = "cur2"
RESET_CURSOR = "cur-reset"
WORKER_ID = "w1"
DEFAULT_TAG = "c1"
DEFAULT_META = "m1"


async def _aiter(payload: bytes) -> AsyncIterator[bytes]:
    """Strumień wejściowy dla ``UploadSource`` (wzorzec tests/integration/ingest)."""
    yield payload


class BlockingConnector(FakeConnector):
    """``FakeConnector`` blokujący pobranie wskazanego elementu do czasu ``gate`` (T8 pkt 6a/6b)."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.reached = asyncio.Event()
        self.blocked: tuple[str, str] | None = None

    async def download(
        self, cfg: object, item: RemoteItem, dest_path: Path, *, max_bytes: int
    ) -> int:
        if self.blocked is not None and (item.container_id, item.item_id) == self.blocked:
            self.reached.set()
            await self.gate.wait()
        return await super().download(cfg, item, dest_path, max_bytes=max_bytes)


@pytest.fixture
def blocking() -> Iterator[BlockingConnector]:
    """Rejestruje blokujący konektor pod typem ``fake``; po teście czyści rejestr."""
    connector = BlockingConnector()
    registry.register("fake", connector, fake_load_config)
    yield connector
    registry.clear()


async def wait_until(
    predicate: Callable[[], bool], *, timeout_s: float = 5.0, interval_s: float = 0.005
) -> None:
    """Czeka na ``predicate`` (krótkie uśpienia), aż minie ``timeout_s`` (testy anulowania)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("warunek nie został osiągnięty")
        await asyncio.sleep(interval_s)


def remote(container_id: str, name: str) -> RemoteContainer:
    """Kontener zdalny konektora."""
    return RemoteContainer(id=container_id, name=name)


async def integration_row(container: Container, integration_id: int) -> IntegrationRow:
    """Wiersz integracji (musi istnieć)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_integration(session, integration_id)
    assert row is not None
    return row


async def upload_document(
    container: Container, integration: IntegrationRow, *, item_id: str, name: str
) -> DocumentRow:
    """Wgrywa dokument usługą ingestii z ``source_ref`` elementu (stan „przed”)."""
    return await container.ingest.upload(
        integration.dataset_id,
        UploadSource(stream=_aiter(b"tresc"), filename=name),
        created_by=integration.owner_id,
        name=name,
        source_type="sharepoint",
        source_ref=f"{integration.id}:{CID}:{item_id}",
        parse=True,
    )


async def put_mapping(  # noqa: PLR0913 — skrót testowy z domyślnymi z tabeli decyzji
    container: Container,
    integration_id: int,
    *,
    container_id: str = CID,
    item_id: str,
    document_id: str | None,
    content_tag: str | None = DEFAULT_TAG,
    meta_tag: str | None = DEFAULT_META,
    name: str | None = "a.txt",
    path: str | None = "/a.txt",
) -> None:
    """Wstawia wiersz ``integration_item_mappings`` (stan wyjściowy testu)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        await upsert_mapping(
            session,
            MappingRow(
                integration_id=integration_id,
                container_id=container_id,
                item_id=item_id,
                document_id=document_id,
                content_tag=content_tag,
                meta_tag=meta_tag,
                name=name,
                path=path,
                web_url=None,
                last_status="ok",
                last_error=None,
                updated_at=TIME_MS,
            ),
        )


async def stored_container(
    container: Container, integration_id: int, container_id: str = CID
) -> ContainerRow | None:
    """Wiersz kontenera z bazy."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await get_container(session, integration_id, container_id)


async def fetch_mapping(
    container: Container, integration_id: int, item_id: str, *, container_id: str = CID
) -> MappingRow | None:
    """Mapowanie elementu z bazy."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await get_mapping(session, integration_id, container_id, item_id)


async def fetch_document(container: Container, document_id: str) -> DocumentRow | None:
    """Dokument z bazy (odczyt w osobnej transakcji)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await documents_repo.get(session, document_id)


async def document_count(container: Container) -> int:
    """Liczba wierszy ``documents`` w bazie."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return int((await session.execute(text("SELECT COUNT(*) FROM documents"))).scalar_one())


async def duplicate_source_refs(container: Container) -> list[str]:
    """``source_ref`` występujące w ``documents`` więcej niż raz (brak duplikatów = [])."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        rows = (
            await session.execute(
                text(
                    "SELECT source_ref FROM documents WHERE source_ref IS NOT NULL"
                    " GROUP BY source_ref HAVING COUNT(*) > 1"
                )
            )
        ).scalars()
    return list(rows)


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


async def run_events(container: Container, run_id: int) -> list[tuple[str, str]]:
    """Zdarzenia przebiegu jako pary ``(level, message)`` w kolejności zapisu."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        events = await repo.list_events(session, run_id)
    return [(event.level, event.message) for event in events]


async def request_cancel(container: Container, integration_id: int) -> None:
    """Ustawia ``cancel_requested=1`` w bazie (współbieżnie z przebiegiem)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        assert await repo.request_cancel(session, integration_id)


async def test_cancel_between_items_keeps_cursor_and_releases_lock(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Anulowanie w trakcie kontenera: status ``cancelled``, kursor NULL, lock zdjęty (pkt 1)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    registered_fake.containers = [remote(CID, CONTAINER_NAME)]
    registered_fake.script(
        CID,
        [
            ChangeSet(
                items=[
                    make_item(item_id="i1"),
                    make_item(item_id="i2", name="b.txt", path="/b.txt"),
                ],
                cursor=CURSOR,
            )
        ],
    )
    registered_fake.block = asyncio.Event()

    task = asyncio.create_task(engine.run(integration_id, trigger="manual", worker_id=WORKER_ID))
    await wait_until(lambda: ("download", CID, "i1") in registered_fake.calls)
    await request_cancel(container, integration_id)
    registered_fake.block.set()
    outcome = await task

    assert outcome is not None
    assert outcome.status == "cancelled"
    assert counts_of(outcome) == (1, 0, 0, 0, 0, 0)
    stored = await stored_container(container, integration_id)
    assert stored is not None
    assert (stored.delta_cursor, stored.last_sync_at) == (None, None)
    row = await integration_row(container, integration_id)
    assert (row.is_running, row.lock_owner, row.last_sync_status) == (False, None, "cancelled")
    assert ("warn", "cancelled") in await run_events(container, outcome.run_id)
    assert ("download", CID, "i2") not in registered_fake.calls
    assert await document_count(container) == 1


async def test_cancel_keeps_cursor_of_earlier_container(
    container: Container, engine: SyncEngine, blocking: BlockingConnector
) -> None:
    """Anulowanie w drugim kontenerze: kursor pierwszego zapisany, drugiego NULL (pkt 1)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    blocking.containers = [remote(CID, CONTAINER_NAME), remote(CID2, CONTAINER_NAME2)]
    blocking.script(CID, [ChangeSet(items=[make_item(item_id="i1")], cursor=CURSOR)])
    blocking.script(
        CID2,
        [
            ChangeSet(
                items=[
                    make_item(container_id=CID2, item_id="i2", name="b.txt", path="/b.txt"),
                    make_item(container_id=CID2, item_id="i3", name="c.txt", path="/c.txt"),
                ],
                cursor=SECOND_CURSOR,
            )
        ],
    )
    blocking.blocked = (CID2, "i2")

    task = asyncio.create_task(engine.run(integration_id, trigger="manual", worker_id=WORKER_ID))
    await asyncio.wait_for(blocking.reached.wait(), timeout=5)
    await request_cancel(container, integration_id)
    blocking.gate.set()
    outcome = await task

    assert outcome is not None
    assert outcome.status == "cancelled"
    first = await stored_container(container, integration_id, CID)
    second = await stored_container(container, integration_id, CID2)
    assert first is not None and first.delta_cursor == CURSOR
    assert second is not None and second.delta_cursor is None
    assert ("download", CID2, "i3") not in blocking.calls


async def test_full_trigger_resets_cursors_and_calls_changes_without_cursor(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """``trigger="full"``: kursory zerowane, ``changes(cursor=None)``, ``info`` (pkt 2)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    registered_fake.containers = [remote(CID, CONTAINER_NAME)]
    registered_fake.script(CID, [ChangeSet(items=[make_item()], cursor=CURSOR)])
    first = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)
    assert first is not None
    stored = await stored_container(container, integration_id)
    assert stored is not None and stored.delta_cursor == CURSOR

    registered_fake.script_run(CID, [ChangeSet(items=[], cursor=SECOND_CURSOR)])
    before = len(registered_fake.calls)
    outcome = await engine.run(integration_id, trigger="full", worker_id=WORKER_ID)

    assert outcome is not None
    changes_calls = [call for call in registered_fake.calls[before:] if call[0] == "changes"]
    assert changes_calls == [("changes", CID, None)]
    assert ("info", "full resync requested") in await run_events(container, outcome.run_id)
    stored = await stored_container(container, integration_id)
    assert stored is not None and stored.delta_cursor == SECOND_CURSOR


async def test_reset_required_reconciles_absent_mapping(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """``reset_required``: pełny stan {i1}, mapping i2 nieobecny → dokument i mapping znikają."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    doc_a = await upload_document(container, integration, item_id="i1", name="a.txt")
    doc_b = await upload_document(container, integration, item_id="i2", name="b.txt")
    await put_mapping(container, integration_id, item_id="i1", document_id=doc_a.id)
    await put_mapping(
        container,
        integration_id,
        item_id="i2",
        document_id=doc_b.id,
        name="b.txt",
        path="/b.txt",
        content_tag="c2",
        meta_tag="m2",
    )
    registered_fake.containers = [remote(CID, CONTAINER_NAME)]
    registered_fake.script_reset(
        CID,
        first=[ChangeSet(items=[], cursor=CURSOR)],
        after_reset=[
            ChangeSet(items=[make_item(item_id="i1")], cursor=RESET_CURSOR),
        ],
    )
    first = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)
    assert first is not None

    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)

    assert outcome is not None
    assert counts_of(outcome) == (0, 0, 0, 1, 0, 0)
    assert await fetch_document(container, doc_b.id) is None
    assert await fetch_document(container, doc_a.id) is not None
    assert await fetch_mapping(container, integration_id, "i2") is None
    assert await fetch_mapping(container, integration_id, "i1") is not None
    events = await run_events(container, outcome.run_id)
    assert ("warn", f"delta token expired, full resync of {CONTAINER_NAME}") in events
    stored = await stored_container(container, integration_id)
    assert stored is not None and stored.delta_cursor == RESET_CURSOR


async def test_reset_required_without_propagation_keeps_document(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """``reset_required`` + ``delete_propagation=False``: dokument zostaje, mapping znika."""
    integration_id = await make_integration(
        container.sessionmaker,  # type: ignore[arg-type]
        delete_propagation=False,
    )
    integration = await integration_row(container, integration_id)
    doc_b = await upload_document(container, integration, item_id="i2", name="b.txt")
    await put_mapping(
        container,
        integration_id,
        item_id="i2",
        document_id=doc_b.id,
        name="b.txt",
        path="/b.txt",
        content_tag="c2",
        meta_tag="m2",
    )
    registered_fake.containers = [remote(CID, CONTAINER_NAME)]
    registered_fake.script_reset(
        CID,
        first=[ChangeSet(items=[], cursor=CURSOR)],
        after_reset=[ChangeSet(items=[], cursor=RESET_CURSOR)],
    )
    first = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)
    assert first is not None

    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)

    assert outcome is not None
    assert counts_of(outcome) == (0, 0, 0, 1, 0, 0)
    assert await fetch_document(container, doc_b.id) is not None
    assert await fetch_mapping(container, integration_id, "i2") is None


async def test_plain_delta_does_not_delete_absent_items(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Zwykła delta (bez resetu) nie rekonsyliuje — element nieobecny zostaje (pkt 6h)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    doc_b = await upload_document(container, integration, item_id="i2", name="b.txt")
    await put_mapping(
        container,
        integration_id,
        item_id="i2",
        document_id=doc_b.id,
        name="b.txt",
        path="/b.txt",
        content_tag="c2",
        meta_tag="m2",
    )
    registered_fake.containers = [remote(CID, CONTAINER_NAME)]
    registered_fake.script(CID, [ChangeSet(items=[make_item(item_id="i1")], cursor=CURSOR)])

    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)

    assert outcome is not None
    assert outcome.status == "success"
    assert counts_of(outcome) == (1, 0, 0, 0, 0, 0)
    assert await fetch_document(container, doc_b.id) is not None
    assert await fetch_mapping(container, integration_id, "i2") is not None


async def _missing_container_case(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> tuple[int, DocumentRow, int]:
    """Wspólna scena pkt 4: kontener ``c1`` z dokumentem znika ze źródła; zwraca id/dok/run."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration, item_id="i1", name="a.txt")
    await put_mapping(container, integration_id, item_id="i1", document_id=document.id)
    registered_fake.containers = [remote(CID, CONTAINER_NAME)]
    registered_fake.script(CID, [ChangeSet(items=[], cursor=CURSOR)])
    first = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)
    assert first is not None

    registered_fake.containers = [remote(CID2, CONTAINER_NAME2)]
    registered_fake.script(CID2, [ChangeSet(items=[], cursor=SECOND_CURSOR)])
    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)
    assert outcome is not None
    return integration_id, document, outcome.run_id


async def test_missing_container_keeps_documents_by_default(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Kontener zniknięty, ``purge_excluded_containers=False``: ``warn``, dokumenty zostają."""
    integration_id, document, run_id = await _missing_container_case(
        container, engine, registered_fake
    )

    events = await run_events(container, run_id)
    assert ("warn", f"container no longer available: {CONTAINER_NAME}") in events
    assert await fetch_document(container, document.id) is not None
    assert await fetch_mapping(container, integration_id, "i1") is not None
    stored = await stored_container(container, integration_id, CID)
    assert stored is not None


async def test_missing_container_purged_when_configured(
    container: Container, registered_fake: FakeConnector
) -> None:
    """Kontener zniknięty, ``purge_excluded_containers=True``: dokument i mapping usunięte."""
    engine = SyncEngine(container, IntegrationsConfig(purge_excluded_containers=True))

    integration_id, document, _run_id = await _missing_container_case(
        container, engine, registered_fake
    )

    assert await fetch_document(container, document.id) is None
    assert await fetch_mapping(container, integration_id, "i1") is None
    stored = await stored_container(container, integration_id, CID)
    assert stored is not None


async def test_idempotent_repeat_after_cancel(
    container: Container, engine: SyncEngine, blocking: BlockingConnector
) -> None:
    """Powtórzenie po anulowaniu: brak duplikatów, ``added`` tylko dla nowych elementów (pkt 5)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    items = [
        make_item(item_id="i1", name="a.txt", path="/a.txt"),
        make_item(item_id="i2", name="b.txt", path="/b.txt"),
        make_item(item_id="i3", name="c.txt", path="/c.txt"),
        make_item(item_id="i4", name="d.txt", path="/d.txt"),
    ]
    pages = [ChangeSet(items=items, cursor=CURSOR)]
    blocking.containers = [remote(CID, CONTAINER_NAME)]
    blocking.script(CID, pages)
    blocking.script_run(CID, pages)
    blocking.blocked = (CID, "i2")

    task = asyncio.create_task(engine.run(integration_id, trigger="manual", worker_id=WORKER_ID))
    await asyncio.wait_for(blocking.reached.wait(), timeout=5)
    await request_cancel(container, integration_id)
    blocking.gate.set()
    first = await task

    assert first is not None
    assert first.status == "cancelled"
    assert counts_of(first) == (2, 0, 0, 0, 0, 0)
    stored = await stored_container(container, integration_id)
    assert stored is not None and stored.delta_cursor is None

    second = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)

    assert second is not None
    assert second.status == "success"
    assert counts_of(second) == (2, 0, 0, 0, 0, 0)
    assert await document_count(container) == 4  # noqa: PLR2004 — 4 elementy skryptu
    assert await duplicate_source_refs(container) == []
