"""Testy połączenia WD: ``POST /integrations/test`` i ``POST /integrations/{id}/test`` (brief T3).

Pierwsza trasa to test bez zapisu (ciało jak SVC ``test-connection`` plus ``type``), druga
testuje **zapisany** sekret (odszyfrowany z wiersza) z opcjonalnymi nadpisaniami pól — bez
zapisu do bazy i bez wpisu audytu (kontrakt E4-3b §3/§4, 09 §10).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.uow import transaction
from app.integrations import registry
from app.integrations.base import ConnectionReport
from app.integrations.base import Container as RemoteContainer
from app.integrations.sharepoint.config import SharePointConfig
from tests.contract.wd.integrations.conftest import (
    CLIENT_ID,
    CLIENT_SECRET,
    SITE_ID,
    SITE_NAME,
    SITE_URL,
    TENANT_ID,
    SharePointFake,
)
from tests.fakes.integrations import fake_load_config

pytestmark = pytest.mark.contract

OK = 200
BAD_REQUEST = 400
NOT_FOUND = 404

TEST_PATH = "/api/wd/v1/integrations/test"
SAVED_PATH = "/api/wd/v1/integrations/{id}/test"

CLIENT_SECRET_MASK = "••••abcd"  # noqa: S105 — maska, nie sekret
ROTATED_SECRET = "inny-sekret-4321"  # noqa: S105 — sekret wyłącznie testowy
ROTATED_MASK = "••••4321"

DATASET_EXISTS = "ok"

OK_CHECKS = [
    {"name": "graph_auth", "status": "ok", "detail": ""},
    {"name": "site_resolution", "status": "ok", "detail": ""},
]
OK_RESOLVED: dict[str, object] = {
    "site_id": SITE_ID,
    "site_display_name": SITE_NAME,
    "libraries_total": 4,
    "libraries_included": 2,
}
DRIVE_NAMES = ["Dokumenty", "Wspólne"]

SUCCESS_KEYS = frozenset(
    {
        "graph_auth",
        "site_resolution",
        "site_id",
        "site_display_name",
        "drives_visible",
        "drives_after_exclusion",
        "drive_names",
        "dataset_exists",
        "dataset_name",
    }
)


def connection_body(**over: object) -> dict[str, object]:
    """Poprawne ciało ``POST /integrations/test`` (kontrakt §2)."""
    body: dict[str, object] = {
        "type": "sharepoint",
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "site_url": SITE_URL,
    }
    body.update(over)
    return body


def wd_error(response: httpx.Response) -> dict[str, Any]:
    """Koperta błędu WD z odpowiedzi (kontrakt §0 p. 6)."""
    body: dict[str, Any] = response.json()
    return body["error"]


def ok_report() -> ConnectionReport:
    """Raport udanej autoryzacji i rozwiązania witryny (09 §10)."""
    return ConnectionReport(ok=True, checks=list(OK_CHECKS), resolved=dict(OK_RESOLVED))


def use_ok_connector(connector: SharePointFake) -> SharePointFake:
    """Zaślepka z udanym raportem i dwiema bibliotekami (kształt DTO jak w SVC)."""
    connector.report = ok_report()
    connector.containers = [
        RemoteContainer(id="d1", name=DRIVE_NAMES[0]),
        RemoteContainer(id="d2", name=DRIVE_NAMES[1]),
    ]
    return connector


class RecordingConnector(SharePointFake):
    """Zaślepka zapisująca konfiguracje przekazane do ``test_connection`` (kontrakt §3)."""

    def __init__(self) -> None:
        super().__init__()
        self.report = ok_report()
        self.configs: list[SharePointConfig] = []

    async def test_connection(self, cfg: object, *, dataset_exists: bool) -> ConnectionReport:
        """Zapisuje ``cfg`` (z sekretem) i deleguje raport do ``SharePointFake``."""
        self.configs.append(cast(SharePointConfig, cfg))
        return await super().test_connection(cfg, dataset_exists=dataset_exists)

    @property
    def client_secrets(self) -> list[str]:
        """Sekrety widziane przez konektor; słownik ``repr`` ich nie wycieka (SecretStr)."""
        return [cfg.client_secret.get_secret_value() for cfg in self.configs]


@pytest.fixture
def recording(app: FastAPI) -> Iterator[RecordingConnector]:
    """Podmienia rejestr ``sharepoint`` na zaślepkę nagrywającą (po ``create_app``)."""
    fake = RecordingConnector()
    registry.register("sharepoint", fake, fake_load_config)
    yield fake
    registry.clear()


async def test_connection_all_stages_ok(
    admin: httpx.AsyncClient, connector: SharePointFake, seed_dataset: Any
) -> None:
    """Wszystkie etapy ``ok`` → 200 z pełnym DTO, bez kluczy o wartości null (kontrakt §4)."""
    dataset_id = await seed_dataset()
    use_ok_connector(connector)

    response = await admin.post(TEST_PATH, json=connection_body(dataset_id=dataset_id))

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert set(data) == SUCCESS_KEYS
    assert data["graph_auth"] == "ok"
    assert data["site_resolution"] == "ok"
    assert data["site_id"] == SITE_ID
    assert data["site_display_name"] == SITE_NAME
    assert data["drives_visible"] == OK_RESOLVED["libraries_total"]
    assert data["drives_after_exclusion"] == OK_RESOLVED["libraries_included"]
    assert data["drive_names"] == DRIVE_NAMES
    assert data["dataset_exists"] == DATASET_EXISTS
    assert all(value is not None for value in data.values())
    assert CLIENT_SECRET not in response.text


async def test_connection_without_dataset_skips_local_check(
    admin: httpx.AsyncClient, connector: SharePointFake
) -> None:
    """Brak ``dataset_id`` → ``dataset_exists: "skipped"`` i brak klucza ``dataset_name``."""
    use_ok_connector(connector)

    response = await admin.post(TEST_PATH, json=connection_body())

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert data["dataset_exists"] == "skipped"
    assert "dataset_name" not in data


async def test_connection_graph_auth_failure_returns_early(
    admin: httpx.AsyncClient, connector: SharePointFake, seed_dataset: Any
) -> None:
    """Porażka ``graph_auth`` → wczesny powrót, dalsze etapy ``skipped`` (09 §10)."""
    dataset_id = await seed_dataset()
    connector.report = ConnectionReport(
        ok=False,
        checks=[{"name": "graph_auth", "status": "failed", "detail": "AADSTS7000215"}],
        resolved={},
    )

    response = await admin.post(TEST_PATH, json=connection_body(dataset_id=dataset_id))

    assert response.status_code == OK, response.text
    assert response.json()["data"] == {
        "graph_auth": "failed",
        "graph_auth_error": "AADSTS7000215",
        "site_resolution": "skipped",
        "dataset_exists": "skipped",
    }


async def test_connection_does_not_persist_integration(
    admin: httpx.AsyncClient, connector: SharePointFake
) -> None:
    """``POST /integrations/test`` nic nie zapisuje — lista integracji nadal pusta."""
    use_ok_connector(connector)

    response = await admin.post(TEST_PATH, json=connection_body())

    assert response.status_code == OK, response.text
    listed = await admin.get("/api/wd/v1/integrations")
    assert listed.json()["data"]["total"] == 0


@pytest.mark.parametrize(
    "over",
    [
        {"type": "other"},
        {"tenant_id": ""},
        {"client_id": None},
        {"site_url": 5},
        {"excluded_library_names": "Site Assets"},
    ],
)
async def test_connection_validation_is_400(
    admin: httpx.AsyncClient, connector: SharePointFake, over: dict[str, object]
) -> None:
    """Złe creds/``type`` → 400 ``validation_failed`` (nigdy 422, kontrakt §0 p. 6)."""
    response = await admin.post(TEST_PATH, json=connection_body(**over))

    assert response.status_code == BAD_REQUEST, response.text
    error = wd_error(response)
    assert error["code"] == "validation_failed"
    assert error["details"]["errors"]


async def test_connection_without_type_is_400_and_keeps_secret_out(
    admin: httpx.AsyncClient, connector: SharePointFake
) -> None:
    """Brak ``type`` → 400, a ``input`` błędu ``missing`` nie wynosi ciała z sekretem (§7)."""
    body = connection_body()
    body.pop("type")

    response = await admin.post(TEST_PATH, json=body)

    assert response.status_code == BAD_REQUEST, response.text
    error = wd_error(response)
    assert error["code"] == "validation_failed"
    assert error["details"]["errors"][0]["type"] == "missing"
    assert "input" not in error["details"]["errors"][0]
    assert CLIENT_SECRET not in response.text


async def test_connection_error_response_never_leaks_secret(
    admin: httpx.AsyncClient, connector: SharePointFake
) -> None:
    """Poprawny sekret + błędne inne pole → 400, ale sekret nie występuje w treści (K3 §4)."""
    response = await admin.post(TEST_PATH, json=connection_body(excluded_library_names="x"))

    assert response.status_code == BAD_REQUEST, response.text
    assert CLIENT_SECRET not in response.text


async def test_saved_error_response_never_leaks_body_secret(
    admin: httpx.AsyncClient,
    recording: RecordingConnector,
    create_integration: Any,
    seed_dataset: Any,
) -> None:
    """Poprawny sekret w nadpisaniu + błędne inne pole → 400 bez sekretu w treści (errata §7)."""
    created = await create_integration(await seed_dataset())

    response = await admin.post(
        SAVED_PATH.format(id=created["id"]),
        json={"client_secret": CLIENT_SECRET, "site_url": 5},
    )

    assert response.status_code == BAD_REQUEST, response.text
    assert wd_error(response)["code"] == "validation_failed"
    assert CLIENT_SECRET not in response.text


async def test_saved_uses_stored_decrypted_secret(
    admin: httpx.AsyncClient,
    recording: RecordingConnector,
    create_integration: Any,
    seed_dataset: Any,
) -> None:
    """``POST /{id}/test`` bez ciała → 200; konektor dostał odszyfrowany zapisany sekret."""
    created = await create_integration(await seed_dataset())

    response = await admin.post(SAVED_PATH.format(id=created["id"]))

    assert response.status_code == OK, response.text
    assert set(response.json()["data"]) == SUCCESS_KEYS
    assert recording.client_secrets == [CLIENT_SECRET]
    assert CLIENT_SECRET not in response.text


async def test_saved_accepts_empty_body_object(
    admin: httpx.AsyncClient,
    recording: RecordingConnector,
    create_integration: Any,
    seed_dataset: Any,
) -> None:
    """Ciało ``{}`` znaczy „bez nadpisań” — test działa na zapisanych wartościach (§4)."""
    created = await create_integration(await seed_dataset())

    response = await admin.post(SAVED_PATH.format(id=created["id"]), json={})

    assert response.status_code == OK, response.text
    assert recording.client_secrets == [CLIENT_SECRET]


async def test_saved_override_secret_does_not_change_stored(
    admin: httpx.AsyncClient,
    recording: RecordingConnector,
    create_integration: Any,
    seed_dataset: Any,
) -> None:
    """Nadpisanie sekretu idzie do konektora, ale zapisana maska zostaje bez zmian (§4)."""
    created = await create_integration(await seed_dataset())

    response = await admin.post(
        SAVED_PATH.format(id=created["id"]), json={"client_secret": ROTATED_SECRET}
    )

    assert response.status_code == OK, response.text
    assert recording.client_secrets == [ROTATED_SECRET]
    assert ROTATED_SECRET not in response.text

    after = await admin.get(f"/api/wd/v1/integrations/{created['id']}")
    assert after.json()["data"]["client_secret_masked"] == CLIENT_SECRET_MASK
    assert after.json()["data"]["client_secret_masked"] != ROTATED_MASK


async def test_saved_does_not_persist_overrides_or_audit(
    admin: httpx.AsyncClient,
    recording: RecordingConnector,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Nadpisania pól nie trafiają do bazy i nie tworzą wpisu audytu (kontrakt §3)."""
    created = await create_integration(await seed_dataset())
    overrides = {"tenant_id": "inny-tenant", "site_url": "https://other/site", "name": "inna"}

    response = await admin.post(SAVED_PATH.format(id=created["id"]), json=overrides)

    assert response.status_code == OK, response.text
    after = await admin.get(f"/api/wd/v1/integrations/{created['id']}")
    stored = after.json()["data"]
    assert stored["tenant_id"] == TENANT_ID
    assert stored["site_url"] == SITE_URL
    assert stored["name"] == created["name"]
    assert stored["updated_at"] == created["updated_at"]
    assert recording.configs[0].tenant_id == "inny-tenant"
    assert recording.configs[0].site_url == "https://other/site"

    async with transaction(sm) as session:
        actions = (
            (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log"
                        " WHERE target_type = 'integration' AND target_id = :id"
                    ),
                    {"id": str(created["id"])},
                )
            )
            .scalars()
            .all()
        )
    assert list(actions) == ["integration_created"]


async def test_saved_missing_integration_is_404(
    admin: httpx.AsyncClient, recording: RecordingConnector
) -> None:
    """``POST /999/test`` → 404 ``not_found`` zanim konektor zostanie zawołany (kontrakt §4)."""
    response = await admin.post(SAVED_PATH.format(id=999))

    assert response.status_code == NOT_FOUND, response.text
    assert wd_error(response)["code"] == "not_found"
    assert recording.configs == []


async def test_saved_error_response_never_leaks_secret(
    admin: httpx.AsyncClient,
    recording: RecordingConnector,
    create_integration: Any,
    seed_dataset: Any,
) -> None:
    """Poprawny sekret w nadpisaniu + błędne inne pole → 400 bez sekretu w treści (§0 p. 6)."""
    created = await create_integration(await seed_dataset())

    response = await admin.post(
        SAVED_PATH.format(id=created["id"]),
        json={"client_secret": ROTATED_SECRET, "site_url": 5},
    )

    assert response.status_code == BAD_REQUEST, response.text
    assert ROTATED_SECRET not in response.text
    assert wd_error(response)["code"] == "validation_failed"
