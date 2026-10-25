"""Odczytowe trasy SVC: AG-20 drives, AG-21 status, AG-22 runs, AG-23 events, `GET /api/datasets`.

Wszystkie asercje na **dokładnych zbiorach kluczy** DTO (03 §5) i na kolejności zwracanych
wierszy (`id DESC` dla przebiegów, `id ASC` dla zdarzeń, nazwa dla bibliotek).
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import NewEvent
from app.db.uow import transaction
from app.integrations.base import SyncCounts
from tests.contract.hub_compat.sharepoint.conftest import (
    CONTAINER_D1,
    CONTAINER_D1_NAME,
    CONTAINER_D2,
    CONTAINER_D2_NAME,
)

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

OK = 200
BAD_REQUEST = 400
NOT_FOUND = 404
NOW_MS = 1_790_157_600_000
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

DRIVE_KEYS = {"drive_id", "drive_name", "has_delta", "last_sync_at", "discovered_at"}
STATUS_KEYS = {"id", "is_active", "is_running", "last_sync_at", "last_sync_status", "latest_run"}
LATEST_RUN_KEYS = {
    "id",
    "started_at",
    "finished_at",
    "status",
    "added",
    "updated",
    "deleted",
    "failed",
}
RUN_KEYS = {
    "id",
    "integration_id",
    "integration_type",
    "started_at",
    "finished_at",
    "status",
    "added",
    "updated",
    "deleted",
    "failed",
}
EVENT_KEYS = {
    "id",
    "run_id",
    "integration_id",
    "integration_type",
    "level",
    "message",
    "file_path",
    "drive_id",
    "drive_name",
    "created_at",
}
DATASET_KEYS = {"id", "name", "document_count", "chunk_count", "embedding_model"}

RUN_COUNT = 25
PAGE_LIMIT = 20
CLAMPED_MIN = 1
DATASET_NAME = "Korpus"
EMBEDDING_MODEL = "fake-embed-1024"


async def insert_runs(
    sm: async_sessionmaker[AsyncSession], integration_id: int, count: int
) -> list[int]:
    """Wstawia `count` przebiegów (`id` rosnąco); zwraca ich identyfikatory."""
    ids: list[int] = []
    async with transaction(sm) as session:
        for index in range(count):
            ids.append(
                await integrations_repo.insert_run(
                    session,
                    integration_id=integration_id,
                    integration_type="sharepoint",
                    run_trigger="manual",
                    now_ms=NOW_MS + index,
                )
            )
    return ids


async def test_ag20_drives_dto_and_name_order(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-20: DTO z `has_delta`, kontenery rosnąco po nazwie, kursor w `d1` → `has_delta` true."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    async with transaction(sm) as session:
        await integrations_repo.upsert_container(
            session, created["id"], CONTAINER_D2, name=CONTAINER_D2_NAME, now_ms=NOW_MS
        )
        await integrations_repo.upsert_container(
            session, created["id"], CONTAINER_D1, name=CONTAINER_D1_NAME, now_ms=NOW_MS
        )
        await integrations_repo.set_container_cursor(
            session, created["id"], CONTAINER_D1, cursor="delta-1", now_ms=NOW_MS + 1
        )

    response = await svc.get(f"{prefix}/api/integrations/{created['id']}/drives")

    assert response.status_code == OK, response.text
    drives = response.json()["data"]
    assert [drive["drive_id"] for drive in drives] == [CONTAINER_D1, CONTAINER_D2]
    assert all(set(drive) == DRIVE_KEYS for drive in drives)
    assert drives[0]["drive_name"] == CONTAINER_D1_NAME
    assert drives[0]["has_delta"] is True
    assert drives[1]["has_delta"] is False
    assert drives[1]["last_sync_at"] is None
    assert ISO_RE.fullmatch(str(drives[0]["discovered_at"])) is not None
    assert ISO_RE.fullmatch(str(drives[0]["last_sync_at"])) is not None


async def test_ag20_drives_unknown_integration(svc: Any, prefix: str, connector: Any) -> None:
    """AG-20: nieznana integracja → 404 `{error}` SVC."""
    response = await svc.get(f"{prefix}/api/integrations/999999/drives")

    assert response.status_code == NOT_FOUND
    assert response.json() == {"error": "Not found"}


async def test_ag21_status_without_and_with_run(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-21: `latest_run` `null` bez przebiegu i obiekt z 8 kluczami po zakończonym przebiegu."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)

    before = await svc.get(f"{prefix}/api/integrations/{created['id']}/status")
    assert before.status_code == OK, before.text
    initial = before.json()["data"]
    assert set(initial) == STATUS_KEYS
    assert initial["id"] == created["id"]
    assert initial["is_active"] is True
    assert initial["is_running"] is False
    assert initial["last_sync_at"] is None
    assert initial["last_sync_status"] is None
    assert initial["latest_run"] is None

    async with transaction(sm) as session:
        run_id = await integrations_repo.insert_run(
            session,
            integration_id=created["id"],
            integration_type="sharepoint",
            run_trigger="manual",
            now_ms=NOW_MS,
        )
        await integrations_repo.finish_run(
            session,
            run_id,
            status="success",
            counts=SyncCounts(added=1, updated=2, deleted=3),
            now_ms=NOW_MS + 50,
        )

    after = await svc.get(f"{prefix}/api/integrations/{created['id']}/status")
    assert after.status_code == OK, after.text
    latest = after.json()["data"]["latest_run"]
    assert set(latest) == LATEST_RUN_KEYS
    assert latest["id"] == run_id
    assert latest["status"] == "success"
    assert (latest["added"], latest["updated"], latest["deleted"], latest["failed"]) == (1, 2, 3, 0)
    assert ISO_RE.fullmatch(str(latest["started_at"])) is not None
    assert ISO_RE.fullmatch(str(latest["finished_at"])) is not None


async def test_ag21_status_unknown_integration(svc: Any, prefix: str, connector: Any) -> None:
    """AG-21: nieznana integracja → 404 `{error}` SVC."""
    response = await svc.get(f"{prefix}/api/integrations/999999/status")

    assert response.status_code == NOT_FOUND
    assert response.json() == {"error": "Not found"}


async def test_ag22_runs_dto_limit_and_order(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-22: DTO z `integration_type`, `limit` respektowany i clampowany, kolejność `id DESC`."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    run_ids = await insert_runs(sm, created["id"], RUN_COUNT)
    base = f"{prefix}/api/integrations/runs"

    everything = await svc.get(base, params={"integration_id": created["id"]})
    assert everything.status_code == OK, everything.text
    runs = everything.json()["data"]
    assert len(runs) == RUN_COUNT
    assert [run["id"] for run in runs] == list(reversed(run_ids))
    assert all(set(run) == RUN_KEYS for run in runs)
    assert all(run["integration_type"] == "sharepoint" for run in runs)

    page = await svc.get(base, params={"integration_id": created["id"], "limit": PAGE_LIMIT})
    assert page.status_code == OK
    assert len(page.json()["data"]) == PAGE_LIMIT

    clamped_low = await svc.get(base, params={"integration_id": created["id"], "limit": 0})
    assert clamped_low.status_code == OK
    assert len(clamped_low.json()["data"]) == CLAMPED_MIN

    clamped_high = await svc.get(base, params={"integration_id": created["id"], "limit": 999})
    assert clamped_high.status_code == OK
    assert len(clamped_high.json()["data"]) == RUN_COUNT

    by_type = await svc.get(base, params={"type": "sharepoint"})
    assert by_type.status_code == OK
    assert len(by_type.json()["data"]) == RUN_COUNT

    other = await svc.get(base, params={"type": "fake"})
    assert other.status_code == OK
    assert other.json()["data"] == []

    absent = await svc.get(base, params={"integration_id": created["id"] + 1})
    assert absent.status_code == OK
    assert absent.json()["data"] == []


async def test_ag22_runs_reject_invalid_integration_id(
    svc: Any, prefix: str, connector: Any
) -> None:
    """AG-22/§4: `integration_id` nie-liczba → 400 „Invalid integration_id” (nie 422)."""
    response = await svc.get(f"{prefix}/api/integrations/runs", params={"integration_id": "abc"})

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json() == {"error": "Invalid integration_id"}


async def test_ag23_events_dto_filters_and_order(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-23: DTO zdarzeń, `after_id`, `limit` i kolejność `id ASC`; `drive_id`/`drive_name`."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    async with transaction(sm) as session:
        run_id = await integrations_repo.insert_run(
            session,
            integration_id=created["id"],
            integration_type="sharepoint",
            run_trigger="manual",
            now_ms=NOW_MS,
        )
        await integrations_repo.insert_events(
            session,
            [
                NewEvent(
                    run_id=run_id,
                    integration_id=created["id"],
                    integration_type="sharepoint",
                    level=level,
                    message=f"zdarzenie {level}",
                    file_path=f"/{level}.txt",
                    container_id=CONTAINER_D1,
                    container_name=CONTAINER_D1_NAME,
                    created_at=NOW_MS + index,
                )
                for index, level in enumerate(("info", "warn", "error"))
            ],
        )
    url = f"{prefix}/api/integrations/runs/{run_id}/events"

    everything = await svc.get(url)
    assert everything.status_code == OK, everything.text
    events = everything.json()["data"]
    assert len(events) == len(("info", "warn", "error"))
    assert all(set(event) == EVENT_KEYS for event in events)
    assert [event["level"] for event in events] == ["info", "warn", "error"]
    assert [event["id"] for event in events] == sorted(event["id"] for event in events)
    assert events[0]["drive_id"] == CONTAINER_D1
    assert events[0]["drive_name"] == CONTAINER_D1_NAME
    assert events[0]["integration_id"] == created["id"]
    assert ISO_RE.fullmatch(str(events[0]["created_at"])) is not None

    after = await svc.get(url, params={"after_id": events[0]["id"]})
    assert after.status_code == OK
    assert [event["level"] for event in after.json()["data"]] == ["warn", "error"]

    limited = await svc.get(url, params={"limit": 1})
    assert limited.status_code == OK
    assert len(limited.json()["data"]) == 1

    level = await svc.get(url, params={"level": "warn"})
    assert level.status_code == OK
    assert [event["level"] for event in level.json()["data"]] == ["warn"]


async def test_ag23_events_reject_bad_level_and_run_id(
    svc: Any, prefix: str, connector: Any
) -> None:
    """AG-23/§4: `level` spoza zbioru i niepoprawny `run_id` → 400 z komunikatem pola."""
    bad_level = await svc.get(f"{prefix}/api/integrations/runs/1/events", params={"level": "debug"})
    bad_run = await svc.get(f"{prefix}/api/integrations/runs/abc/events")
    zero_run = await svc.get(f"{prefix}/api/integrations/runs/0/events")

    assert bad_level.status_code == BAD_REQUEST
    assert bad_level.json() == {"error": "Invalid level (use info|warn|error)"}
    assert bad_run.status_code == BAD_REQUEST
    assert bad_run.json() == {"error": "Invalid run id"}
    assert zero_run.status_code == BAD_REQUEST
    assert zero_run.json() == {"error": "Invalid run id"}


async def test_datasets_route_lists_summaries(
    svc: Any, prefix: str, connector: Any, seed_dataset: Any
) -> None:
    """Tabela 03 §5: `GET /api/datasets` → listy datasetów z dokładnymi kluczami (K7 §7 p. 11)."""
    _owner, dataset_id = await seed_dataset()

    response = await svc.get(f"{prefix}/api/datasets")

    assert response.status_code == OK, response.text
    items = response.json()["data"]
    assert len(items) == 1
    assert all(set(item) == DATASET_KEYS for item in items)
    assert items[0] == {
        "id": dataset_id,
        "name": DATASET_NAME,
        "document_count": 0,
        "chunk_count": 0,
        "embedding_model": EMBEDDING_MODEL,
    }
