"""Testy ``IntegrationService``: create/get/list/update/delete, sekrety i audyt (brief T2b).

Bez HTTP: usługa na prawdziwej MariaDB, konektor pod typem ``sharepoint`` z rejestru
(``FakeConnector``). Asercje patrzą na artefakty w bazie (``integrations``,
``integration_sharepoint``, ``audit_log``), nie na kod wyjścia.
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
from app.core.errors import Conflict, NotFound, UpstreamError, ValidationFailed
from app.core.timeutil import from_ms
from app.db.repositories import audit_log as audit_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.documents import DocumentRow
from app.db.repositories.integrations import MappingRow, NewEvent
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.config import IntegrationsConfig
from app.services.audit import AuditService
from app.services.integration_input import (
    DEFAULT_EXCLUDED_LIBRARY_NAMES,
    parse_create,
    parse_update,
)
from app.services.integration_runs import CancelResult
from app.services.integrations import Actor, IntegrationService
from tests.fakes.clock import FrozenClock
from tests.fakes.integrations import FakeConnector, fake_load_config
from tests.integration.integrations.conftest import TIME_MS, seed_dataset_and_user

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]
# Klucz testowy (64 hex), nie sekret produkcyjny — conftest nie ustawia WD_CRYPTO_KEY.
KEY_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
SECRET = "sharepoint-secret-abcd"  # noqa: S105 — dane testowe
ROTATED_SECRET = "rotated-secret-9876"  # noqa: S105 — dane testowe
SITE_ID = "S1"
SITE_NAME = "Eng"
TENANT_ID = "tenant-1"
CLIENT_ID = "client-1"
SITE_URL = "https://tenant.sharepoint.test/sites/eng"
CONTAINER_ID = "c1"
ITEM_ID = "i1"
INTEGRATION_NAME = "SP 1"
NEW_NAME = "SP po zmianie"
ACTOR = Actor("X-API-Secret", ip="10.0.0.7")
PARSER_CONFIG = {"chunk_token_num": 128, "delimiter": "\n"}
RESOLVE_CALLS_AFTER_UPDATE = 2  # create + update


class SiteFake(FakeConnector):
    """Fake konektora z konfigurowalnym ``resolve`` i licznikiem wywołań (kontrakt C8)."""

    def __init__(self) -> None:
        super().__init__()
        self.resolved: dict[str, Any] = {"site_id": SITE_ID, "site_display_name": SITE_NAME}
        self.resolve_error: Exception | None = None
        self.resolve_calls = 0

    async def resolve(self, cfg: Any) -> dict[str, Any]:
        self.resolve_calls += 1
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.resolved


class RecordingRuns:
    """Atrapa ``IntegrationRunsService``: notuje wywołania i zwraca ustalony ``CancelResult``."""

    def __init__(self) -> None:
        self.cancelled: list[int] = []
        self.result = CancelResult(True, True, 1)

    async def request_sync(self, integration_id: int, *, full: bool) -> str:
        return "task-1"

    async def wait_for_run(
        self, integration_id: int, *, since_run_id: int | None, timeout_s: float
    ) -> None:
        return None

    async def cancel(self, integration_id: int) -> CancelResult:
        self.cancelled.append(integration_id)
        return self.result


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
def sharepoint_fake() -> Iterator[SiteFake]:
    """``SiteFake`` pod typem ``sharepoint``; po teście czyści rejestr (kontrakt §5)."""
    fake = SiteFake()
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
        "name": INTEGRATION_NAME,
        "dataset_id": dataset_id,
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "client_secret": SECRET,
        "site_url": SITE_URL,
    }
    body.update(overrides)
    return body


async def integration_count(sm: SM) -> int:
    """Liczba wierszy ``integrations`` (świeża baza na test)."""
    async with transaction(sm) as session:
        return int((await session.execute(text("SELECT COUNT(*) FROM integrations"))).scalar_one())


async def audit_row(sm: SM, action: str) -> Any:
    """Jedyny wpis audytu danej akcji (świeża baza na test)."""
    async with transaction(sm) as session:
        rows = await audit_repo.list_by_action(session, action)
    assert len(rows) == 1
    return rows[0]


async def audit_dump(sm: SM) -> str:
    """Cały ``audit_log`` jako JSON — do testów „brak plaintextu sekretu”."""
    async with transaction(sm) as session:
        rows = (await session.execute(text("SELECT * FROM audit_log"))).mappings().all()
    return json.dumps([dict(row) for row in rows], default=str)


async def integration_row(sm: SM, integration_id: int) -> Any:
    """Wiersz ``integrations`` (musi istnieć)."""
    async with transaction(sm) as session:
        row = await integrations_repo.get_integration(session, integration_id)
    assert row is not None
    return row


async def seed_document(sm: SM, dataset_id: str, created_by: str) -> str:
    """Wstawia dokument datasetu (bez plików — storage nie jest potrzebny w tych testach)."""
    document_id = uuid.uuid4().hex
    date = from_ms(TIME_MS)
    row = DocumentRow(
        id=document_id,
        dataset_id=dataset_id,
        created_by=created_by,
        name="umowa.txt",
        suffix="txt",
        type="doc",
        size=10,
        location=f"files/{dataset_id}/{document_id}/original.txt",
        content_hash="0" * 32,
        source_type="local",
        source_ref=None,
        chunk_method="naive",
        parser_config=PARSER_CONFIG,
        run="0",
        progress=0.0,
        progress_msg="",
        error=None,
        process_begin_at=None,
        process_duration=0.0,
        chunk_count=0,
        token_count=0,
        enabled=True,
        meta_fields={},
        thumbnail=None,
        create_time=TIME_MS,
        create_date=date,
        update_time=TIME_MS,
        update_date=date,
    )
    async with transaction(sm) as session:
        await documents_repo.insert(session, row)
    return document_id


async def seed_mapping(sm: SM, integration_id: int, document_id: str | None) -> None:
    """Kontener ``c1`` i mapowanie elementu ``i1`` (dane kasowane razem z integracją)."""
    async with transaction(sm) as session:
        await integrations_repo.upsert_container(
            session, integration_id, CONTAINER_ID, name="Dokumenty", now_ms=TIME_MS
        )
        await integrations_repo.upsert_mapping(
            session,
            MappingRow(
                integration_id=integration_id,
                container_id=CONTAINER_ID,
                item_id=ITEM_ID,
                document_id=document_id,
                content_tag="c1",
                meta_tag="m1",
                name="umowa.txt",
                path="/umowa.txt",
                web_url=None,
                last_status="ok",
                last_error=None,
                updated_at=TIME_MS,
            ),
        )


async def seed_run(sm: SM, integration_id: int) -> int:
    """Przebieg integracji z jednym zdarzeniem; zwraca ``run_id``."""
    async with transaction(sm) as session:
        run_id = await integrations_repo.insert_run(
            session,
            integration_id=integration_id,
            integration_type="sharepoint",
            run_trigger="manual",
            now_ms=TIME_MS,
        )
        await integrations_repo.insert_events(
            session,
            [
                NewEvent(
                    run_id=run_id,
                    integration_id=integration_id,
                    integration_type="sharepoint",
                    level="info",
                    message="start",
                    file_path=None,
                    container_id=CONTAINER_ID,
                    container_name="Dokumenty",
                    created_at=TIME_MS,
                )
            ],
        )
    return run_id


async def set_running(sm: SM, integration_id: int) -> None:
    """Zakłada lock przebiegu (``is_running=1``) — worker w tle."""
    async with transaction(sm) as session:
        assert await integrations_repo.try_lock(
            session, integration_id, owner="worker-1", now_ms=TIME_MS
        )


# --- create ---------------------------------------------------------------------


async def test_create_saves_secret_site_and_audit(
    container: Container, sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)

    view = await service.create(parse_create(create_body(dataset_id)), ACTOR)

    assert view.row.dataset_id == dataset_id
    assert view.row.owner_id == owner_id  # DEC-074: owner = datasets.created_by
    assert view.row.type == "sharepoint"
    assert view.row.name == INTEGRATION_NAME
    assert view.row.secret_enc is not None
    assert view.row.secret_enc.startswith("v1:")
    assert view.row.secret_last4 == SECRET[-4:]
    assert view.sharepoint.tenant_id == TENANT_ID
    assert view.sharepoint.client_id == CLIENT_ID
    assert view.sharepoint.site_url == SITE_URL
    assert view.sharepoint.site_id == SITE_ID
    assert view.sharepoint.site_display_name == SITE_NAME
    assert view.sharepoint.excluded_library_names == DEFAULT_EXCLUDED_LIBRARY_NAMES
    assert sharepoint_fake.resolve_calls == 1
    # Widok i audyt nie niosą plaintextu sekretu (kontrakt §3 p. 5).
    assert SECRET not in repr(view)
    assert SECRET not in await audit_dump(sm)
    entry = await audit_row(sm, "integration_created")
    assert (entry.target_type, entry.target_id) == ("integration", str(view.row.id))
    assert (entry.actor_label, entry.ip) == (ACTOR.label, ACTOR.ip)
    assert entry.details == {
        "name": INTEGRATION_NAME,
        "dataset_id": dataset_id,
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "site_url": SITE_URL,
    }


async def test_create_unknown_dataset_fails_without_row(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    missing = uuid.uuid4().hex

    with pytest.raises(ValidationFailed) as excinfo:
        await service.create(parse_create(create_body(missing)), ACTOR)

    assert str(excinfo.value) == f"Dataset {missing} not found"
    assert await integration_count(sm) == 0


async def test_create_second_integration_for_dataset_conflicts(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    await service.create(parse_create(create_body(dataset_id)), ACTOR)

    with pytest.raises(Conflict) as excinfo:
        await service.create(parse_create(create_body(dataset_id, name="SP 2")), ACTOR)

    assert str(excinfo.value) == f"Dataset {dataset_id} is already linked to another integration"
    assert await integration_count(sm) == 1


async def test_create_resolve_failure_leaves_no_row(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    sharepoint_fake.resolve_error = RuntimeError("boom")

    with pytest.raises(ValidationFailed) as excinfo:
        await service.create(parse_create(create_body(dataset_id)), ACTOR)

    assert str(excinfo.value) == "Cannot save: boom. Run test-connection first."
    assert await integration_count(sm) == 0


async def test_create_duplicate_race_conflicts(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    async with transaction(sm) as session:
        await integrations_repo.insert_integration(
            session,
            type="sharepoint",
            name="Pierwsza",
            dataset_id=dataset_id,
            owner_id=owner_id,
            config={},
            now_ms=TIME_MS,
        )

    async def _none(session: AsyncSession, value: str) -> None:
        return None

    # Wyścig: wiersz powstał po sprawdzeniu ``find_by_dataset``.
    monkeypatch.setattr(integrations_repo, "find_by_dataset", _none)
    with pytest.raises(Conflict) as excinfo:
        await service.create(parse_create(create_body(dataset_id)), ACTOR)

    assert str(excinfo.value) == f"Dataset {dataset_id} is already linked to another integration"
    assert await integration_count(sm) == 1


async def test_create_without_registered_connector(sm: SM, service: IntegrationService) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    assert registry.registered_types() == []

    with pytest.raises(UpstreamError) as excinfo:
        await service.create(parse_create(create_body(dataset_id)), ACTOR)

    assert str(excinfo.value) == "sharepoint connector is not registered"
    assert await integration_count(sm) == 0


# --- list / get -----------------------------------------------------------------


async def test_list_orders_by_id_desc_and_get_returns_view(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, first_dataset = await seed_dataset_and_user(sm)
    _, second_dataset = await seed_dataset_and_user(sm)
    first = await service.create(parse_create(create_body(first_dataset)), ACTOR)
    second = await service.create(parse_create(create_body(second_dataset, name="SP 2")), ACTOR)

    views = await service.list()

    assert [view.row.id for view in views] == [second.row.id, first.row.id]
    assert (await service.get(first.row.id)).sharepoint.site_id == SITE_ID


async def test_get_missing_returns_not_found(service: IntegrationService) -> None:
    with pytest.raises(NotFound) as excinfo:
        await service.get(404)
    assert str(excinfo.value) == "Not found"


# --- update ---------------------------------------------------------------------


async def test_update_without_creds_change_keeps_secret(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)

    view = await service.update(created.row.id, parse_update({"name": NEW_NAME}), ACTOR)

    assert view.row.name == NEW_NAME
    assert view.row.secret_enc == created.row.secret_enc
    assert view.row.secret_last4 == SECRET[-4:]
    assert sharepoint_fake.resolve_calls == 1  # tylko create
    entry = await audit_row(sm, "integration_updated")
    assert entry.details == {"changed": ["name"]}


async def test_update_new_secret_reresolves_and_reencrypts(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)

    view = await service.update(
        created.row.id, parse_update({"client_secret": ROTATED_SECRET}), ACTOR
    )

    assert view.row.secret_enc != created.row.secret_enc
    assert view.row.secret_enc is not None
    assert view.row.secret_enc.startswith("v1:")
    assert view.row.secret_last4 == ROTATED_SECRET[-4:]
    assert sharepoint_fake.resolve_calls == RESOLVE_CALLS_AFTER_UPDATE
    assert ROTATED_SECRET not in await audit_dump(sm)
    assert ROTATED_SECRET not in repr(view)


async def test_update_empty_secret_body_changes_nothing(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)

    view = await service.update(
        created.row.id, parse_update({"client_secret": "", "name": NEW_NAME}), ACTOR
    )

    assert view.row.secret_enc == created.row.secret_enc
    assert view.row.secret_last4 == SECRET[-4:]
    assert sharepoint_fake.resolve_calls == 1


async def test_update_site_url_resolves_and_saves_site(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)
    sharepoint_fake.resolved = {"site_id": "S2", "site_display_name": "Sales"}
    new_url = "https://tenant.sharepoint.test/sites/sales"

    view = await service.update(created.row.id, parse_update({"site_url": new_url}), ACTOR)

    assert sharepoint_fake.resolve_calls == RESOLVE_CALLS_AFTER_UPDATE
    assert view.sharepoint.site_url == new_url
    assert view.sharepoint.site_id == "S2"
    assert view.sharepoint.site_display_name == "Sales"


async def test_update_missing_returns_not_found(service: IntegrationService) -> None:
    with pytest.raises(NotFound) as excinfo:
        await service.update(404, parse_update({"name": NEW_NAME}), ACTOR)
    assert str(excinfo.value) == "Not found"


async def test_update_unknown_dataset_fails(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)
    missing = uuid.uuid4().hex

    with pytest.raises(ValidationFailed) as excinfo:
        await service.update(created.row.id, parse_update({"dataset_id": missing}), ACTOR)

    assert str(excinfo.value) == f"Dataset {missing} not found"
    assert (await integration_row(sm, created.row.id)).dataset_id == dataset_id


async def test_update_dataset_taken_conflicts(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, first_dataset = await seed_dataset_and_user(sm)
    _, second_dataset = await seed_dataset_and_user(sm)
    first = await service.create(parse_create(create_body(first_dataset)), ACTOR)
    await service.create(parse_create(create_body(second_dataset, name="SP 2")), ACTOR)

    with pytest.raises(Conflict) as excinfo:
        await service.update(first.row.id, parse_update({"dataset_id": second_dataset}), ACTOR)

    taken = f"Dataset {second_dataset} is already linked to another integration"
    assert str(excinfo.value) == taken
    assert (await integration_row(sm, first.row.id)).dataset_id == first_dataset


async def test_update_resolve_failure_leaves_row_unchanged(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)
    row_before = created.row
    sharepoint_fake.resolve_error = RuntimeError("boom")

    with pytest.raises(ValidationFailed) as excinfo:
        await service.update(
            created.row.id,
            parse_update({"name": NEW_NAME, "site_url": "https://other.test"}),
            ACTOR,
        )

    assert str(excinfo.value) == "Cannot save: boom. Run test-connection first."
    row_after = await integration_row(sm, created.row.id)
    assert (row_after.name, row_after.dataset_id) == (row_before.name, row_before.dataset_id)
    assert row_after.secret_enc == row_before.secret_enc


# --- delete ---------------------------------------------------------------------


async def test_delete_keeps_documents_and_history(
    sm: SM, service: IntegrationService, sharepoint_fake: SiteFake
) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)
    document_id = await seed_document(sm, dataset_id, owner_id)
    await seed_mapping(sm, created.row.id, document_id)
    run_id = await seed_run(sm, created.row.id)

    await service.delete(created.row.id, ACTOR)

    async with transaction(sm) as session:
        assert await integrations_repo.get_integration(session, created.row.id) is None
        assert await integrations_repo.get_sharepoint(session, created.row.id) is None
        assert await integrations_repo.get_container(session, created.row.id, CONTAINER_ID) is None
        assert await integrations_repo.list_mappings(session, created.row.id, CONTAINER_ID) == []
        assert await integrations_repo.get_run(session, run_id) is not None
        assert len(await integrations_repo.list_events(session, run_id)) == 1
        assert await documents_repo.get(session, document_id) is not None
    entry = await audit_row(sm, "integration_deleted")
    assert entry.details == {
        "name": INTEGRATION_NAME,
        "dataset_id": dataset_id,
        "delete_docs": False,
        "documents_deleted": 0,
    }


async def test_delete_with_flag_removes_mapped_documents(
    container: Container, sm: SM, sharepoint_fake: SiteFake
) -> None:
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    service = IntegrationService(
        container, IntegrationsConfig(delete_docs_on_integration_delete=True)
    )
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)
    document_id = await seed_document(sm, dataset_id, owner_id)
    await seed_mapping(sm, created.row.id, document_id)

    await service.delete(created.row.id, ACTOR)

    async with transaction(sm) as session:
        assert await documents_repo.get(session, document_id) is None
    entry = await audit_row(sm, "integration_deleted")
    assert entry.details == {
        "name": INTEGRATION_NAME,
        "dataset_id": dataset_id,
        "delete_docs": True,
        "documents_deleted": 1,
    }


async def test_delete_running_cancels_first(
    container: Container, sm: SM, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    runs = RecordingRuns()
    service = IntegrationService(container, IntegrationsConfig(), runs=runs)  # type: ignore[arg-type]
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)
    await set_running(sm, created.row.id)

    await service.delete(created.row.id, ACTOR)

    assert runs.cancelled == [created.row.id]
    async with transaction(sm) as session:
        assert await integrations_repo.get_integration(session, created.row.id) is None


async def test_delete_without_running_does_not_cancel(
    container: Container, sm: SM, sharepoint_fake: SiteFake
) -> None:
    _, dataset_id = await seed_dataset_and_user(sm)
    runs = RecordingRuns()
    service = IntegrationService(container, IntegrationsConfig(), runs=runs)  # type: ignore[arg-type]
    created = await service.create(parse_create(create_body(dataset_id)), ACTOR)

    await service.delete(created.row.id, ACTOR)

    assert runs.cancelled == []


async def test_delete_missing_returns_not_found(service: IntegrationService) -> None:
    with pytest.raises(NotFound) as excinfo:
        await service.delete(404, ACTOR)
    assert str(excinfo.value) == "Not found"
