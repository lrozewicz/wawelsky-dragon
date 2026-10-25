"""Testy repozytorium integracji na prawdziwej MariaDB (brief T3, kontrakt C1/C2)."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.integrations import (
    ContainerRow,
    EventRow,
    IntegrationRow,
    MappingRow,
    NewEvent,
    RunRow,
    delete_mapping,
    finish_run,
    force_unlock,
    get_container,
    get_integration,
    get_mapping,
    get_run,
    heartbeat_lock,
    insert_events,
    insert_integration,
    insert_run,
    is_cancel_requested,
    latest_run,
    list_containers,
    list_due,
    list_events,
    list_mappings,
    mark_running_runs,
    purge_events_before,
    recover_stale,
    release_lock,
    request_cancel,
    reset_cursors,
    running_run_ids,
    set_container_cursor,
    try_lock,
    update_run_counts,
    upsert_container,
    upsert_mapping,
)
from app.db.uow import transaction
from app.integrations.base import SyncCounts
from tests.integration.integrations.conftest import (
    TIME_MS,
    make_integration,
    seed_dataset_and_user,
)

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]
DEFAULT_MAX_FILE_SIZE = 209_715_200
DEFAULT_SCAN_INTERVAL = 300
STALE_MS = 900_000
OVERRIDE_MAX_FILE_SIZE = 1024
OVERRIDE_SCAN_INTERVAL = 30
COUNTS_SET = SyncCounts(added=1, updated=2, renamed=3, deleted=4, failed=5, skipped=6)
COUNTS_REPLACED = SyncCounts(added=10)
COUNTS_FINISHED = SyncCounts(added=7)
MARKED_RUNS = 2


async def _get(sm: SM, integration_id: int) -> IntegrationRow | None:
    async with transaction(sm) as session:
        return await get_integration(session, integration_id)


async def _try(sm: SM, integration_id: int, owner: str, now_ms: int) -> bool:
    async with transaction(sm) as session:
        return await try_lock(session, integration_id, owner=owner, now_ms=now_ms)


async def _heartbeat(sm: SM, integration_id: int, owner: str, now_ms: int) -> bool:
    async with transaction(sm) as session:
        return await heartbeat_lock(session, integration_id, owner=owner, now_ms=now_ms)


async def _release(sm: SM, integration_id: int, owner: str, now_ms: int, status: str) -> bool:
    async with transaction(sm) as session:
        return await release_lock(
            session, integration_id, owner=owner, now_ms=now_ms, status=status
        )


async def _cancel(sm: SM, integration_id: int) -> bool:
    async with transaction(sm) as session:
        return await request_cancel(session, integration_id)


async def _force(sm: SM, integration_id: int) -> bool:
    async with transaction(sm) as session:
        return await force_unlock(session, integration_id)


async def _insert_run(
    sm: SM, integration_id: int, *, trigger: str = "schedule", now_ms: int = TIME_MS
) -> int:
    async with transaction(sm) as session:
        return await insert_run(
            session,
            integration_id=integration_id,
            integration_type="fake",
            run_trigger=trigger,
            now_ms=now_ms,
        )


def _mapping(integration_id: int, item_id: str, **overrides: object) -> MappingRow:
    """MappingRow z domyślnymi testowymi; nadpisywane polami z ``overrides``."""
    values: dict[str, object] = {
        "integration_id": integration_id,
        "container_id": "c1",
        "item_id": item_id,
        "document_id": None,
        "content_tag": None,
        "meta_tag": None,
        "name": None,
        "path": None,
        "web_url": None,
        "last_status": "ok",
        "last_error": None,
        "updated_at": TIME_MS,
    }
    values.update(overrides)
    return MappingRow(**values)  # type: ignore[arg-type]


def _event(integration_id: int, run_id: int, created_at: int) -> NewEvent:
    return NewEvent(
        run_id=run_id,
        integration_id=integration_id,
        integration_type="fake",
        level="info",
        message=f"event {created_at}",
        file_path=None,
        container_id=None,
        container_name=None,
        created_at=created_at,
    )


# --- integracje -----------------------------------------------------------------


async def test_insert_get_round_trip(sm: SM) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    async with transaction(sm) as session:
        integration_id = await insert_integration(
            session,
            type="sharepoint",
            name="Księgowość",
            dataset_id=dataset_id,
            owner_id=owner_id,
            config={"site_url": "https://x", "opis": "żółć"},
            now_ms=TIME_MS,
        )
    row = await _get(sm, integration_id)
    assert row == IntegrationRow(
        id=integration_id,
        type="sharepoint",
        name="Księgowość",
        dataset_id=dataset_id,
        owner_id=owner_id,
        config={"site_url": "https://x", "opis": "żółć"},
        secret_enc=None,
        secret_last4=None,
        max_file_size_bytes=DEFAULT_MAX_FILE_SIZE,
        ignored_extensions=[],
        scan_interval_seconds=DEFAULT_SCAN_INTERVAL,
        delete_propagation=True,
        is_active=True,
        is_running=False,
        lock_acquired_at=None,
        lock_owner=None,
        cancel_requested=False,
        last_sync_at=None,
        last_sync_status=None,
        created_at=TIME_MS,
        updated_at=TIME_MS,
    )


async def test_insert_get_overrides(sm: SM) -> None:
    integration_id = await make_integration(
        sm,
        ignored_extensions=["exe", "dll"],
        max_file_size_bytes=1024,
        scan_interval_seconds=30,
        delete_propagation=False,
        is_active=False,
    )
    row = await _get(sm, integration_id)
    assert row is not None
    assert row.ignored_extensions == ["exe", "dll"]
    assert row.max_file_size_bytes == OVERRIDE_MAX_FILE_SIZE
    assert row.scan_interval_seconds == OVERRIDE_SCAN_INTERVAL
    assert row.delete_propagation is False
    assert row.is_active is False


async def test_get_integration_missing(sm: SM) -> None:
    assert await _get(sm, 999_999) is None


async def test_try_lock_once_then_false(sm: SM) -> None:
    integration_id = await make_integration(sm)
    assert await _try(sm, integration_id, "w1", TIME_MS) is True
    row = await _get(sm, integration_id)
    assert row.is_running is True
    assert row.lock_owner == "w1"
    assert row.lock_acquired_at == TIME_MS
    assert await _try(sm, integration_id, "w2", TIME_MS + 1) is False
    assert (await _get(sm, integration_id)).lock_owner == "w1"


async def test_try_lock_parallel_sessions_exactly_one(sm: SM) -> None:
    integration_id = await make_integration(sm)

    async def attempt(owner: str) -> bool:
        async with transaction(sm) as session:
            return await try_lock(session, integration_id, owner=owner, now_ms=TIME_MS)

    a, b = await asyncio.gather(attempt("a"), attempt("b"))
    assert sorted([a, b]) == [False, True]


async def test_try_lock_zeroes_cancel_requested(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE integrations SET cancel_requested = 1 WHERE id = :id"),
            {"id": integration_id},
        )
    assert await _try(sm, integration_id, "w1", TIME_MS) is True
    assert (await _get(sm, integration_id)).cancel_requested is False


async def test_heartbeat_lock_only_owner(sm: SM) -> None:
    integration_id = await make_integration(sm)
    await _try(sm, integration_id, "w1", TIME_MS)
    assert await _heartbeat(sm, integration_id, "w2", TIME_MS + 5) is False
    assert await _heartbeat(sm, integration_id, "w1", TIME_MS + 5) is True
    assert (await _get(sm, integration_id)).lock_acquired_at == TIME_MS + 5


async def test_release_lock_owner_and_foreign(sm: SM) -> None:
    integration_id = await make_integration(sm)
    await _try(sm, integration_id, "w1", TIME_MS)
    assert await _release(sm, integration_id, "w2", TIME_MS + 1, "success") is False
    assert await _release(sm, integration_id, "w1", TIME_MS + 2, "success") is True
    row = await _get(sm, integration_id)
    assert row.is_running is False
    assert row.lock_owner is None
    assert row.cancel_requested is False
    assert row.last_sync_at == TIME_MS + 2
    assert row.last_sync_status == "success"


async def test_recover_stale_old_lock(sm: SM) -> None:
    stale_id = await make_integration(sm)
    fresh_id = await make_integration(sm)
    await _try(sm, stale_id, "w1", TIME_MS - 1_000_000)
    await _try(sm, fresh_id, "w2", TIME_MS)
    async with transaction(sm) as session:
        recovered = await recover_stale(session, now_ms=TIME_MS, stale_ms=STALE_MS)
    assert recovered == [stale_id]
    assert (await _get(sm, stale_id)).is_running is False
    assert (await _get(sm, stale_id)).lock_owner is None
    assert (await _get(sm, fresh_id)).is_running is True


async def test_recover_stale_fresh_lock_empty(sm: SM) -> None:
    integration_id = await make_integration(sm)
    await _try(sm, integration_id, "w1", TIME_MS)
    async with transaction(sm) as session:
        recovered = await recover_stale(session, now_ms=TIME_MS, stale_ms=STALE_MS)
    assert recovered == []


async def test_request_cancel_only_when_running(sm: SM) -> None:
    integration_id = await make_integration(sm)
    assert await _cancel(sm, integration_id) is False
    await _try(sm, integration_id, "w1", TIME_MS)
    assert await _cancel(sm, integration_id) is True
    assert (await _get(sm, integration_id)).cancel_requested is True


async def test_is_cancel_requested(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        assert await is_cancel_requested(session, integration_id) is False
        assert await is_cancel_requested(session, 999_999) is False
    await _try(sm, integration_id, "w1", TIME_MS)
    await _cancel(sm, integration_id)
    async with transaction(sm) as session:
        assert await is_cancel_requested(session, integration_id) is True


async def test_force_unlock(sm: SM) -> None:
    integration_id = await make_integration(sm)
    assert await _force(sm, integration_id) is False
    await _try(sm, integration_id, "w1", TIME_MS)
    await _cancel(sm, integration_id)
    assert await _force(sm, integration_id) is True
    row = await _get(sm, integration_id)
    assert row.is_running is False
    assert row.lock_owner is None
    assert row.cancel_requested is False


async def test_list_due_new_is_due(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        assert await list_due(session, now_ms=TIME_MS) == [integration_id]


async def test_list_due_after_release_respects_interval(sm: SM) -> None:
    integration_id = await make_integration(sm)
    await _try(sm, integration_id, "w1", TIME_MS)
    await _release(sm, integration_id, "w1", TIME_MS, "success")
    async with transaction(sm) as session:
        assert await list_due(session, now_ms=TIME_MS + 299_999) == []
        assert await list_due(session, now_ms=TIME_MS + 300_001) == [integration_id]


async def test_list_due_skips_inactive_and_running(sm: SM) -> None:
    inactive_id = await make_integration(sm, is_active=False)
    running_id = await make_integration(sm)
    await _try(sm, running_id, "w1", TIME_MS)
    async with transaction(sm) as session:
        due = await list_due(session, now_ms=TIME_MS)
    assert inactive_id not in due
    assert running_id not in due


async def test_list_due_ordered_by_id(sm: SM) -> None:
    first_id = await make_integration(sm)
    second_id = await make_integration(sm)
    async with transaction(sm) as session:
        assert await list_due(session, now_ms=TIME_MS) == [first_id, second_id]


# --- kontenery ------------------------------------------------------------------


async def test_upsert_container_keeps_discovered_at(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        await upsert_container(session, integration_id, "c1", name="Dokumenty", now_ms=TIME_MS)
    async with transaction(sm) as session:
        await upsert_container(
            session, integration_id, "c1", name="Dokumenty 2", now_ms=TIME_MS + 5_000
        )
    async with transaction(sm) as session:
        row = await get_container(session, integration_id, "c1")
    assert row == ContainerRow(
        integration_id=integration_id,
        container_id="c1",
        name="Dokumenty 2",
        delta_cursor=None,
        last_sync_at=None,
        discovered_at=TIME_MS,
    )


async def test_get_container_missing(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        assert await get_container(session, integration_id, "nope") is None


async def test_set_and_reset_cursors(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        await upsert_container(session, integration_id, "c1", name="A", now_ms=TIME_MS)
        await upsert_container(session, integration_id, "c2", name="B", now_ms=TIME_MS)
    async with transaction(sm) as session:
        await set_container_cursor(
            session, integration_id, "c1", cursor="tok", now_ms=TIME_MS + 100
        )
    async with transaction(sm) as session:
        row = await get_container(session, integration_id, "c1")
    assert row.delta_cursor == "tok"
    assert row.last_sync_at == TIME_MS + 100
    async with transaction(sm) as session:
        await reset_cursors(session, integration_id)
    async with transaction(sm) as session:
        rows = await list_containers(session, integration_id)
    assert [r.container_id for r in rows] == ["c1", "c2"]
    assert all(r.delta_cursor is None for r in rows)


# --- mapowania ------------------------------------------------------------------


async def test_mapping_upsert_get_update_delete(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        await upsert_mapping(session, _mapping(integration_id, "i2", name="b.txt", path="/b.txt"))
        await upsert_mapping(session, _mapping(integration_id, "i1", name="a.txt", path="/a.txt"))
    async with transaction(sm) as session:
        row = await get_mapping(session, integration_id, "c1", "i1")
    assert row == MappingRow(
        integration_id=integration_id,
        container_id="c1",
        item_id="i1",
        document_id=None,
        content_tag=None,
        meta_tag=None,
        name="a.txt",
        path="/a.txt",
        web_url=None,
        last_status="ok",
        last_error=None,
        updated_at=TIME_MS,
    )
    async with transaction(sm) as session:
        await upsert_mapping(
            session,
            _mapping(
                integration_id,
                "i1",
                name="a2.txt",
                last_status="failed",
                last_error="boom",
                updated_at=TIME_MS + 9,
            ),
        )
    async with transaction(sm) as session:
        updated = await get_mapping(session, integration_id, "c1", "i1")
    assert updated.name == "a2.txt"
    assert updated.last_status == "failed"
    assert updated.last_error == "boom"
    assert updated.updated_at == TIME_MS + 9
    async with transaction(sm) as session:
        rows = await list_mappings(session, integration_id, "c1")
    assert [r.item_id for r in rows] == ["i1", "i2"]
    async with transaction(sm) as session:
        await delete_mapping(session, integration_id, "c1", "i1")
    async with transaction(sm) as session:
        assert await get_mapping(session, integration_id, "c1", "i1") is None


async def test_get_mapping_missing(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        assert await get_mapping(session, integration_id, "c1", "nope") is None


# --- runy -----------------------------------------------------------------------


async def test_insert_get_run_running(sm: SM) -> None:
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id, trigger="manual")
    async with transaction(sm) as session:
        row = await get_run(session, run_id)
    assert row == RunRow(
        id=run_id,
        integration_id=integration_id,
        integration_type="fake",
        run_trigger="manual",
        started_at=TIME_MS,
        finished_at=None,
        status="running",
        added=0,
        updated=0,
        renamed=0,
        deleted=0,
        failed=0,
        skipped=0,
    )


async def test_update_run_counts_and_finish_run(sm: SM) -> None:
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id)
    async with transaction(sm) as session:
        await update_run_counts(session, run_id, COUNTS_SET)
    async with transaction(sm) as session:
        row = await get_run(session, run_id)
    assert (row.added, row.updated, row.renamed, row.deleted, row.failed, row.skipped) == (
        1,
        2,
        3,
        4,
        5,
        6,
    )
    assert row.status == "running"
    # update_run_counts ustawia, nie dodaje
    async with transaction(sm) as session:
        await update_run_counts(session, run_id, COUNTS_REPLACED)
    async with transaction(sm) as session:
        row = await get_run(session, run_id)
    assert row.added == COUNTS_REPLACED.added
    assert row.updated == 0
    async with transaction(sm) as session:
        await finish_run(
            session, run_id, status="success", counts=COUNTS_FINISHED, now_ms=TIME_MS + 100
        )
    async with transaction(sm) as session:
        row = await get_run(session, run_id)
    assert row.status == "success"
    assert row.finished_at == TIME_MS + 100
    assert row.added == COUNTS_FINISHED.added


async def test_latest_run_running_ids_and_mark(sm: SM) -> None:
    integration_id = await make_integration(sm)
    run1 = await _insert_run(sm, integration_id)
    run2 = await _insert_run(sm, integration_id, trigger="manual")
    async with transaction(sm) as session:
        latest = await latest_run(session, integration_id)
    assert latest is not None
    assert latest.id == run2
    async with transaction(sm) as session:
        assert await running_run_ids(session, integration_id) == [run1, run2]
    async with transaction(sm) as session:
        marked = await mark_running_runs(
            session, integration_id, status="failed", now_ms=TIME_MS + 50
        )
    assert marked == MARKED_RUNS
    async with transaction(sm) as session:
        assert await running_run_ids(session, integration_id) == []
        row = await get_run(session, run1)
    assert row.status == "failed"
    assert row.finished_at == TIME_MS + 50


async def test_latest_run_empty(sm: SM) -> None:
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        assert await latest_run(session, integration_id) is None
    async with transaction(sm) as session:
        assert await running_run_ids(session, integration_id) == []


# --- zdarzenia ------------------------------------------------------------------


async def test_insert_events_empty_is_noop(sm: SM) -> None:
    async with transaction(sm) as session:
        await insert_events(session, [])
    async with transaction(sm) as session:
        assert await list_events(session, 999_999) == []


async def test_insert_and_list_events_order(sm: SM) -> None:
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id)
    first = NewEvent(
        run_id=run_id,
        integration_id=integration_id,
        integration_type="fake",
        level="info",
        message="pierwsze",
        file_path="a.txt",
        container_id="c1",
        container_name="A",
        created_at=TIME_MS,
    )
    second = NewEvent(
        run_id=run_id,
        integration_id=integration_id,
        integration_type="fake",
        level="error",
        message="drugie",
        file_path=None,
        container_id=None,
        container_name=None,
        created_at=TIME_MS + 1,
    )
    async with transaction(sm) as session:
        await insert_events(session, [first, second])
    async with transaction(sm) as session:
        rows = await list_events(session, run_id)
    assert [r.message for r in rows] == ["pierwsze", "drugie"]
    assert rows[0] == EventRow(
        id=rows[0].id,
        run_id=run_id,
        integration_id=integration_id,
        integration_type="fake",
        level="info",
        message="pierwsze",
        file_path="a.txt",
        container_id="c1",
        container_name="A",
        created_at=TIME_MS,
    )


async def test_purge_events_before(sm: SM) -> None:
    integration_id = await make_integration(sm)
    run_id = await _insert_run(sm, integration_id)
    async with transaction(sm) as session:
        await insert_events(
            session, [_event(integration_id, run_id, 50), _event(integration_id, run_id, 150)]
        )
    async with transaction(sm) as session:
        purged = await purge_events_before(session, before_ms=100)
    assert purged == 1
    async with transaction(sm) as session:
        rows = await list_events(session, run_id)
    assert [r.created_at for r in rows] == [150]
