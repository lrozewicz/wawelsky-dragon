"""Testy ``IntegrationCore.test_saved`` i kursora ``before_id`` przebiegów (brief T1, E4-3b §3).

Bez HTTP: usługa na świeżej bazie i ``SecretFake`` pod typem ``sharepoint`` (wzorzec
``test_service_ops.py``). Weryfikujemy też brak zapisu i brak audytu po ``test_saved``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import NotFound, ValidationFailed
from app.db.repositories import integrations as integrations_repo
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.base import ConnectionReport
from app.integrations.base import Container as RemoteContainer
from app.integrations.config import IntegrationsConfig
from app.services.audit import AuditService
from app.services.integration_input import (
    DEFAULT_EXCLUDED_LIBRARY_NAMES,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    TestOverrides,
    parse_create,
)
from app.services.integrations import Actor, IntegrationService
from tests.fakes.clock import FrozenClock
from tests.fakes.integrations import FakeConnector, fake_load_config
from tests.integration.integrations.conftest import TIME_MS, seed_dataset_and_user

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]
KEY_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
SECRET = "sharepoint-secret-abcd"  # noqa: S105 — dane testowe
OVERRIDE_SECRET = "nowy-sekret"  # noqa: S105 — dane testowe
TENANT_ID = "tenant-1"
CLIENT_ID = "client-1"
SITE_URL = "https://tenant.sharepoint.test/sites/eng"
SITE_ID = "S1"
SITE_NAME = "Eng"
DRIVES_TOTAL = 5
DRIVES_INCLUDED = 3
ACTOR = Actor("X-API-Secret")
RUN_COUNT = 5
CURSOR_LIMIT = 2
DATASET_NAME = "Korpus"

AUTH_OK: dict[str, object] = {"name": "graph_auth", "status": "ok", "detail": ""}
SITE_OK: dict[str, object] = {"name": "site_resolution", "status": "ok", "detail": ""}
RESOLVED: dict[str, object] = {
    "site_id": SITE_ID,
    "site_display_name": SITE_NAME,
    "libraries_total": DRIVES_TOTAL,
    "libraries_included": DRIVES_INCLUDED,
}
CONTAINERS = [RemoteContainer(id="c2", name="Zulu"), RemoteContainer(id="c1", name="Alfa")]


class SecretFake(FakeConnector):
    """Fake zapamiętujący ``cfg`` każdego testu połączenia (w tym plaintext sekretu)."""

    def __init__(self) -> None:
        super().__init__()
        self.report = ConnectionReport(ok=True, checks=[AUTH_OK, SITE_OK], resolved=RESOLVED)
        self.containers = list(CONTAINERS)
        self.cfgs: list[Any] = []
        self.dataset_flags: list[bool] = []
        self.list_calls = 0

    async def resolve(self, cfg: Any) -> dict[str, Any]:
        return {"site_id": SITE_ID, "site_display_name": SITE_NAME}

    async def test_connection(self, cfg: Any, *, dataset_exists: bool) -> ConnectionReport:
        self.cfgs.append(cfg)
        self.dataset_flags.append(dataset_exists)
        return self.report

    async def list_containers(self, cfg: Any) -> list[RemoteContainer]:
        self.list_calls += 1
        return self.containers


def secret_of(fake: SecretFake) -> str:
    """Plaintext sekretu z ostatniej konfiguracji przekazanej konektorowi."""
    return fake.cfgs[-1].client_secret.get_secret_value()


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
def sharepoint_fake() -> Iterator[SecretFake]:
    """``SecretFake`` pod typem ``sharepoint``; po teście czyści rejestr."""
    fake = SecretFake()
    registry.register("sharepoint", fake, fake_load_config)
    yield fake
    registry.clear()


@pytest.fixture
def service(container: Container) -> IntegrationService:
    """Usługa na kontenerze testowym z domyślną konfiguracją integracji."""
    return IntegrationService(container, IntegrationsConfig())


def create_body(dataset_id: str) -> dict[str, object]:
    """Ciało ``POST /api/integrations`` z kompletem pól wymaganych."""
    return {
        "name": "SP 1",
        "dataset_id": dataset_id,
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "client_secret": SECRET,
        "site_url": SITE_URL,
    }


def expected_report(dataset_exists: str, dataset_name: str | None = None) -> dict[str, object]:
    """Raport testu połączenia z pełnym sukcesem etapów 1 i 2."""
    report: dict[str, object] = {
        "graph_auth": "ok",
        "site_resolution": "ok",
        "site_id": SITE_ID,
        "site_display_name": SITE_NAME,
        "drives_visible": DRIVES_TOTAL,
        "drives_after_exclusion": DRIVES_INCLUDED,
        "drive_names": ["Zulu", "Alfa"],
        "dataset_exists": dataset_exists,
    }
    if dataset_name is not None:
        report["dataset_name"] = dataset_name
    return report


async def create_integration(sm: SM, service: IntegrationService) -> int:
    """Dataset + integracja przez usługę (z zapisanym zaszyfrowanym sekretem)."""
    _, dataset_id = await seed_dataset_and_user(sm)
    view = await service.create(parse_create(create_body(dataset_id)), ACTOR)
    return view.row.id


async def add_integration_without_secret(sm: SM, owner_id: str, dataset_id: str) -> int:
    """Integracja SharePoint bez kolumny ``secret_enc`` (wiersz + konfiguracja SharePoint)."""
    async with transaction(sm) as session:
        integration_id = await integrations_repo.insert_integration(
            session,
            type="sharepoint",
            name="Bez sekretu",
            dataset_id=dataset_id,
            owner_id=owner_id,
            config={},
            now_ms=TIME_MS,
        )
        await integrations_repo.upsert_sharepoint(
            session,
            integration_id=integration_id,
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            site_url=SITE_URL,
            site_id=SITE_ID,
            site_display_name=SITE_NAME,
            excluded_library_names=list(DEFAULT_EXCLUDED_LIBRARY_NAMES),
        )
    return integration_id


async def integration_row(sm: SM, integration_id: int) -> Any:
    """Wiersz ``integrations`` po ``id`` (bez zmiany: porównanie przed/po)."""
    async with transaction(sm) as session:
        row = await integrations_repo.get_integration(session, integration_id)
    assert row is not None
    return row


async def sharepoint_row(sm: SM, integration_id: int) -> Any:
    """Wiersz ``integration_sharepoint`` po ``id``."""
    async with transaction(sm) as session:
        row = await integrations_repo.get_sharepoint(session, integration_id)
    assert row is not None
    return row


async def audit_actions(sm: SM) -> list[str]:
    """Akcje wpisów audytu w kolejności zapisu (``test_saved`` nie może nic dopisać)."""
    sql = text("SELECT action FROM audit_log ORDER BY id")
    async with transaction(sm) as session:
        rows = (await session.execute(sql)).mappings().all()
    return [str(row["action"]) for row in rows]


async def add_run(sm: SM, integration_id: int) -> int:
    """Przebieg integracji; zwraca ``run_id`` (``id`` rosnąco w czasie)."""
    async with transaction(sm) as session:
        return await integrations_repo.insert_run(
            session,
            integration_id=integration_id,
            integration_type="sharepoint",
            run_trigger="manual",
            now_ms=TIME_MS,
        )


# --- test_saved -----------------------------------------------------------------


async def test_saved_uses_stored_secret_and_does_not_write(
    sm: SM, service: IntegrationService, sharepoint_fake: SecretFake
) -> None:
    integration_id = await create_integration(sm, service)
    before = await integration_row(sm, integration_id)
    before_sharepoint = await sharepoint_row(sm, integration_id)

    report = await service.test_saved(integration_id, TestOverrides())

    after = await integration_row(sm, integration_id)
    cfg = sharepoint_fake.cfgs[-1]
    assert report == expected_report("ok", DATASET_NAME)
    assert secret_of(sharepoint_fake) == SECRET
    assert cfg.integration_id == integration_id
    assert (cfg.tenant_id, cfg.client_id, cfg.site_url) == (TENANT_ID, CLIENT_ID, SITE_URL)
    assert cfg.tenant_id == before_sharepoint.tenant_id
    assert cfg.excluded_library_names == before_sharepoint.excluded_library_names
    assert cfg.excluded_library_names == list(DEFAULT_EXCLUDED_LIBRARY_NAMES)
    assert cfg.max_file_size_bytes == DEFAULT_MAX_FILE_SIZE_BYTES
    assert sharepoint_fake.dataset_flags == [True]
    assert sharepoint_fake.list_calls == 1
    assert (after.secret_enc, after.secret_last4, after.updated_at) == (
        before.secret_enc,
        before.secret_last4,
        before.updated_at,
    )
    assert await audit_actions(sm) == ["integration_created"]
    assert SECRET not in str(report)


async def test_saved_overrides_fields_without_persisting(
    sm: SM, service: IntegrationService, sharepoint_fake: SecretFake
) -> None:
    integration_id = await create_integration(sm, service)
    before = await integration_row(sm, integration_id)
    before_sharepoint = await sharepoint_row(sm, integration_id)

    report = await service.test_saved(
        integration_id,
        TestOverrides(
            tenant_id="tenant-2",
            client_id="client-2",
            client_secret=OVERRIDE_SECRET,
            site_url="https://other.sharepoint.test/sites/eng",
            excluded_library_names=["X"],
        ),
    )

    cfg = sharepoint_fake.cfgs[-1]
    after = await integration_row(sm, integration_id)
    after_sharepoint = await sharepoint_row(sm, integration_id)
    assert secret_of(sharepoint_fake) == OVERRIDE_SECRET
    assert (cfg.tenant_id, cfg.client_id, cfg.site_url) == (
        "tenant-2",
        "client-2",
        "https://other.sharepoint.test/sites/eng",
    )
    assert cfg.excluded_library_names == ["X"]
    assert report == expected_report("ok", DATASET_NAME)
    assert (after.secret_enc, after.secret_last4, after.updated_at) == (
        before.secret_enc,
        before.secret_last4,
        before.updated_at,
    )
    assert after_sharepoint == before_sharepoint
    assert await audit_actions(sm) == ["integration_created"]
    assert OVERRIDE_SECRET not in str(report)
    assert SECRET not in str(report)


async def test_saved_dataset_override_wins(
    sm: SM, service: IntegrationService, sharepoint_fake: SecretFake
) -> None:
    integration_id = await create_integration(sm, service)
    _, other_dataset_id = await seed_dataset_and_user(sm)

    found = await service.test_saved(integration_id, TestOverrides(dataset_id=other_dataset_id))
    missing = await service.test_saved(integration_id, TestOverrides(dataset_id="brak-datasetu"))

    assert found == expected_report("ok", DATASET_NAME)
    assert missing == expected_report("not_found")
    assert sharepoint_fake.dataset_flags == [True, False]


async def test_saved_missing_integration_returns_not_found(
    service: IntegrationService,
) -> None:
    with pytest.raises(NotFound) as excinfo:
        await service.test_saved(9999, TestOverrides())

    assert str(excinfo.value) == "Not found"
    assert SECRET not in str(excinfo.value)


async def test_saved_without_stored_secret_returns_validation_failed(
    sm: SM, service: IntegrationService
) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    integration_id = await add_integration_without_secret(sm, owner_id, dataset_id)

    with pytest.raises(ValidationFailed) as excinfo:
        await service.test_saved(integration_id, TestOverrides())

    assert str(excinfo.value) == "Integration has no stored secret."
    assert SECRET not in str(excinfo.value)


# --- kursor before_id -----------------------------------------------------------


async def test_list_runs_before_id_returns_older_page(
    sm: SM, service: IntegrationService, sharepoint_fake: SecretFake
) -> None:
    integration_id = await create_integration(sm, service)
    run_ids = [await add_run(sm, integration_id) for _ in range(RUN_COUNT)]
    before_id = run_ids[2]  # trzeci od góry; strona ma zwrócić dwa starsze przebiegi

    page = await service.list_runs(
        integration_type=None,
        integration_id=integration_id,
        limit=CURSOR_LIMIT,
        before_id=before_id,
    )

    assert [run.id for run in page] == [run_ids[1], run_ids[0]]
    assert all(run.id < before_id for run in page)


async def test_list_runs_without_before_id_is_unchanged(
    sm: SM, service: IntegrationService, sharepoint_fake: SecretFake
) -> None:
    integration_id = await create_integration(sm, service)
    run_ids = [await add_run(sm, integration_id) for _ in range(RUN_COUNT)]

    all_runs = await service.list_runs(
        integration_type=None, integration_id=integration_id, limit=RUN_COUNT
    )

    assert [run.id for run in all_runs] == sorted(run_ids, reverse=True)
