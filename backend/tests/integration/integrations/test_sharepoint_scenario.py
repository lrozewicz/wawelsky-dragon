"""Scenariusz przekrojowy SharePoint: integracja w bazie → ``SyncEngine.run`` (WP E4-2b/T4).

Wiersz ``integrations`` + ``integration_sharepoint`` + sekret → rejestr z prawdziwym
``SharePointConnector`` na ``httpx.MockTransport`` → kolejne przebiegi ``SyncEngine``: pierwsze
pobranie, rename bez re-parsowania, zmiana treści (ten sam ``document_id``), usunięcie
z propagacją i reset delty po 410. Asercje patrzą na artefakty w bazie (``documents``,
``integration_item_mappings``, ``integration_containers``, ``tasks``, ``datasets.document_count``,
``integration_sync_runs``), nie tylko na kod wyjścia.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.documents import DocumentRow
from app.db.repositories.integrations import (
    ContainerRow,
    MappingRow,
    RunRow,
    set_secret,
    upsert_sharepoint,
)
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import RunOutcome, SyncEngine
from app.integrations.secrets import encrypt_secret
from app.integrations.sharepoint.connector import SharePointConnector
from app.integrations.sharepoint.loader import make_load_config
from tests.fakes.clock import FrozenClock
from tests.integration.integrations.conftest import TIME_MS, seed_dataset_and_user
from tests.integration.integrations.sharepoint_mock import (
    CONTENT_B_NEXT,
    DRIVE_ID,
    DRIVE_NAME,
    ITEM_A,
    ITEM_B,
    SITE_HOST,
    SITE_URL,
    GraphSim,
    delta_link,
)

pytestmark = pytest.mark.db

CRYPTO_KEY = "ab" * 32
SECRET = "sp-secret"  # noqa: S105 — sekret wyłącznie testowy
TENANT_ID = "contoso.onmicrosoft.com"
CLIENT_ID = "client-1"
MAX_FILE_SIZE_BYTES = 1_048_576
WORKER_ID = "w:1"
CTAG_A1 = "ca1"
CTAG_B2 = "cb2"
ETAG_A2 = "ea2"
ETAG_B2 = "eb2"
FIRST_TWO = 2
AFTER_UPDATE = 3


@pytest.fixture
async def container(
    migrated_db: Settings, tmp_path: Path, clock: FrozenClock
) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie z kluczem szyfrującym sekrety integracji (wymaganie 3)."""
    instance = Container(
        migrated_db.model_copy(
            update={"storage_root": str(tmp_path), "crypto_key": SecretStr(CRYPTO_KEY)}
        ),
        clock=clock,
    )
    await instance.start()
    yield instance
    await instance.aclose()


@pytest.fixture
def sim() -> GraphSim:
    """Świeży symulator Graph (stan źródła zmieniany między przebiegami)."""
    return GraphSim()


@pytest.fixture
def registered(sim: GraphSim, container: Container) -> Iterator[GraphSim]:
    """Rejestruje prawdziwy konektor SharePoint na symulatorze; po teście czyści rejestr."""
    registry.clear()
    registry.register(
        "sharepoint", SharePointConnector(http_factory=sim), make_load_config(container)
    )
    yield sim
    registry.clear()


@pytest.fixture
def engine(container: Container) -> SyncEngine:
    """Silnik integracji na kontenerze testowym (domyślna konfiguracja integracji)."""
    return SyncEngine(container, IntegrationsConfig())


async def make_sharepoint_integration(container: Container) -> int:
    """Wiersz ``integrations`` typu ``sharepoint`` + wiersz SP + sekret (wymaganie 3)."""
    sessionmaker = container.sessionmaker
    owner_id, dataset_id = await seed_dataset_and_user(sessionmaker)  # type: ignore[arg-type]
    async with transaction(sessionmaker) as session:  # type: ignore[arg-type]
        integration_id = await integrations_repo.insert_integration(
            session,
            type="sharepoint",
            name="SP scenariusz",
            dataset_id=dataset_id,
            owner_id=owner_id,
            config={},
            now_ms=TIME_MS,
            max_file_size_bytes=MAX_FILE_SIZE_BYTES,
        )
        await upsert_sharepoint(
            session,
            integration_id=integration_id,
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            site_url=SITE_URL,
            site_id=None,
            site_display_name=None,
            excluded_library_names=[],
        )
        enc, last4 = encrypt_secret(CRYPTO_KEY, integration_id, SECRET)
        await set_secret(
            session, integration_id, secret_enc=enc, secret_last4=last4, now_ms=TIME_MS
        )
    return integration_id


async def run_sync(engine: SyncEngine, integration_id: int) -> RunOutcome:
    """Jeden przebieg ``SyncEngine`` (``manual``, z pominięciem kolejki)."""
    outcome = await engine.run(integration_id, trigger="manual", worker_id=WORKER_ID)
    assert outcome is not None
    return outcome


async def latest_run_row(container: Container, integration_id: int) -> RunRow:
    """Najświeższy wiersz ``integration_sync_runs`` integracji (statusy przebiegu)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await integrations_repo.latest_run(session, integration_id)
    assert row is not None
    return row


async def mapping_of(container: Container, integration_id: int, item_id: str) -> MappingRow | None:
    """Mapowanie elementu w kontenerze ``d1`` (brak → ``None``)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        rows = await integrations_repo.list_mappings(session, integration_id, DRIVE_ID)
    return next((row for row in rows if row.item_id == item_id), None)


async def document_by_id(container: Container, document_id: str) -> DocumentRow | None:
    """Dokument z bazy po ``id``."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await documents_repo.get(session, document_id)


async def document_of_item(
    container: Container, integration_id: int, item_id: str
) -> DocumentRow | None:
    """Dokument elementu: mapping kontenera ``d1`` → wiersz ``documents`` (brak → ``None``)."""
    mapping = await mapping_of(container, integration_id, item_id)
    if mapping is None or mapping.document_id is None:
        return None
    return await document_by_id(container, mapping.document_id)


async def container_row(container: Container, integration_id: int) -> ContainerRow | None:
    """Wiersz ``integration_containers`` biblioteki ``d1`` (kursor delty)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return await integrations_repo.get_container(session, integration_id, DRIVE_ID)


async def dataset_document_count(container: Container, integration_id: int) -> int:
    """``datasets.document_count`` datasetu integracji."""
    sql = text(
        "SELECT document_count FROM datasets"
        " WHERE id = (SELECT dataset_id FROM integrations WHERE id = :id)"
    )
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return int((await session.execute(sql, {"id": integration_id})).scalar_one())


async def parse_task_count(container: Container) -> int:
    """Liczba zadań ``parse_document`` w bazie."""
    sql = text("SELECT COUNT(*) FROM tasks WHERE task_type = 'parse_document'")
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        return int((await session.execute(sql)).scalar_one())


async def complete_parse_tasks(container: Container) -> None:
    """Zamyka zadania parsowania, jak zrobiłby to worker.

    Scenariusz prowadzi sam ``SyncEngine``, więc bez tego ``replace`` w wierszu 9 trafiłby na
    ``_reject_active`` (dokument z zadaniem ``queued``).
    """
    sql = text(
        "UPDATE tasks SET status = 'done' WHERE task_type = 'parse_document' AND status = 'queued'"
    )
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        await session.execute(sql)


def doc_ref(integration_id: int, item_id: str) -> str:
    """``source_ref`` dokumentu elementu (kontrakt C5)."""
    return f"{integration_id}:{DRIVE_ID}:{item_id}"


def wd_source(integration_id: int, item_id: str, name: str) -> dict[str, object]:
    """``meta_fields.wd_source`` elementu SharePoint (kontrakt C5)."""
    return {
        "integration_id": integration_id,
        "type": "sharepoint",
        "container_id": DRIVE_ID,
        "item_id": item_id,
        "path": f"/{DRIVE_NAME}/{name}",
        "web_url": f"https://{SITE_HOST}/sites/eng/{DRIVE_NAME}/{name}",
    }


async def test_sharepoint_scenario(  # noqa: PLR0915 — jeden scenariusz przekrojowy
    container: Container,
    sim: GraphSim,
    registered: GraphSim,
    engine: SyncEngine,
) -> None:
    """Pięć przebiegów: dodanie, rename, zmiana treści, usunięcie i reset po 410."""
    integration_id = await make_sharepoint_integration(container)

    # 1) pierwsze pobranie: dwa pliki, mapowania ok, kursor zapisany, dwa zadania parsowania
    outcome = await run_sync(engine, integration_id)
    assert (outcome.status, outcome.counts.added) == ("success", FIRST_TWO)
    run_row = await latest_run_row(container, integration_id)
    assert (run_row.status, run_row.added, run_row.run_trigger) == ("success", FIRST_TWO, "manual")
    document_ids: dict[str, str] = {}
    for item_id, name in ((ITEM_A, "a.txt"), (ITEM_B, "b.txt")):
        mapping = await mapping_of(container, integration_id, item_id)
        assert mapping is not None
        assert mapping.last_status == "ok"
        assert mapping.document_id is not None
        document_ids[item_id] = mapping.document_id
        document = await document_by_id(container, mapping.document_id)
        assert document is not None
        assert document.source_type == "sharepoint"
        assert document.source_ref == doc_ref(integration_id, item_id)
        assert document.name == name
        assert document.meta_fields["wd_source"] == wd_source(integration_id, item_id, name)
    stored = await container_row(container, integration_id)
    assert stored is not None
    assert (stored.name, stored.delta_cursor) == (DRIVE_NAME, delta_link("T1"))
    assert await parse_task_count(container) == FIRST_TWO
    assert await dataset_document_count(container, integration_id) == FIRST_TWO

    # 2) rename u źródła: nowa nazwa, ten sam dokument, bez nowego zadania parsowania
    sim.rename(ITEM_A, "a2.txt", e_tag=ETAG_A2)
    sim.page("T1", [sim.raw(ITEM_A)])
    outcome = await run_sync(engine, integration_id)
    assert (outcome.status, outcome.counts.renamed) == ("success", 1)
    assert (await latest_run_row(container, integration_id)).renamed == 1
    document = await document_of_item(container, integration_id, ITEM_A)
    assert document is not None
    assert (document.id, document.name) == (document_ids[ITEM_A], "a2.txt")
    assert document.meta_fields["wd_source"] == wd_source(integration_id, ITEM_A, "a2.txt")
    mapping = await mapping_of(container, integration_id, ITEM_A)
    assert mapping is not None
    assert (mapping.name, mapping.path, mapping.content_tag) == (
        "a2.txt",
        f"/{DRIVE_NAME}/a2.txt",
        CTAG_A1,
    )
    assert await parse_task_count(container) == FIRST_TWO
    stored = await container_row(container, integration_id)
    assert stored is not None
    assert stored.delta_cursor == delta_link("T2")

    # 3) zmiana treści: ten sam ``document_id``, licznik ``updated`` i jedno nowe parsowanie
    await complete_parse_tasks(container)
    sim.touch(ITEM_B, c_tag=CTAG_B2, e_tag=ETAG_B2, content=CONTENT_B_NEXT)
    sim.page("T2", [sim.raw(ITEM_B)])
    outcome = await run_sync(engine, integration_id)
    assert (outcome.status, outcome.counts.updated) == ("success", 1)
    mapping = await mapping_of(container, integration_id, ITEM_B)
    assert mapping is not None
    assert (mapping.document_id, mapping.content_tag) == (document_ids[ITEM_B], CTAG_B2)
    document = await document_of_item(container, integration_id, ITEM_B)
    assert document is not None
    assert document.meta_fields["wd_source"] == wd_source(integration_id, ITEM_B, "b.txt")
    assert await parse_task_count(container) == AFTER_UPDATE

    # 4) usunięcie u źródła: dokument i mapowanie znikają, licznik datasetu spada
    sim.page("T3", [sim.deleted_raw(ITEM_A)])
    sim.remove(ITEM_A)
    outcome = await run_sync(engine, integration_id)
    assert (outcome.status, outcome.counts.deleted) == ("success", 1)
    assert (await latest_run_row(container, integration_id)).deleted == 1
    assert await document_by_id(container, document_ids[ITEM_A]) is None
    assert await mapping_of(container, integration_id, ITEM_A) is None
    remaining = await mapping_of(container, integration_id, ITEM_B)
    assert remaining is not None
    assert remaining.document_id == document_ids[ITEM_B]
    assert await dataset_document_count(container, integration_id) == 1

    # 5) 410 na kursora: reset (pełne przejście bez kursora) i stan zgodny ze źródłem
    sim.gone_token("T4")
    outcome = await run_sync(engine, integration_id)
    assert outcome.status == "success"
    assert (outcome.counts.added, outcome.counts.updated, outcome.counts.failed) == (0, 0, 0)
    assert (await latest_run_row(container, integration_id)).status == "success"
    assert sim.delta_calls == [None, "T1", "T2", "T3", "T4", None]
    stored = await container_row(container, integration_id)
    assert stored is not None
    assert stored.delta_cursor == delta_link("T5")
    assert await dataset_document_count(container, integration_id) == 1
    assert await document_by_id(container, document_ids[ITEM_B]) is not None
