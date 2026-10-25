"""Testy ``IntegrationService``: test połączenia, sync/cancel, odczyty (brief T2b, kontrakt §3).

Bez HTTP i bez workera: zlecenie sync sprawdzamy na tabeli ``tasks``, a zakończony przebieg
na wierszach ``integration_sync_runs``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import Conflict, NotFound
from app.db.repositories import audit_log as audit_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import NewEvent
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.base import ConnectionReport
from app.integrations.base import Container as RemoteContainer
from app.integrations.config import IntegrationsConfig
from app.services.audit import AuditService
from app.services.integration_input import parse_create, parse_test_connection
from app.services.integration_runs import CancelResult
from app.services.integrations import Actor, IntegrationService, SyncOutcome
from tests.fakes.clock import FrozenClock
from tests.fakes.integrations import FakeConnector, fake_load_config
from tests.integration.integrations.conftest import TIME_MS, seed_dataset_and_user

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]
KEY_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
SECRET = "sharepoint-secret-abcd"  # noqa: S105 — dane testowe
TENANT_ID = "tenant-1"
CLIENT_ID = "client-1"
SITE_URL = "https://tenant.sharepoint.test/sites/eng"
SITE_ID = "S1"
SITE_NAME = "Eng"
DRIVES_TOTAL = 5
DRIVES_INCLUDED = 3
ACTOR = Actor("X-API-Secret")
WAIT_TIMEOUT_ZERO = 0
EVENT_LIMIT = 2
RUN_LIMIT = 1

AUTH_OK: dict[str, object] = {"name": "graph_auth", "status": "ok", "detail": ""}
SITE_OK: dict[str, object] = {"name": "site_resolution", "status": "ok", "detail": ""}
RESOLVED: dict[str, object] = {
    "site_id": SITE_ID,
    "site_display_name": SITE_NAME,
    "libraries_total": DRIVES_TOTAL,
    "libraries_included": DRIVES_INCLUDED,
}
CONTAINERS = [RemoteContainer(id="c2", name="Zulu"), RemoteContainer(id="c1", name="Alfa")]


class ReportFake(FakeConnector):
    """Fake z ustalonym raportem testu połączenia; liczy listy kontenerów i flagi datasetu."""

    def __init__(self) -> None:
        super().__init__()
        self.report = ConnectionReport(ok=True, checks=[AUTH_OK, SITE_OK], resolved=RESOLVED)
        self.containers = list(CONTAINERS)
        self.dataset_flags: list[bool] = []
        self.list_calls = 0
        self.resolved: dict[str, Any] = {"site_id": SITE_ID, "site_display_name": SITE_NAME}

    async def resolve(self, cfg: Any) -> dict[str, Any]:
        return self.resolved

    async def test_connection(self, cfg: Any, *, dataset_exists: bool) -> ConnectionReport:
        self.dataset_flags.append(dataset_exists)
        return self.report

    async def list_containers(self, cfg: Any) -> list[RemoteContainer]:
        self.list_calls += 1
        return self.containers


@pytest.fixture
def container(migrated_db: Settings, sm: SM, tmp_path: Path, clock: FrozenClock) -> Container:
    """Kontener bez ``start()``: sessionmaker ze świeżej bazy, klucz krypto, storage w tmp."""
    settings = migrated_db.model_copy(
        update={"storage_root": str(tmp_path), "crypto_key": SecretStr(KEY_HEX)}
    )
    instance = Container(settings, clock=clock)
    instance.sessionmaker = sm
    instance.audit = AuditService(sm, settings, clock)
    return instance


@pytest.fixture
def sharepoint_fake() -> Iterator[ReportFake]:
    """``ReportFake`` pod typem ``sharepoint``; po teście czyści rejestr (kontrakt §5)."""
    fake = ReportFake()
    registry.register("sharepoint", fake, fake_load_config)
    yield fake
    registry.clear()


@pytest.fixture
def service(container: Container) -> IntegrationService:
    """Usługa na kontenerze testowym z domyślną konfiguracją integracji."""
    return IntegrationService(container, IntegrationsConfig())


def create_body(dataset_id: str, **overrides: object) -> dict[str, object]:
    """Ciało ``POST /api/integrations`` z kompletem pól wymaganych."""
    body: dict[str, object] = {
        "name": "SP 1",
        "dataset_id": dataset_id,
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "client_secret": SECRET,
        "site_url": SITE_URL,
    }
    body.update(overrides)
    return body


def connection_body(**overrides: object) -> dict[str, object]:
    """Ciało ``POST /api/integrations/test-connection``."""
    body: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "client_secret": SECRET,
        "site_url": SITE_URL,
    }
    body.update(overrides)
    return body


def expected_report(**overrides: object) -> dict[str, object]:
    """Pełny sukces testu połączenia (etapy 1 i 2) z nadpisanymi polami."""
    report: dict[str, object] = {
        "graph_auth": "ok",
        "site_resolution": "ok",
        "site_id": SITE_ID,
        "site_display_name": SITE_NAME,
        "drives_visible": DRIVES_TOTAL,
        "drives_after_exclusion": DRIVES_INCLUDED,
        "drive_names": ["Zulu", "Alfa"],
        "dataset_exists": "skipped",
    }
    report.update(overrides)
    return report


async def create_integration(sm: SM, service: IntegrationService) -> int:
    """Dataset + integracja przez usługę; zwraca ``integration_id``."""
    _, dataset_id = await seed_dataset_and_user(sm)
    view = await service.create(parse_create(create_body(dataset_id)), ACTOR)
    return view.row.id


async def sync_tasks(sm: SM) -> list[dict[str, Any]]:
    """Zadania ``integration_sync`` w kolejności zlecenia (payload z JSON)."""
    sql = text(
        "SELECT payload, priority, status FROM tasks"
        " WHERE task_type = 'integration_sync' ORDER BY id"
    )
    async with transaction(sm) as session:
        rows = (await session.execute(sql)).mappings().all()
    tasks = []
    for row in rows:
        task = dict(row)
        if isinstance(task["payload"], str):
            task["payload"] = json.loads(task["payload"])
        tasks.append(task)
    return tasks


async def audit_rows(sm: SM, action: str) -> list[Any]:
    """Wpisy audytu danej akcji."""
    async with transaction(sm) as session:
        return await audit_repo.list_by_action(session, action)


async def add_container(sm: SM, integration_id: int, container_id: str, name: str) -> None:
    """Kontener integracji (``discovered_at`` z zegara testów)."""
    async with transaction(sm) as session:
        await integrations_repo.upsert_container(
            session, integration_id, container_id, name=name, now_ms=TIME_MS
        )


async def add_run(sm: SM, integration_id: int, *, integration_type: str = "sharepoint") -> int:
    """Przebieg integracji; zwraca ``run_id``."""
    async with transaction(sm) as session:
        return await integrations_repo.insert_run(
            session,
            integration_id=integration_id,
            integration_type=integration_type,
            run_trigger="manual",
            now_ms=TIME_MS,
        )


async def add_events(sm: SM, integration_id: int, run_id: int, levels: list[str]) -> None:
    """Zdarzenia przebiegu (``created_at`` rosnąco)."""
    events = [
        NewEvent(
            run_id=run_id,
            integration_id=integration_id,
            integration_type="sharepoint",
            level=level,
            message=f"zdarzenie {index}",
            file_path=None,
            container_id="c1",
            container_name="Dokumenty",
            created_at=TIME_MS + index,
        )
        for index, level in enumerate(levels)
    ]
    async with transaction(sm) as session:
        await integrations_repo.insert_events(session, events)


async def set_running(sm: SM, integration_id: int) -> None:
    """Zakłada lock przebiegu (``is_running=1``) — worker w tle."""
    async with transaction(sm) as session:
        assert await integrations_repo.try_lock(
            session, integration_id, owner="worker-1", now_ms=TIME_MS
        )


# --- test połączenia ------------------------------------------------------------


async def test_test_connection_full_success(
    service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    report = await service.test_connection(parse_test_connection(connection_body()))

    assert report == expected_report()
    assert sharepoint_fake.dataset_flags == [False]
    assert sharepoint_fake.list_calls == 1


async def test_test_connection_dataset_statuses(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)

    skipped = await service.test_connection(parse_test_connection(connection_body()))
    found = await service.test_connection(
        parse_test_connection(connection_body(dataset_id=dataset_id))
    )
    missing = await service.test_connection(
        parse_test_connection(connection_body(dataset_id=uuid.uuid4().hex))
    )

    assert skipped["dataset_exists"] == "skipped"
    assert found == expected_report(dataset_exists="ok", dataset_name="Korpus")
    assert missing == expected_report(dataset_exists="not_found")
    assert sharepoint_fake.dataset_flags == [False, True, False]


async def test_test_connection_graph_auth_failure_returns_early(
    service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    sharepoint_fake.report = ConnectionReport(
        ok=False,
        checks=[{"name": "graph_auth", "status": "failed", "detail": "bad secret"}],
        resolved={},
    )

    report = await service.test_connection(parse_test_connection(connection_body()))

    assert report == {
        "graph_auth": "failed",
        "graph_auth_error": "bad secret",
        "site_resolution": "skipped",
        "dataset_exists": "skipped",
    }
    assert sharepoint_fake.list_calls == 0
    assert SECRET not in json.dumps(report)


async def test_test_connection_without_graph_auth_check_fails(
    service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    sharepoint_fake.report = ConnectionReport(ok=True, checks=[], resolved={})

    report = await service.test_connection(parse_test_connection(connection_body()))

    assert report == {
        "graph_auth": "failed",
        "graph_auth_error": "graph auth failed",
        "site_resolution": "skipped",
        "dataset_exists": "skipped",
    }
    assert sharepoint_fake.list_calls == 0


async def test_test_connection_site_resolution_failure(
    service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    sharepoint_fake.report = ConnectionReport(
        ok=False,
        checks=[
            AUTH_OK,
            {"name": "site_resolution", "status": "failed", "detail": "site not found"},
        ],
        resolved={},
    )

    report = await service.test_connection(parse_test_connection(connection_body()))

    assert report == {
        "graph_auth": "ok",
        "site_resolution": "failed",
        "site_resolution_error": "site not found",
        "dataset_exists": "skipped",
    }
    assert sharepoint_fake.list_calls == 0


# --- sync / cancel --------------------------------------------------------------


async def test_sync_without_wait_enqueues_task(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    integration_id = await create_integration(sm, service)

    manual = await service.sync(integration_id, full=False, wait=False, actor=ACTOR)
    full = await service.sync(integration_id, full=True, wait=False, actor=ACTOR)

    assert manual == SyncOutcome(True, False, None)
    assert full == SyncOutcome(True, True, None)
    assert await sync_tasks(sm) == [
        {
            "payload": {"integration_id": integration_id, "trigger": "manual"},
            "priority": 1,
            "status": "queued",
        },
        {
            "payload": {"integration_id": integration_id, "trigger": "full"},
            "priority": 1,
            "status": "queued",
        },
    ]
    entries = await audit_rows(sm, "integration_sync_requested")
    assert [entry.details for entry in entries] == [
        {"full": False, "wait": False},
        {"full": True, "wait": False},
    ]
    assert [entry.target_id for entry in entries] == [str(integration_id)] * 2


async def test_sync_wait_timeout_returns_outcome_without_run(
    container: Container, sm: SM, sharepoint_fake: ReportFake
) -> None:
    service = IntegrationService(container, IntegrationsConfig(wait_timeout_seconds=0))
    integration_id = await create_integration(sm, service)

    outcome = await service.sync(integration_id, full=False, wait=True, actor=ACTOR)

    assert outcome == SyncOutcome(True, False, None)


async def test_sync_while_running_conflicts(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    integration_id = await create_integration(sm, service)
    await set_running(sm, integration_id)

    with pytest.raises(Conflict) as excinfo:
        await service.sync(integration_id, full=False, wait=False, actor=ACTOR)

    assert str(excinfo.value) == "Sync already running"
    assert await sync_tasks(sm) == []


async def test_sync_missing_returns_not_found(service: IntegrationService) -> None:
    with pytest.raises(NotFound) as excinfo:
        await service.sync(404, full=False, wait=False, actor=ACTOR)
    assert str(excinfo.value) == "Not found"


async def test_cancel_returns_result_and_audit(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    integration_id = await create_integration(sm, service)

    result = await service.cancel(integration_id, ACTOR)

    assert result == CancelResult(False, False, 0)
    entry = (await audit_rows(sm, "integration_cancelled"))[0]
    assert entry.details == {
        "was_running_in_process": False,
        "lock_cleared": False,
        "runs_marked_cancelled": 0,
    }
    assert entry.target_id == str(integration_id)


async def test_cancel_missing_returns_not_found(service: IntegrationService) -> None:
    with pytest.raises(NotFound) as excinfo:
        await service.cancel(404, ACTOR)
    assert str(excinfo.value) == "Not found"


# --- odczyty --------------------------------------------------------------------


async def test_drives_sorted_by_name(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    integration_id = await create_integration(sm, service)
    await add_container(sm, integration_id, "a", "Zulu")
    await add_container(sm, integration_id, "b", "Alfa")

    drives = await service.drives(integration_id)

    assert [(drive.container_id, drive.name) for drive in drives] == [("b", "Alfa"), ("a", "Zulu")]


async def test_drives_missing_returns_not_found(service: IntegrationService) -> None:
    with pytest.raises(NotFound) as excinfo:
        await service.drives(404)
    assert str(excinfo.value) == "Not found"


async def test_status_returns_latest_run(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    integration_id = await create_integration(sm, service)
    run_id = await add_run(sm, integration_id)

    view = await service.status(integration_id)

    assert view.row.id == integration_id
    assert view.latest_run is not None
    assert (view.latest_run.id, view.latest_run.status) == (run_id, "running")


async def test_status_missing_returns_not_found(service: IntegrationService) -> None:
    with pytest.raises(NotFound) as excinfo:
        await service.status(404)
    assert str(excinfo.value) == "Not found"


async def test_list_runs_passes_filters(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    first = await create_integration(sm, service)
    second = await create_integration(sm, service)
    first_run = await add_run(sm, first)
    second_run = await add_run(sm, second)
    foreign_run = await add_run(sm, second, integration_type="fake")

    by_integration = await service.list_runs(integration_type=None, integration_id=first, limit=10)
    by_type = await service.list_runs(integration_type="fake", integration_id=None, limit=10)
    newest = await service.list_runs(integration_type=None, integration_id=None, limit=RUN_LIMIT)

    assert [run.id for run in by_integration] == [first_run]
    assert [run.id for run in by_type] == [foreign_run]
    assert [run.id for run in newest] == [foreign_run]
    assert second_run not in [run.id for run in newest]


async def test_list_events_passes_filters(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    integration_id = await create_integration(sm, service)
    run_id = await add_run(sm, integration_id)
    await add_events(sm, integration_id, run_id, ["info", "error", "info"])

    page = await service.list_events(run_id, after_id=0, level=None, limit=10)
    errors = await service.list_events(run_id, after_id=0, level="error", limit=10)
    short = await service.list_events(run_id, after_id=1, level=None, limit=EVENT_LIMIT)

    assert [event.message for event in page] == ["zdarzenie 0", "zdarzenie 1", "zdarzenie 2"]
    assert [event.message for event in errors] == ["zdarzenie 1"]
    assert [event.message for event in short] == ["zdarzenie 1", "zdarzenie 2"]


async def test_list_datasets_returns_summaries(
    sm: SM, service: IntegrationService, sharepoint_fake: ReportFake
) -> None:
    owner_id, _ = await seed_dataset_and_user(sm)
    for name in ["Zulu", "Alfa"]:
        async with transaction(sm) as session:
            await datasets_repo.insert(
                session,
                id=uuid.uuid4().hex,
                tenant_id=owner_id,
                created_by=owner_id,
                name=name,
                description=None,
                avatar=None,
                language="Polish",
                embedding_model="fake-embed-1024",
                embedding_dim=1024,
                permission="me",
                chunk_method="naive",
                parser_config={"chunk_token_num": 128, "delimiter": "\n"},
                now_ms=TIME_MS,
            )

    summaries = await service.list_datasets()

    assert [summary.name for summary in summaries] == ["Alfa", "Korpus", "Zulu"]
    assert {(item.document_count, item.chunk_count) for item in summaries} == {(0, 0)}
