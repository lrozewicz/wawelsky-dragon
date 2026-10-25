"""Testy funkcji administracyjnych repozytorium integracji (brief T1, kontrakt E4-3a §1)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import datasets as datasets_repo
from app.db.repositories.integrations import (
    DatasetSummary,
    delete_integration,
    find_by_dataset,
    find_mapping_by_document,
    get_container,
    get_integration,
    get_mapping,
    get_run,
    get_sharepoint,
    insert_events,
    insert_integration,
    insert_run,
    list_dataset_summaries,
    list_events,
    list_events_page,
    list_integrations,
    list_runs,
    mapping_document_ids,
    update_integration,
    update_mapping_link,
    upsert_container,
    upsert_mapping,
    upsert_sharepoint,
)
from app.db.repositories.integrations.rows import (
    EventRow,
    IntegrationRow,
    MappingRow,
    NewEvent,
    RunRow,
)
from app.db.uow import transaction
from tests.integration.integrations.conftest import (
    TIME_MS,
    make_integration,
    seed_dataset_and_user,
)

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]
LATER_MS = TIME_MS + 1_000
CONTAINER_ID = "c1"
ITEM_ID = "i1"
UPDATED_NAME = "Księgowość po zmianie"
NEW_MAX_FILE_SIZE = 1_024
NEW_SCAN_INTERVAL = 60
NEW_PATH = "/Dokumenty/raport.pdf"
NEW_WEB_URL = "https://tenant.sharepoint.test/raport.pdf"
RUN_LIMIT = 2
EVENT_PAGE_LIMIT = 2
EXPECTED_EVENT_COUNT = 2
EMBEDDING_MODEL = "fake-embed-1024"
DATASET_NAME = "Archiwum"

# Poziomy zdarzeń runu: ``error`` na pozycjach 1, 3 i 4 (indeksy od 0).
EVENT_LEVELS = ["info", "error", "info", "error", "error"]


async def _list(sm: SM) -> list[IntegrationRow]:
    async with transaction(sm) as session:
        return await list_integrations(session)


async def _by_dataset(sm: SM, dataset_id: str) -> IntegrationRow | None:
    async with transaction(sm) as session:
        return await find_by_dataset(session, dataset_id)


async def _update(sm: SM, integration_id: int, *, dataset_id: str, now_ms: int) -> bool:
    async with transaction(sm) as session:
        return await update_integration(
            session,
            integration_id,
            name=UPDATED_NAME,
            dataset_id=dataset_id,
            max_file_size_bytes=NEW_MAX_FILE_SIZE,
            ignored_extensions=["exe"],
            scan_interval_seconds=NEW_SCAN_INTERVAL,
            delete_propagation=False,
            is_active=False,
            now_ms=now_ms,
        )


async def _delete(sm: SM, integration_id: int) -> bool:
    async with transaction(sm) as session:
        return await delete_integration(session, integration_id)


async def _runs(
    sm: SM, *, integration_type: str | None, integration_id: int | None, limit: int
) -> list[RunRow]:
    async with transaction(sm) as session:
        return await list_runs(
            session,
            integration_type=integration_type,
            integration_id=integration_id,
            limit=limit,
        )


async def _page(
    sm: SM, run_id: int, *, after_id: int, level: str | None, limit: int
) -> list[EventRow]:
    async with transaction(sm) as session:
        return await list_events_page(session, run_id, after_id=after_id, level=level, limit=limit)


async def _find_mapping(sm: SM, document_id: str) -> MappingRow | None:
    async with transaction(sm) as session:
        return await find_mapping_by_document(session, document_id)


async def _document_ids(sm: SM, integration_id: int) -> list[str]:
    async with transaction(sm) as session:
        return await mapping_document_ids(session, integration_id)


async def _link(sm: SM, integration_id: int) -> None:
    async with transaction(sm) as session:
        await update_mapping_link(
            session,
            integration_id,
            CONTAINER_ID,
            ITEM_ID,
            name="Nowa nazwa",
            path=NEW_PATH,
            web_url=NEW_WEB_URL,
            now_ms=LATER_MS,
        )


async def _summaries(sm: SM) -> list[DatasetSummary]:
    async with transaction(sm) as session:
        return await list_dataset_summaries(session)


async def _insert_run(sm: SM, integration_id: int, *, integration_type: str = "fake") -> int:
    async with transaction(sm) as session:
        return await insert_run(
            session,
            integration_id=integration_id,
            integration_type=integration_type,
            run_trigger="manual",
            now_ms=TIME_MS,
        )


async def _insert_events(sm: SM, integration_id: int, run_id: int, levels: list[str]) -> None:
    events = [
        NewEvent(
            run_id=run_id,
            integration_id=integration_id,
            integration_type="fake",
            level=level,
            message=f"zdarzenie {index}",
            file_path=None,
            container_id=None,
            container_name=None,
            created_at=TIME_MS + index,
        )
        for index, level in enumerate(levels)
    ]
    async with transaction(sm) as session:
        await insert_events(session, events)


def _mapping(integration_id: int, item_id: str, document_id: str | None) -> MappingRow:
    """MappingRow z wartościami testowymi; ``document_id=None`` to mapowanie bez dokumentu."""
    return MappingRow(
        integration_id=integration_id,
        container_id=CONTAINER_ID,
        item_id=item_id,
        document_id=document_id,
        content_tag=None,
        meta_tag=None,
        name=None,
        path=None,
        web_url=None,
        last_status="ok",
        last_error=None,
        updated_at=TIME_MS,
    )


async def _seed_dependants(sm: SM, integration_id: int) -> None:
    """Kontener, mapowanie i wiersz SharePoint dla integracji (dane kasowane razem z nią)."""
    async with transaction(sm) as session:
        await upsert_container(
            session, integration_id, CONTAINER_ID, name="Dokumenty", now_ms=TIME_MS
        )
        await upsert_mapping(session, _mapping(integration_id, ITEM_ID, uuid.uuid4().hex))
        await upsert_sharepoint(
            session,
            integration_id=integration_id,
            tenant_id="tenant",
            client_id="client",
            site_url="https://tenant.sharepoint.test",
        )


async def _insert_dataset(sm: SM, tenant_id: str, name: str) -> str:
    dataset_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await datasets_repo.insert(
            session,
            id=dataset_id,
            tenant_id=tenant_id,
            created_by=tenant_id,
            name=name,
            description=None,
            avatar=None,
            language="Polish",
            embedding_model=EMBEDDING_MODEL,
            embedding_dim=1024,
            permission="me",
            chunk_method="naive",
            parser_config={"chunk_token_num": 128, "delimiter": "\n"},
            now_ms=TIME_MS,
        )
    return dataset_id


async def _get_row(sm: SM, integration_id: int) -> IntegrationRow | None:
    async with transaction(sm) as session:
        return await get_integration(session, integration_id)


# --- list_integrations ----------------------------------------------------------


async def test_list_integrations_orders_by_id_desc(sm: SM) -> None:
    inserted = [await make_integration(sm, name=f"SP {index}") for index in range(3)]
    rows = await _list(sm)
    assert [row.id for row in rows] == list(reversed(inserted))


async def test_list_integrations_empty(sm: SM) -> None:
    assert await _list(sm) == []


# --- find_by_dataset ------------------------------------------------------------


async def test_find_by_dataset_returns_row_and_none(sm: SM) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    integration_id = await make_integration(sm, dataset_id=dataset_id, owner_id=owner_id)

    row = await _by_dataset(sm, dataset_id)
    assert row is not None
    assert row.id == integration_id
    assert row.dataset_id == dataset_id
    assert await _by_dataset(sm, uuid.uuid4().hex) is None


# --- update_integration ---------------------------------------------------------


async def test_update_integration_changes_fields_and_timestamp(sm: SM) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    other_id = await _insert_dataset(sm, owner_id, DATASET_NAME)
    integration_id = await make_integration(sm, dataset_id=dataset_id, owner_id=owner_id)

    assert await _update(sm, integration_id, dataset_id=other_id, now_ms=LATER_MS) is True

    row = await _get_row(sm, integration_id)
    assert row is not None
    assert row.name == UPDATED_NAME
    assert row.dataset_id == other_id
    assert row.max_file_size_bytes == NEW_MAX_FILE_SIZE
    assert row.ignored_extensions == ["exe"]
    assert row.scan_interval_seconds == NEW_SCAN_INTERVAL
    assert row.delete_propagation is False
    assert row.is_active is False
    assert row.updated_at == LATER_MS
    assert row.created_at == TIME_MS
    assert row.secret_enc is None  # kolumna sekretu bez zmian


async def test_update_integration_missing_returns_false(sm: SM) -> None:
    _owner_id, dataset_id = await seed_dataset_and_user(sm)
    assert await _update(sm, 999_999, dataset_id=dataset_id, now_ms=LATER_MS) is False


# --- delete_integration ---------------------------------------------------------


async def test_delete_integration_removes_dependants_and_keeps_runs(sm: SM) -> None:
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id)
    await _insert_events(sm, integration_id, run_id, ["info", "error"])
    await _seed_dependants(sm, integration_id)

    assert await _delete(sm, integration_id) is True

    assert await _get_row(sm, integration_id) is None
    async with transaction(sm) as session:
        assert await get_container(session, integration_id, CONTAINER_ID) is None
        assert await get_sharepoint(session, integration_id) is None
        assert await get_mapping(session, integration_id, CONTAINER_ID, ITEM_ID) is None
        assert await get_run(session, run_id) is not None
        assert len(await list_events(session, run_id)) == EXPECTED_EVENT_COUNT


async def test_delete_integration_twice_returns_false(sm: SM) -> None:
    integration_id = await make_integration(sm)
    assert await _delete(sm, integration_id) is True
    assert await _delete(sm, integration_id) is False


# --- list_runs ------------------------------------------------------------------


async def test_list_runs_filters_and_orders_desc(sm: SM) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    async with transaction(sm) as session:
        sharepoint_id = await insert_integration(
            session,
            type="sharepoint",
            name="SP",
            dataset_id=dataset_id,
            owner_id=owner_id,
            config={},
            now_ms=TIME_MS,
        )
    fake_id = await make_integration(sm)
    sharepoint_run = await _insert_run(sm, sharepoint_id, integration_type="sharepoint")
    fake_runs = [await _insert_run(sm, fake_id) for _ in range(3)]

    everything = await _runs(sm, integration_type=None, integration_id=None, limit=10)
    assert [run.id for run in everything] == [*reversed(fake_runs), sharepoint_run]

    only_fake = await _runs(sm, integration_type="fake", integration_id=None, limit=10)
    assert [run.id for run in only_fake] == list(reversed(fake_runs))

    only_sharepoint = await _runs(sm, integration_type=None, integration_id=sharepoint_id, limit=10)
    assert [run.id for run in only_sharepoint] == [sharepoint_run]

    limited = await _runs(sm, integration_type="fake", integration_id=fake_id, limit=RUN_LIMIT)
    assert [run.id for run in limited] == list(reversed(fake_runs))[:RUN_LIMIT]


async def test_list_runs_empty_when_no_matches(sm: SM) -> None:
    integration_id = await make_integration(sm)
    found = await _runs(sm, integration_type="sharepoint", integration_id=integration_id, limit=10)
    assert found == []


# --- list_events_page -----------------------------------------------------------


async def test_list_events_page_after_id_level_limit_asc(sm: SM) -> None:
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id)
    await _insert_events(sm, integration_id, run_id, EVENT_LEVELS)
    async with transaction(sm) as session:
        ids = [event.id for event in await list_events(session, run_id)]
    assert ids == sorted(ids)

    after_second = await _page(sm, run_id, after_id=ids[1], level=None, limit=10)
    assert [event.id for event in after_second] == ids[2:]

    errors = await _page(sm, run_id, after_id=ids[0], level="error", limit=10)
    assert [event.id for event in errors] == [ids[1], ids[3], ids[4]]

    first_page = await _page(sm, run_id, after_id=0, level=None, limit=EVENT_PAGE_LIMIT)
    assert [event.id for event in first_page] == ids[:EVENT_PAGE_LIMIT]


async def test_list_events_page_other_run_is_empty(sm: SM) -> None:
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id)
    other_run = await _insert_run(sm, integration_id)
    await _insert_events(sm, integration_id, run_id, ["info"])

    assert await _page(sm, other_run, after_id=0, level=None, limit=10) == []


# --- find_mapping_by_document ---------------------------------------------------


async def test_find_mapping_by_document_returns_row_and_none(sm: SM) -> None:
    integration_id = await make_integration(sm)
    document_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await upsert_mapping(session, _mapping(integration_id, ITEM_ID, document_id))

    row = await _find_mapping(sm, document_id)
    assert row is not None
    assert row.integration_id == integration_id
    assert row.item_id == ITEM_ID
    assert row.document_id == document_id
    assert await _find_mapping(sm, uuid.uuid4().hex) is None


# --- mapping_document_ids -------------------------------------------------------


async def test_mapping_document_ids_skips_empty_and_null(sm: SM) -> None:
    integration_id = await make_integration(sm)
    document_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await upsert_mapping(session, _mapping(integration_id, "i1", document_id))
        await upsert_mapping(session, _mapping(integration_id, "i2", None))
        await upsert_mapping(session, _mapping(integration_id, "i3", ""))

    assert await _document_ids(sm, integration_id) == [document_id]


async def test_mapping_document_ids_scoped_to_integration(sm: SM) -> None:
    first = await make_integration(sm)
    second = await make_integration(sm)
    async with transaction(sm) as session:
        await upsert_mapping(session, _mapping(first, "i1", uuid.uuid4().hex))

    assert await _document_ids(sm, second) == []


# --- update_mapping_link --------------------------------------------------------


async def test_update_mapping_link_sets_fields_and_timestamp(sm: SM) -> None:
    integration_id = await make_integration(sm)
    document_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await upsert_mapping(session, _mapping(integration_id, ITEM_ID, document_id))

    await _link(sm, integration_id)

    async with transaction(sm) as session:
        row = await get_mapping(session, integration_id, CONTAINER_ID, ITEM_ID)
    assert row is not None
    assert row.name == "Nowa nazwa"
    assert row.path == NEW_PATH
    assert row.web_url == NEW_WEB_URL
    assert row.updated_at == LATER_MS
    assert row.document_id == document_id  # mapowanie na dokument bez zmian


# --- list_dataset_summaries -----------------------------------------------------


async def test_list_dataset_summaries_orders_by_name_and_counts(sm: SM) -> None:
    owner_id, korpus_id = await seed_dataset_and_user(sm)
    archiwum_id = await _insert_dataset(sm, owner_id, DATASET_NAME)
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET document_count = 7, chunk_count = 9 WHERE id = :id"),
            {"id": korpus_id},
        )

    assert await _summaries(sm) == [
        DatasetSummary(
            id=archiwum_id,
            name=DATASET_NAME,
            document_count=0,
            chunk_count=0,
            embedding_model=EMBEDDING_MODEL,
        ),
        DatasetSummary(
            id=korpus_id,
            name="Korpus",
            document_count=7,
            chunk_count=9,
            embedding_model=EMBEDDING_MODEL,
        ),
    ]
