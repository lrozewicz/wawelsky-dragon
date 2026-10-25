"""Tabela decyzji 09 §6 — jeden test na wiersz, na ``FakeConnector`` (brief T6, kontrakt C5).

Każdy test sprawdza artefakty w bazie: ``documents`` (nazwa, ``source_type``, ``source_ref``,
``meta_fields.wd_source``, ``run``), ``integration_item_mappings``, liczbę zadań
``parse_document``, liczniki przebiegu w ``integration_sync_runs`` i zdarzenia
w ``integration_sync_events``. Pliki tymczasowe pobrania leżą w ``<storage_root>/tmp``.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.repositories.documents import DocumentRow
from app.db.repositories.integrations import (
    EventRow,
    IntegrationRow,
    MappingRow,
    RunRow,
    get_integration,
    get_mapping,
    get_run,
    list_events,
    upsert_mapping,
)
from app.db.uow import transaction
from app.integrations.base import ChangeSet
from app.integrations.base import Container as RemoteContainer
from app.integrations.engine import RunOutcome, SyncEngine
from app.services.ingest import UploadSource
from tests.fakes.integrations import FakeConnector, make_item
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

CID = "c1"
CONTAINER_NAME = "Dokumenty"
CURSOR = "cur1"
ITEM_ID = "i1"
WORKER_ID = "w1"
BOGUS_DOCUMENT_ID = "0" * 32
MAX_SIZE_BYTES = 10
START_EVENT = f"container start: {CONTAINER_NAME}"
DONE_EVENT = f"container done: {CONTAINER_NAME}"


async def _aiter(payload: bytes) -> AsyncIterator[bytes]:
    """Strumień wejściowy dla ``UploadSource`` (wzorzec tests/integration/ingest)."""
    yield payload


async def upload_document(
    container: Container,
    integration: IntegrationRow,
    *,
    name: str = "a.txt",
    content: bytes = b"stara tresc",
) -> DocumentRow:
    """Wgrywa dokument usługą ingestii i oznacza jego zadanie parsowania jako ``done``.

    Stan „przed” dla wierszy 6-9: dokument istnieje, ale nie jest w trakcie parsowania
    (inaczej ``replace`` zgłosiłby ``OperationNotAllowed``).
    """
    document = await container.ingest.upload(
        integration.dataset_id,
        UploadSource(stream=_aiter(content), filename=name),
        created_by=integration.owner_id,
        name=name,
        source_type="sharepoint",
        source_ref=source_ref(integration.id, ITEM_ID),
        parse=True,
    )
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        await session.execute(
            text("UPDATE tasks SET status = 'done' WHERE document_id = :document_id"),
            {"document_id": document.id},
        )
    return document


async def put_mapping(  # noqa: PLR0913 — skrót testowy z domyślnymi z tabeli decyzji
    container: Container,
    integration_id: int,
    *,
    item_id: str = ITEM_ID,
    document_id: str | None,
    content_tag: str | None = "c1",
    meta_tag: str | None = "m1",
    name: str | None = "a.txt",
    path: str | None = "/a.txt",
    web_url: str | None = None,
    last_status: str = "ok",
    last_error: str | None = None,
) -> None:
    """Wstawia wiersz ``integration_item_mappings`` (stan wyjściowy testu)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        await upsert_mapping(
            session,
            MappingRow(
                integration_id=integration_id,
                container_id=CID,
                item_id=item_id,
                document_id=document_id,
                content_tag=content_tag,
                meta_tag=meta_tag,
                name=name,
                path=path,
                web_url=web_url,
                last_status=last_status,
                last_error=last_error,
                updated_at=TIME_MS,
            ),
        )


def source_ref(integration_id: int, item_id: str) -> str:
    """``source_ref`` dokumentu wg kontraktu C5."""
    return f"{integration_id}:{CID}:{item_id}"


def wd_source(integration_id: int, *, path: str = "/a.txt", web_url: str | None = None) -> dict:
    """``meta_fields.wd_source`` elementu ``i1`` wg kontraktu C5."""
    return {
        "integration_id": integration_id,
        "type": "fake",
        "container_id": CID,
        "item_id": ITEM_ID,
        "path": path,
        "web_url": web_url,
    }


async def start_run(
    engine: SyncEngine, fake: FakeConnector, integration_id: int, *, items: list, cursor=CURSOR
) -> RunOutcome:
    """Skryptuje jedno przejście ``changes`` i uruchamia silnik; wynik musi istnieć."""
    fake.containers = [RemoteContainer(id=CID, name=CONTAINER_NAME)]
    fake.script(CID, [ChangeSet(items=items, cursor=cursor)])
    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)
    assert outcome is not None
    return outcome


async def fetch_document(container: Container, document_id: str) -> DocumentRow | None:
    """Dokument z bazy (odczyt w osobnej transakcji)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await documents_repo.get(session, document_id)


async def integration_row(container: Container, integration_id: int) -> IntegrationRow:
    """Wiersz integracji (musi istnieć) — potrzebny do wgrania dokumentu wzorcowego."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_integration(session, integration_id)
    assert row is not None
    return row


async def fetch_mapping(
    container: Container, integration_id: int, item_id: str = ITEM_ID
) -> MappingRow | None:
    """Mapowanie elementu z bazy."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await get_mapping(session, integration_id, CID, item_id)


async def parse_task_count(
    container: Container, document_id: str, *, status: str | None = None
) -> int:
    """Liczba zadań ``parse_document`` dokumentu (opcjonalnie o danym statusie)."""
    sql = (
        "SELECT COUNT(*) FROM tasks"
        " WHERE document_id = :document_id AND task_type = 'parse_document'"
    )
    params: dict[str, object] = {"document_id": document_id}
    if status is not None:
        sql += " AND status = :status"
        params["status"] = status
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return int((await session.execute(text(sql), params)).scalar_one())


async def document_count(container: Container) -> int:
    """Liczba wierszy ``documents`` w bazie."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return int((await session.execute(text("SELECT COUNT(*) FROM documents"))).scalar_one())


async def run_row(container: Container, run_id: int) -> RunRow:
    """Wiersz przebiegu (musi istnieć)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await get_run(session, run_id)
    assert row is not None
    return row


async def event_pairs(container: Container, run_id: int) -> list[tuple[str, str]]:
    """Zdarzenia przebiegu jako pary ``(level, message)`` w kolejności zapisu."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        events: list[EventRow] = await list_events(session, run_id)
    return [(event.level, event.message) for event in events]


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


def run_counts(row: RunRow) -> tuple[int, ...]:
    """Liczniki zapisane w wierszu przebiegu (ten sam układ co ``counts_of``)."""
    return (row.added, row.updated, row.renamed, row.deleted, row.failed, row.skipped)


def tmp_dir(container: Container) -> Path:
    """Katalog plików tymczasowych pobrania (``<storage_root>/tmp``)."""
    return Path(container.settings.storage_root) / "tmp"


async def test_row1_folder_is_skipped(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 1: ``is_folder`` — pominięty bez zdarzenia, bez mapowania i dokumentu."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(is_folder=True)]
    )

    assert counts_of(outcome) == (0, 0, 0, 0, 0, 0)
    assert await fetch_mapping(container, integration_id) is None
    assert await document_count(container) == 0
    assert await event_pairs(container, outcome.run_id) == [
        ("info", START_EVENT),
        ("info", DONE_EVENT),
    ]


async def test_row2_deleted_item_with_mapping_removes_document(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 2: ``deleted`` + mapowanie + propagacja — dokument i mapowanie znikają."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(container, integration_id, document_id=document.id)

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(deleted=True)]
    )

    assert counts_of(outcome) == (0, 0, 0, 1, 0, 0)
    assert await fetch_document(container, document.id) is None
    assert await fetch_mapping(container, integration_id) is None
    assert ("info", "deleted") in await event_pairs(container, outcome.run_id)
    assert run_counts(await run_row(container, outcome.run_id)) == (0, 0, 0, 1, 0, 0)


async def test_row2_deleted_without_propagation_keeps_document(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 2 (``delete_propagation=False``): dokument zostaje, mapowanie znika (09 §6)."""
    integration_id = await make_integration(
        container.sessionmaker,
        delete_propagation=False,  # type: ignore[arg-type]
    )
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(container, integration_id, document_id=document.id)

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(deleted=True)]
    )

    assert counts_of(outcome) == (0, 0, 0, 1, 0, 0)
    assert await fetch_document(container, document.id) is not None
    assert await fetch_mapping(container, integration_id) is None
    assert ("info", "deleted") in await event_pairs(container, outcome.run_id)


async def test_row2_delete_failure_warns_and_keeps_mapping(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 2 (błąd usuwania): ``warn`` z ``file_path``, mapowanie zostaje, licznik bez zmian."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    await put_mapping(container, integration_id, document_id=BOGUS_DOCUMENT_ID, path="/a.txt")

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(deleted=True)]
    )

    assert counts_of(outcome) == (0, 0, 0, 0, 0, 0)
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert mapping.document_id == BOGUS_DOCUMENT_ID
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        events = await list_events(session, outcome.run_id)
    warns = [event for event in events if event.level == "warn"]
    assert len(warns) == 1
    assert warns[0].file_path == "/a.txt"


async def test_row3_deleted_item_without_mapping_is_skipped(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 3: ``deleted`` bez mapowania — pominięty, bez mapowania i licznika."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(deleted=True)]
    )

    assert counts_of(outcome) == (0, 0, 0, 0, 0, 0)
    assert await fetch_mapping(container, integration_id) is None
    assert await document_count(container) == 0
    assert await event_pairs(container, outcome.run_id) == [
        ("info", START_EVENT),
        ("info", DONE_EVENT),
    ]


async def test_row4_ignored_extension_is_skipped_without_event(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 4: rozszerzenie z ``ignored_extensions`` — pominięte bez zdarzenia, ``skipped=1``."""
    integration_id = await make_integration(
        container.sessionmaker,
        ignored_extensions=["txt"],  # type: ignore[arg-type]
    )

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(name="a.TXT")]
    )

    assert counts_of(outcome) == (0, 0, 0, 0, 0, 1)
    assert await fetch_mapping(container, integration_id) is None
    assert await document_count(container) == 0
    assert await event_pairs(container, outcome.run_id) == [
        ("info", START_EVENT),
        ("info", DONE_EVENT),
    ]


async def test_row5_too_large_file_warns_and_skips(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 5: ``size > max_file_size_bytes`` — ``warn`` z ``file_path``, dokument bez zmian."""
    integration_id = await make_integration(
        container.sessionmaker,  # type: ignore[arg-type]
        max_file_size_bytes=MAX_SIZE_BYTES,
    )

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(size=MAX_SIZE_BYTES + 1)]
    )

    assert counts_of(outcome) == (0, 0, 0, 0, 0, 1)
    assert await fetch_mapping(container, integration_id) is None
    assert await document_count(container) == 0
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        events = await list_events(session, outcome.run_id)
    warns = [event for event in events if event.level == "warn"]
    assert len(warns) == 1
    assert warns[0].message == f"file too large ({MAX_SIZE_BYTES + 1} B > {MAX_SIZE_BYTES} B)"
    assert warns[0].file_path == "/a.txt"


async def test_row6_unchanged_item_does_nothing(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 6: mapping ``ok``, równe tagi, nazwa i ścieżka — brak akcji i liczników."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(container, integration_id, document_id=document.id)

    outcome = await start_run(engine, registered_fake, integration_id, items=[make_item()])

    assert counts_of(outcome) == (0, 0, 0, 0, 0, 0)
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert mapping.updated_at == TIME_MS
    fresh = await fetch_document(container, document.id)
    assert fresh is not None
    assert (fresh.name, fresh.location, fresh.content_hash) == (
        document.name,
        document.location,
        document.content_hash,
    )
    assert await parse_task_count(container, document.id) == 1
    assert await parse_task_count(container, document.id, status="queued") == 0
    assert await event_pairs(container, outcome.run_id) == [
        ("info", START_EVENT),
        ("info", DONE_EVENT),
    ]


async def test_row7_rename_changes_name_without_reparse(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 7: sam rename — ``documents.name`` nowa, plik i parsowanie bez zmian."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(container, integration_id, document_id=document.id)

    outcome = await start_run(
        engine,
        registered_fake,
        integration_id,
        items=[make_item(name="b.txt", path="/dir/b.txt", content_tag="c1", meta_tag="m1")],
    )

    assert counts_of(outcome) == (0, 0, 1, 0, 0, 0)
    fresh = await fetch_document(container, document.id)
    assert fresh is not None
    assert fresh.name == "b.txt"
    assert (fresh.location, fresh.content_hash) == (document.location, document.content_hash)
    assert fresh.meta_fields["wd_source"] == wd_source(integration_id, path="/dir/b.txt")
    assert await parse_task_count(container, document.id) == 1
    assert await parse_task_count(container, document.id, status="queued") == 0
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert (mapping.document_id, mapping.name, mapping.path) == (document.id, "b.txt", "/dir/b.txt")
    assert ("info", "renamed") in await event_pairs(container, outcome.run_id)


async def test_row7_extension_change_falls_back_to_replace(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 7 → 9: zmiana rozszerzenia to ``ValidationFailed`` i ścieżka zmiany treści."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(container, integration_id, document_id=document.id)
    registered_fake.files[(CID, ITEM_ID)] = b"nowa tresc"

    outcome = await start_run(
        engine,
        registered_fake,
        integration_id,
        items=[make_item(name="b.pdf", path="/b.pdf", content_tag="c1", meta_tag="m1")],
    )

    assert counts_of(outcome) == (0, 1, 0, 0, 0, 0)
    fresh = await fetch_document(container, document.id)
    assert fresh is not None
    assert fresh.suffix == "pdf"
    assert fresh.name == "b.pdf"
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert mapping.document_id == document.id
    assert await parse_task_count(container, document.id, status="queued") == 1
    assert ("info", "updated") in await event_pairs(container, outcome.run_id)


async def test_row8_meta_tag_only_updates_mapping(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 8: sam ``meta_tag`` — mapowanie nowe, dokument i parsowanie bez zmian."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(container, integration_id, document_id=document.id, web_url=None)

    outcome = await start_run(
        engine,
        registered_fake,
        integration_id,
        items=[
            make_item(
                name="a.txt",
                path="/a.txt",
                content_tag="c1",
                meta_tag="m2",
                web_url="https://x/a.txt",
            )
        ],
    )

    assert counts_of(outcome) == (0, 0, 0, 0, 0, 0)
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert (mapping.meta_tag, mapping.web_url) == ("m2", "https://x/a.txt")
    assert mapping.document_id == document.id
    fresh = await fetch_document(container, document.id)
    assert fresh is not None
    assert (fresh.name, fresh.content_hash) == (document.name, document.content_hash)
    assert await parse_task_count(container, document.id, status="queued") == 0
    assert await event_pairs(container, outcome.run_id) == [
        ("info", START_EVENT),
        ("info", DONE_EVENT),
    ]


async def test_row9_new_item_uploads_document(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 9: brak mapowania — ``upload`` z ``source_ref``, ``wd_source`` i zadaniem parse."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    registered_fake.files[(CID, ITEM_ID)] = b"tresc pliku"

    outcome = await start_run(
        engine,
        registered_fake,
        integration_id,
        items=[make_item(web_url="https://x/a.txt", content_tag="c1", meta_tag="m1")],
    )

    assert counts_of(outcome) == (1, 0, 0, 0, 0, 0)
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert mapping.document_id is not None
    document = await fetch_document(container, mapping.document_id)
    assert document is not None
    assert document.source_type == "sharepoint"
    assert document.source_ref == source_ref(integration_id, ITEM_ID)
    assert document.meta_fields["wd_source"] == wd_source(integration_id, web_url="https://x/a.txt")
    assert document.run == "1"
    assert (mapping.last_status, mapping.last_error) == ("ok", None)
    assert (mapping.content_tag, mapping.meta_tag) == ("c1", "m1")
    assert (mapping.name, mapping.path, mapping.web_url) == ("a.txt", "/a.txt", "https://x/a.txt")
    assert await parse_task_count(container, document.id, status="queued") == 1
    assert ("info", "added") in await event_pairs(container, outcome.run_id)
    assert list(tmp_dir(container).iterdir()) == []


async def test_row9_content_change_replaces_same_document_id(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 9: ``content_tag`` różny — ``replace`` z **niezmienionym** ``document_id``."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(container, integration_id, document_id=document.id, content_tag="old")
    registered_fake.files[(CID, ITEM_ID)] = b"nowa tresc pliku"

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(content_tag="new")]
    )

    assert counts_of(outcome) == (0, 1, 0, 0, 0, 0)
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert mapping.document_id == document.id
    assert mapping.content_tag == "new"
    fresh = await fetch_document(container, document.id)
    assert fresh is not None
    assert fresh.content_hash != document.content_hash
    assert await parse_task_count(container, document.id, status="queued") == 1
    assert ("info", "updated") in await event_pairs(container, outcome.run_id)
    assert list(tmp_dir(container).iterdir()) == []


async def test_row9_failed_mapping_is_retried(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 9: mapping ``failed`` — element wraca ścieżką zmiany treści (``replace``)."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(
        container,
        integration_id,
        document_id=document.id,
        content_tag="c1",
        last_status="failed",
        last_error="boom",
    )

    outcome = await start_run(engine, registered_fake, integration_id, items=[make_item()])

    assert counts_of(outcome) == (0, 1, 0, 0, 0, 0)
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert (mapping.last_status, mapping.last_error) == ("ok", None)
    assert mapping.document_id == document.id


async def test_row10_download_failure_records_failed_mapping(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 10: błąd pobrania — mapping ``failed``, ``error`` i sprzątnięty plik tymczasowy."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    registered_fake.fail_download[(CID, ITEM_ID)] = RuntimeError("boom")

    outcome = await start_run(engine, registered_fake, integration_id, items=[make_item()])

    assert counts_of(outcome) == (0, 0, 0, 0, 1, 0)
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert (mapping.last_status, mapping.last_error) == ("failed", "boom")
    assert (mapping.document_id, mapping.content_tag) == (None, None)
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        events = await list_events(session, outcome.run_id)
    errors = [event for event in events if event.level == "error"]
    assert len(errors) == 1
    assert errors[0].file_path == "/a.txt"
    assert errors[0].message.endswith("boom")
    assert list(tmp_dir(container).iterdir()) == []


async def test_row10_failure_keeps_existing_document_id(
    container: Container, engine: SyncEngine, registered_fake: FakeConnector
) -> None:
    """Wiersz 10: przy istniejącym mappingu ``document_id`` zostaje, ``last_status`` = failed."""
    integration_id = await make_integration(container.sessionmaker)  # type: ignore[arg-type]
    integration = await integration_row(container, integration_id)
    document = await upload_document(container, integration)
    await put_mapping(container, integration_id, document_id=document.id, content_tag="old")
    registered_fake.fail_download[(CID, ITEM_ID)] = RuntimeError("boom")

    outcome = await start_run(
        engine, registered_fake, integration_id, items=[make_item(content_tag="new")]
    )

    assert counts_of(outcome) == (0, 0, 0, 0, 1, 0)
    mapping = await fetch_mapping(container, integration_id)
    assert mapping is not None
    assert mapping.document_id == document.id
    assert (mapping.last_status, mapping.last_error) == ("failed", "boom")
    assert await fetch_document(container, document.id) is not None
    assert list(tmp_dir(container).iterdir()) == []
