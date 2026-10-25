"""Silnik synchronizacji na stubie ``fake_graph`` po prawdziwym HTTP (WP E4-3d/T4).

Wzorowany na ``test_sharepoint_scenario.py``, ale konektor nie dostaje ``httpx.MockTransport``:
prawdziwy ``SharePointConnector`` rozmawia po sieci z procesem-stubem ``fake_graph``
(``tools/fake-graph/fake_graph/app.py``), uruchomionym w wątku daemon na losowym porcie.
Stub odtwarza kształty Microsoft Graph z kontraktu E4-3d C3 (token, witryna, napędy, delta
z ``@odata.deltaLink``, pobranie treści przez 302 bez ``Authorization``).

Stałe integracji są ze kontraktu C5 (``tenant-e2e``/``client-e2e``/``fake-graph-secret``),
a wybranym napędem jest ``drive-docs`` (``Archiwum`` wykluczone po nazwie).
"""

from __future__ import annotations

import sys
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.repositories import integrations as integrations_repo
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
from app.integrations.sharepoint.auth import clear_token_cache
from app.integrations.sharepoint.config import SharePointConfig
from app.integrations.sharepoint.connector import SharePointConnector
from app.integrations.sharepoint.loader import make_load_config
from tests.fakes.clock import FrozenClock
from tests.integration.integrations.conftest import TIME_MS, seed_dataset_and_user

# Pakiet ``fake_graph`` leży poza backendem (``tools/fake-graph``), a pytest chodzi z
# ``--import-mode=importlib``, więc katalog nadrzędny pakietu dokładamy do ``sys.path``.
FAKE_GRAPH_DIR = Path(__file__).resolve().parents[4] / "tools" / "fake-graph"
if str(FAKE_GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(FAKE_GRAPH_DIR))

pytestmark = pytest.mark.db

CRYPTO_KEY = "ab" * 32
TENANT_ID = "tenant-e2e"
CLIENT_ID = "client-e2e"
SECRET = "fake-graph-secret"  # noqa: S105 — sekret wyłącznie testowy (kontrakt C5)
SITE_URL = "https://contoso.sharepoint.test/sites/e2e"
DRIVE_ID = "drive-docs"
DRIVE_NAME = "Dokumenty"
EXCLUDED_LIBRARY = "Archiwum"
ITEM_TO_NAME = {
    "item-pdf": "sample.pdf",
    "item-docx": "sample.docx",
    "item-txt": "notatka.txt",
}
INITIAL_FILES = len(ITEM_TO_NAME)
NEW_ITEM_NAME = "nowy.txt"
NEW_ITEM_TEXT = "nowy"
MAX_FILE_SIZE_BYTES = 1_048_576
WORKER_ID = "w:1"
LOCALHOST = "127.0.0.1"


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    """Stub w wątku daemon na losowym porcie; ``shutdown`` + ``server_close`` po teście."""
    from fake_graph.app import create_server  # noqa: PLC0415 — ścieżka dodana do sys.path wyżej

    httpd = create_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.fixture
def base_url(server: ThreadingHTTPServer) -> str:
    """Adres stubu; ten sam host trafia do ``Host`` żądań (stąd absolutne URL-e, C3)."""
    return f"http://{LOCALHOST}:{server.server_address[1]}"


@pytest.fixture
async def container(
    migrated_db: Settings, tmp_path: Path, clock: FrozenClock
) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie z kluczem szyfrującym sekrety integracji."""
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
def registered(base_url: str, container: Container) -> Iterator[None]:
    """Prawdziwy konektor SharePoint na HTTP do stubu; po teście czyści rejestr i cache tokenów."""
    clear_token_cache()  # cache tokenów jest modułowy — kolejny test nie może dostać cudzego
    registry.clear()
    registry.register(
        "sharepoint",
        SharePointConnector(
            login_base_url=base_url,
            graph_base_url=f"{base_url}/v1.0",
        ),
        make_load_config(container),
    )
    yield
    registry.clear()


@pytest.fixture
def engine(container: Container) -> SyncEngine:
    """Silnik integracji na kontenerze testowym (domyślna konfiguracja integracji)."""
    return SyncEngine(container, IntegrationsConfig())


async def make_sharepoint_integration(container: Container) -> int:
    """Wiersz ``integrations`` typu ``sharepoint`` + wiersz SP + sekret (kontrakt C5).

    Wykluczona biblioteka ``Archiwum`` zostawia w przebiegu wyłącznie napęd ``drive-docs``.
    """
    sessionmaker = container.sessionmaker
    owner_id, dataset_id = await seed_dataset_and_user(sessionmaker)  # type: ignore[arg-type]
    async with transaction(sessionmaker) as session:  # type: ignore[arg-type]
        integration_id = await integrations_repo.insert_integration(
            session,
            type="sharepoint",
            name="SP fake-graph",
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
            excluded_library_names=[EXCLUDED_LIBRARY],
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


async def mappings_of(container: Container, integration_id: int) -> dict[str, MappingRow]:
    """Mapowania napędu ``drive-docs`` kluczowane ``item_id``."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        rows = await integrations_repo.list_mappings(session, integration_id, DRIVE_ID)
    return {row.item_id: row for row in rows}


async def container_row(container: Container, integration_id: int) -> ContainerRow:
    """Wiersz ``integration_containers`` napędu ``drive-docs`` (kursor delty)."""
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        row = await integrations_repo.get_container(session, integration_id, DRIVE_ID)
    assert row is not None
    return row


async def document_name(container: Container, mapping: MappingRow) -> str:
    """Nazwa dokumentu z mapowania plus kontrola ``source_type``/``source_ref`` (kontrakt C5)."""
    assert mapping.document_id is not None
    async with transaction(container.sessionmaker) as session:  # type: ignore[arg-type]
        document = await documents_repo.get(session, mapping.document_id)
    assert document is not None
    assert document.source_type == "sharepoint"
    assert document.source_ref == f"{mapping.integration_id}:{DRIVE_ID}:{mapping.item_id}"
    return document.name


async def add_file_over_http(base_url: str, name: str, text: str) -> None:
    """``POST /__test/files`` stubu: nowy plik w napędzie ``drive-docs`` (C3)."""
    async with httpx.AsyncClient(base_url=base_url) as client:
        response = await client.post(
            "/__test/files", json={"drive_id": DRIVE_ID, "name": name, "text": text}
        )
    assert response.status_code == httpx.codes.CREATED


async def test_first_run_imports_selected_drive(
    base_url: str, container: Container, registered: None, engine: SyncEngine
) -> None:
    """Pierwszy przebieg: trzy pliki ``drive-docs`` w bazie, mapowania ``ok``, kursor T0."""
    integration_id = await make_sharepoint_integration(container)

    outcome = await run_sync(engine, integration_id)
    assert (outcome.status, outcome.counts.added) == ("success", INITIAL_FILES)
    run_row = await latest_run_row(container, integration_id)
    assert (run_row.status, run_row.added, run_row.run_trigger) == (
        "success",
        INITIAL_FILES,
        "manual",
    )

    mappings = await mappings_of(container, integration_id)
    assert set(mappings) == set(ITEM_TO_NAME)
    names: dict[str, str] = {}
    for item_id, mapping in mappings.items():
        assert mapping.last_status == "ok"
        names[item_id] = await document_name(container, mapping)
    assert names == ITEM_TO_NAME

    stored = await container_row(container, integration_id)
    assert stored.name == DRIVE_NAME
    assert stored.delta_cursor == f"{base_url}/v1.0/drives/{DRIVE_ID}/root/delta?token=T0"


async def test_second_run_adds_only_new_file(
    base_url: str, container: Container, registered: None, engine: SyncEngine
) -> None:
    """Po dodaniu pliku w stubie drugi przebieg (kursor T0) dokłada dokładnie jeden dokument."""
    integration_id = await make_sharepoint_integration(container)
    first = await run_sync(engine, integration_id)
    assert first.counts.added == INITIAL_FILES
    first_mappings = await mappings_of(container, integration_id)
    before = {item_id: mapping.document_id for item_id, mapping in first_mappings.items()}

    await add_file_over_http(base_url, NEW_ITEM_NAME, NEW_ITEM_TEXT)
    outcome = await run_sync(engine, integration_id)
    assert (outcome.status, outcome.counts.added, outcome.counts.updated) == ("success", 1, 0)
    assert (outcome.counts.renamed, outcome.counts.deleted, outcome.counts.failed) == (0, 0, 0)

    mappings = await mappings_of(container, integration_id)
    assert len(mappings) == INITIAL_FILES + 1
    for item_id, mapping in mappings.items():
        assert mapping.last_status == "ok"
        if item_id in before:  # pliki z pierwszego przebiegu nietknięte
            assert mapping.document_id == before[item_id]
            assert mapping.name == ITEM_TO_NAME[item_id]
            continue
        assert mapping.name == NEW_ITEM_NAME
        assert await document_name(container, mapping) == NEW_ITEM_NAME

    stored = await container_row(container, integration_id)
    assert stored.delta_cursor == f"{base_url}/v1.0/drives/{DRIVE_ID}/root/delta?token=T1"


async def test_bad_secret_fails_graph_auth(base_url: str) -> None:
    """Zły sekret: ``test_connection`` zatrzymuje się na kroku ``graph_auth`` (C3)."""
    clear_token_cache()
    connector = SharePointConnector(login_base_url=base_url, graph_base_url=f"{base_url}/v1.0")
    cfg = SharePointConfig(
        integration_id=1,
        tenant_id="tenant-bad",
        client_id="client-bad",
        client_secret=SecretStr("zly-sekret"),
        site_url=SITE_URL,
        site_id=None,
        excluded_library_names=[],
        max_file_size_bytes=MAX_FILE_SIZE_BYTES,
    )

    report = await connector.test_connection(cfg, dataset_exists=True)

    assert report.ok is False
    assert report.resolved == {}
    assert len(report.checks) == 1
    check = report.checks[0]
    assert (check["name"], check["status"]) == ("graph_auth", "failed")
    assert "AADSTS7000215" in str(check["detail"])
