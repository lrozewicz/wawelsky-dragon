"""Trasy WD przebiegów: sync, cancel, status, drives, runs, events (brief T4, kontrakt E4-3b §4).

Wzorce: ``tests/contract/hub_compat/sharepoint/test_sync_cancel_status.py`` (prawdziwy ``Worker``)
i ``test_runs_events_drives_datasets.py`` (kursory i dokładne zbiory kluczy DTO).

Integracje zakładamy **usługą** (``app.state.integrations``), nie trasą WD — ``POST /integrations``
do chodzi dopiero w T3 (brief T4, „Przykłady”).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import NewEvent
from app.db.uow import transaction
from app.integrations.base import SyncCounts
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import SyncEngine
from app.services.integration_input import (
    DEFAULT_EXCLUDED_LIBRARY_NAMES,
    DEFAULT_IGNORED_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    IntegrationCreate,
)
from app.services.integration_ops import Actor
from app.services.integrations import IntegrationService
from app.worker.handlers.integration_sync import make_handler
from app.worker.loop import Worker
from tests.contract.wd.integrations.conftest import (
    CLIENT_ID,
    CLIENT_SECRET,
    SITE_URL,
    TENANT_ID,
)

pytestmark = pytest.mark.contract

WD = "/api/wd/v1"
OK = 200
ACCEPTED = 202
BAD_REQUEST = 400
UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404
CONFLICT = 409

NOW_MS = 1_790_157_600_000
RUN_COUNT = 3
PAGE_LIMIT = 2
WORKER_SHUTDOWN_S = 15

ISO_MS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

CONTAINER_D1 = "d1"
CONTAINER_D1_NAME = "Dokumenty"
CONTAINER_D2 = "d2"
CONTAINER_D2_NAME = "Wspólne"

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

MakeIntegration = Callable[[str], Coroutine[Any, Any, int]]


@pytest.fixture
def make_integration(app: FastAPI, connector: Any) -> MakeIntegration:
    """Zakłada integrację usługą aplikacji (wymaga zaślepki konektora) i zwraca jej ``id``."""
    service: IntegrationService = app.state.integrations

    async def _make(dataset_id: str) -> int:
        view = await service.create(
            IntegrationCreate(
                name="SP test",
                dataset_id=dataset_id,
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                site_url=SITE_URL,
                excluded_library_names=list(DEFAULT_EXCLUDED_LIBRARY_NAMES),
                max_file_size_bytes=DEFAULT_MAX_FILE_SIZE_BYTES,
                ignored_extensions=list(DEFAULT_IGNORED_EXTENSIONS),
                scan_interval_seconds=DEFAULT_SCAN_INTERVAL_SECONDS,
                delete_propagation=True,
                is_active=True,
            ),
            Actor(label="wd-test"),
        )
        return view.row.id

    return _make


@pytest.fixture
async def worker(container: Container) -> AsyncIterator[None]:
    """Prawdziwy ``Worker`` z handlerem ``integration_sync`` (bez sieci i bez ``sleep``)."""
    engine = SyncEngine(container, IntegrationsConfig())
    instance = Worker(container, {"integration_sync": make_handler(engine)})
    stop = asyncio.Event()
    runner = asyncio.create_task(instance.run(stop))
    yield
    stop.set()
    await asyncio.wait_for(runner, timeout=WORKER_SHUTDOWN_S)


async def insert_runs(
    sm: async_sessionmaker[AsyncSession], integration_id: int, count: int
) -> list[int]:
    """Wstawia ``count`` zakończonych przebiegów (``id`` rosnąco); zwraca ich identyfikatory."""
    ids: list[int] = []
    async with transaction(sm) as session:
        for index in range(count):
            run_id = await integrations_repo.insert_run(
                session,
                integration_id=integration_id,
                integration_type="sharepoint",
                run_trigger="manual",
                now_ms=NOW_MS + index,
            )
            await integrations_repo.finish_run(
                session,
                run_id,
                status="success",
                counts=SyncCounts(added=index, updated=0, deleted=0),
                now_ms=NOW_MS + index + 1,
            )
            ids.append(run_id)
    return ids


async def test_sync_queues_and_returns_accepted(
    admin: Any, make_integration: MakeIntegration, seed_dataset: Any
) -> None:
    """``POST /sync`` bez ``wait`` → 202 ``{"data":{"queued":true}}`` (brief, wiersz 1)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)

    response = await admin.post(f"{WD}/integrations/{integration_id}/sync")

    assert response.status_code == ACCEPTED, response.text
    assert response.json() == {"data": {"queued": True}}


async def test_sync_conflict_when_running(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Zajęty lock przebiegu → 409 ``conflict`` (brief, wiersz 2)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)
    async with transaction(sm) as session:
        assert await integrations_repo.try_lock(
            session, integration_id, owner="worker-1", now_ms=NOW_MS
        )

    response = await admin.post(f"{WD}/integrations/{integration_id}/sync")

    assert response.status_code == CONFLICT, response.text
    assert response.json()["error"]["code"] == "conflict"


async def test_sync_wait_returns_finished_run(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    worker: None,
) -> None:
    """``?wait=true`` z prawdziwym Workerem → 200 ``{"data": IntegrationRun}`` (brief, wiersz 3)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)

    response = await admin.post(f"{WD}/integrations/{integration_id}/sync", params={"wait": "true"})

    assert response.status_code == OK, response.text
    run = response.json()["data"]
    assert set(run) == RUN_KEYS
    assert run["integration_id"] == integration_id
    assert run["integration_type"] == "sharepoint"
    assert run["status"] in {"success", "partial", "failed", "cancelled"}
    assert ISO_MS_RE.fullmatch(str(run["started_at"])) is not None
    assert ISO_MS_RE.fullmatch(str(run["finished_at"])) is not None
    assert CLIENT_SECRET not in response.text


async def test_sync_unknown_integration_is_404(admin: Any, connector: Any) -> None:
    """``POST /integrations/999999/sync`` → 404 ``not_found`` (brief, wiersz 4)."""
    response = await admin.post(f"{WD}/integrations/999999/sync")

    assert response.status_code == NOT_FOUND, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_cancel_without_running_sync_is_false(
    admin: Any, make_integration: MakeIntegration, seed_dataset: Any
) -> None:
    """Bez przebiegu → 200 ``{"data":{"cancelled":false}}`` (brief, wiersz 5)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)

    response = await admin.post(f"{WD}/integrations/{integration_id}/cancel")

    assert response.status_code == OK, response.text
    assert response.json() == {"data": {"cancelled": False}}


async def test_cancel_unknown_integration_is_404(admin: Any, connector: Any) -> None:
    """Anulowanie nieznanej integracji → 404 ``not_found``."""
    response = await admin.post(f"{WD}/integrations/999999/cancel")

    assert response.status_code == NOT_FOUND, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_status_without_and_with_run(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """``GET /status`` → ``latest_run: null``, a po przebiegu obiekt (brief, wiersz 6)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)

    before = await admin.get(f"{WD}/integrations/{integration_id}/status")
    assert before.status_code == OK, before.text
    initial = before.json()["data"]
    assert set(initial) == STATUS_KEYS
    assert initial["id"] == integration_id
    assert initial["latest_run"] is None

    run_ids = await insert_runs(sm, integration_id, 1)
    after = await admin.get(f"{WD}/integrations/{integration_id}/status")
    assert after.status_code == OK, after.text
    latest = after.json()["data"]["latest_run"]
    assert set(latest) == LATEST_RUN_KEYS
    assert latest["id"] == run_ids[0]
    assert CLIENT_SECRET not in after.text


async def test_status_unknown_integration_is_404(admin: Any, connector: Any) -> None:
    """Status nieznanej integracji → 404 ``not_found``."""
    response = await admin.get(f"{WD}/integrations/999999/status")

    assert response.status_code == NOT_FOUND, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_drives_returns_items(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """``GET /drives`` → 200 ``{"data":{"items":[…]}}`` z ``drive_id`` (brief, wiersz 7)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)
    async with transaction(sm) as session:
        await integrations_repo.upsert_container(
            session, integration_id, CONTAINER_D2, name=CONTAINER_D2_NAME, now_ms=NOW_MS
        )
        await integrations_repo.upsert_container(
            session, integration_id, CONTAINER_D1, name=CONTAINER_D1_NAME, now_ms=NOW_MS
        )
        await integrations_repo.set_container_cursor(
            session, integration_id, CONTAINER_D1, cursor="delta-1", now_ms=NOW_MS + 1
        )

    response = await admin.get(f"{WD}/integrations/{integration_id}/drives")

    assert response.status_code == OK, response.text
    body = response.json()
    assert set(body) == {"data"}
    items = body["data"]["items"]
    assert [drive["drive_id"] for drive in items] == [CONTAINER_D1, CONTAINER_D2]
    assert all(set(drive) == DRIVE_KEYS for drive in items)
    assert items[0]["has_delta"] is True
    assert items[1]["has_delta"] is False


async def test_drives_unknown_integration_is_404(admin: Any, connector: Any) -> None:
    """Biblioteki nieznanej integracji → 404 ``not_found``."""
    response = await admin.get(f"{WD}/integrations/999999/drives")

    assert response.status_code == NOT_FOUND, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_runs_cursor_descending(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """``GET /runs?limit=2`` przy 3 przebiegach: ``id`` malejąco i ``next_after_id`` (wiersz 8)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)
    run_ids = await insert_runs(sm, integration_id, RUN_COUNT)
    url = f"{WD}/integrations/{integration_id}/runs"

    page = await admin.get(url, params={"limit": PAGE_LIMIT})
    assert page.status_code == OK, page.text
    body = page.json()["data"]
    assert set(body) == {"items", "next_after_id"}
    assert [run["id"] for run in body["items"]] == list(reversed(run_ids))[:PAGE_LIMIT]
    assert all(set(run) == RUN_KEYS for run in body["items"])
    assert body["next_after_id"] == run_ids[1]

    second = await admin.get(url, params={"limit": PAGE_LIMIT, "after_id": body["next_after_id"]})
    assert second.status_code == OK, second.text
    rest = second.json()["data"]
    assert [run["id"] for run in rest["items"]] == [run_ids[0]]
    assert rest["next_after_id"] is None


async def test_runs_limit_zero_is_validation_failed(
    admin: Any, make_integration: MakeIntegration, seed_dataset: Any
) -> None:
    """``GET /runs?limit=0`` → 400 ``validation_failed`` w kopercie WD (brief, wiersz 9)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)

    response = await admin.get(f"{WD}/integrations/{integration_id}/runs", params={"limit": 0})

    assert response.status_code == BAD_REQUEST, response.text
    body = response.json()["error"]
    assert body["code"] == "validation_failed"
    assert body["details"]["errors"]


async def test_runs_unknown_integration_is_404(admin: Any, connector: Any) -> None:
    """Historia nieznanej integracji → 404 ``not_found`` tylko z trasy (brief, „najpierw get”)."""
    response = await admin.get(f"{WD}/integrations/999999/runs")

    assert response.status_code == NOT_FOUND, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_events_cursor_ascending(
    admin: Any,
    make_integration: MakeIntegration,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """``GET /runs/{id}/events?limit=2`` przy 3 zdarzeniach: ``id`` rosnąco (brief, wiersz 10)."""
    dataset_id = await seed_dataset()
    integration_id = await make_integration(dataset_id)
    async with transaction(sm) as session:
        run_id = await integrations_repo.insert_run(
            session,
            integration_id=integration_id,
            integration_type="sharepoint",
            run_trigger="manual",
            now_ms=NOW_MS,
        )
        await integrations_repo.insert_events(
            session,
            [
                NewEvent(
                    run_id=run_id,
                    integration_id=integration_id,
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
    url = f"{WD}/runs/{run_id}/events"

    page = await admin.get(url, params={"limit": PAGE_LIMIT})
    assert page.status_code == OK, page.text
    body = page.json()["data"]
    assert set(body) == {"items", "next_after_id"}
    assert [event["level"] for event in body["items"]] == ["info", "warn"]
    assert all(set(event) == EVENT_KEYS for event in body["items"])
    assert body["items"][0]["drive_id"] == CONTAINER_D1
    assert body["items"][0]["drive_name"] == CONTAINER_D1_NAME
    assert ISO_MS_RE.fullmatch(str(body["items"][0]["created_at"])) is not None
    assert body["next_after_id"] == body["items"][1]["id"]

    rest = await admin.get(url, params={"after_id": body["next_after_id"]})
    assert rest.status_code == OK, rest.text
    tail = rest.json()["data"]
    assert [event["level"] for event in tail["items"]] == ["error"]
    assert tail["next_after_id"] is None


async def test_events_bad_level_is_validation_failed(admin: Any, connector: Any) -> None:
    """``GET /runs/1/events?level=debug`` → 400 ``validation_failed`` (brief, wiersz 11)."""
    response = await admin.get(f"{WD}/runs/1/events", params={"level": "debug"})

    assert response.status_code == BAD_REQUEST, response.text
    body = response.json()["error"]
    assert body["code"] == "validation_failed"
    assert body["details"]["errors"]


async def test_events_unknown_run_is_empty_page(admin: Any, connector: Any) -> None:
    """``GET /runs/999999/events`` → 200 pusta strona, nie 404 (brief, wiersz 12)."""
    response = await admin.get(f"{WD}/runs/999999/events")

    assert response.status_code == OK, response.text
    assert response.json() == {"data": {"items": [], "next_after_id": None}}


AUTH_CASES = (
    ("POST", f"{WD}/integrations/1/sync"),
    ("POST", f"{WD}/integrations/1/cancel"),
    ("GET", f"{WD}/integrations/1/status"),
    ("GET", f"{WD}/integrations/1/drives"),
    ("GET", f"{WD}/integrations/1/runs"),
    ("GET", f"{WD}/runs/1/events"),
    ("GET", f"{WD}/documents/abc/source-link"),
)


@pytest.mark.parametrize(("method", "path"), AUTH_CASES)
async def test_routes_reject_anonymous(anon: Any, method: str, path: str) -> None:
    """Każda trasa bez nagłówka → 401 ``unauthorized`` (brief, „Testy negatywne”)."""
    response = await anon.request(method, path)

    assert response.status_code == UNAUTHORIZED, response.text
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path"), AUTH_CASES)
async def test_routes_reject_member(member: Any, method: str, path: str) -> None:
    """Każda trasa jako zwykły użytkownik → 403 ``permission_denied`` (kontrakt §0 p. 2)."""
    response = await member.request(method, path)

    assert response.status_code == FORBIDDEN, response.text
    assert response.json()["error"]["code"] == "permission_denied"
