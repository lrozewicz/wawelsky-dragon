"""CRUD integracji SVC `/api/integrations*` — AG-25 (kontrakt E4-3a §4, 03 §5).

Asercje na **dokładnych zbiorach kluczy** DTO `Integration` (19 kluczy) i na braku
plaintextu sekretu w odpowiedziach, w bazie i w `audit_log.details_json`.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import MappingRow
from app.db.uow import transaction
from app.integrations.base import SyncCounts
from tests.contract.hub_compat.sharepoint.conftest import (
    CLIENT_SECRET,
    CLIENT_SECRET_MASK,
    CONTAINER_D1,
    CONTAINER_D1_NAME,
    SITE_ID,
    SITE_URL,
    integration_body,
)

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

OK = 200
CREATED = 201
BAD_REQUEST = 400
NOT_FOUND = 404
CONFLICT = 409
NOW_MS = 1_790_157_600_000
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

INTEGRATION_KEYS = frozenset(
    {
        "id",
        "name",
        "dataset_id",
        "tenant_id",
        "client_id",
        "client_secret_masked",
        "site_url",
        "site_id",
        "excluded_library_names",
        "max_file_size_bytes",
        "ignored_extensions",
        "scan_interval_seconds",
        "delete_propagation",
        "is_active",
        "is_running",
        "last_sync_at",
        "last_sync_status",
        "created_at",
        "updated_at",
    }
)

DEFAULT_EXCLUDED = [
    "Site Assets",
    "Style Library",
    "Form Templates",
    "Site Pages",
    "Preservation Hold Library",
    "Customized Reports",
]
DEFAULT_IGNORED = [
    "exe",
    "dll",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "mp4",
    "mov",
    "avi",
    "iso",
    "dmg",
]

_VALIDATION_CASES = [
    ({"scan_interval_seconds": "60"}, "scan_interval_seconds must be a number"),
    ({"scan_interval_seconds": 10}, "scan_interval_seconds must be >= 30"),
    ({"max_file_size_bytes": 0}, "max_file_size_bytes must be >= 1"),
    ({"is_active": 1}, "is_active must be a boolean"),
    ({"name": "   "}, "name is required and must be a non-empty string"),
    (
        {"excluded_library_names": "Site Assets"},
        "excluded_library_names must be an array of strings",
    ),
]

DEFAULT_MAX_FILE_SIZE_BYTES = 209_715_200
DEFAULT_SCAN_INTERVAL_SECONDS = 300
UPDATED_SCAN_INTERVAL_SECONDS = 60
ROTATED_SECRET = "nowy-sekret-1234"  # noqa: S105 — sekret wyłącznie testowy


async def insert_finished_run(
    sm: async_sessionmaker[AsyncSession], integration_id: int, *, now_ms: int = NOW_MS
) -> int:
    """Wstawia zakończony przebieg integracji; zwraca `run_id` (kontrakt E4-1 C2)."""
    async with transaction(sm) as session:
        run_id = await integrations_repo.insert_run(
            session,
            integration_id=integration_id,
            integration_type="sharepoint",
            run_trigger="manual",
            now_ms=now_ms,
        )
        await integrations_repo.finish_run(
            session,
            run_id,
            status="success",
            counts=SyncCounts(added=1, updated=2, deleted=3, failed=0),
            now_ms=now_ms + 1,
        )
    return run_id


async def audit_details(sm: async_sessionmaker[AsyncSession], action: str) -> list[str]:
    """`details` wpisów audytu danej akcji jako tekst (K7 część 2 §7 p. 13).

    Kontrakt §3 nazywa to pole `details_json` (tak nazywa się parametr repozytorium);
    kolumna w tabeli `audit_log` to `details` (migracja 0002).
    """
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text("SELECT details FROM audit_log WHERE action = :action"),
                    {"action": action},
                )
            )
            .scalars()
            .all()
        )
    return [str(value) for value in rows if value is not None]


async def test_ag25_create_returns_exact_integration_dto(
    svc: Any, prefix: str, connector: Any, seed_dataset: Any
) -> None:
    """AG-25: 201 + dokładne klucze DTO, maska sekretu, `site_id` z `resolve`, ISO czasy."""
    _owner, dataset_id = await seed_dataset()
    response = await svc.post(f"{prefix}/api/integrations", json=integration_body(dataset_id))

    assert response.status_code == CREATED, response.text
    body = response.json()
    assert set(body) == {"data"}
    created = body["data"]
    assert set(created) == INTEGRATION_KEYS
    assert isinstance(created["id"], int)
    assert not isinstance(created["id"], bool)
    assert created["dataset_id"] == dataset_id
    assert re.fullmatch(r"[0-9a-f]{32}", created["dataset_id"]) is not None
    assert created["client_secret_masked"] == CLIENT_SECRET_MASK
    assert created["client_id"] == "c-client"
    assert created["tenant_id"] == "t-tenant"
    assert created["site_url"] == SITE_URL
    assert created["site_id"] == SITE_ID
    assert created["excluded_library_names"] == DEFAULT_EXCLUDED
    assert created["ignored_extensions"] == DEFAULT_IGNORED
    assert created["max_file_size_bytes"] == DEFAULT_MAX_FILE_SIZE_BYTES
    assert created["scan_interval_seconds"] == DEFAULT_SCAN_INTERVAL_SECONDS
    assert created["delete_propagation"] is True
    assert created["is_active"] is True
    assert created["is_running"] is False
    assert created["last_sync_at"] is None
    assert created["last_sync_status"] is None
    assert ISO_RE.fullmatch(str(created["created_at"])) is not None
    assert ISO_RE.fullmatch(str(created["updated_at"])) is not None
    assert CLIENT_SECRET not in response.text
    assert "client_secret" not in created


@pytest.mark.parametrize(("over", "message"), _VALIDATION_CASES)
async def test_ag25_create_validation_is_400_never_422(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any, prefix: str, connector: Any, seed_dataset: Any, over: dict[str, object], message: str
) -> None:
    """AG-25/AG-18: złe typy pól → 400 `{error}` z komunikatem pola (nigdy 422)."""
    _owner, dataset_id = await seed_dataset()
    body = integration_body(dataset_id, **over)
    response = await svc.post(f"{prefix}/api/integrations", json=body)

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json() == {"error": message}


async def test_ag25_create_rejects_non_object_body(svc: Any, prefix: str, connector: Any) -> None:
    """Errata TL po T4: ciało nie-obiekt → puste pola → 400 o `name` (nie „Invalid JSON”)."""
    response = await svc.post(f"{prefix}/api/integrations", json=["nie", "obiekt"])

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json() == {"error": "name is required and must be a non-empty string"}


async def test_ag25_create_requires_resolvable_site(
    svc: Any, prefix: str, connector: Any, seed_dataset: Any
) -> None:
    """AG-25: `resolve` konektora rzuca → 400 „Cannot save: … Run test-connection first.”"""
    _owner, dataset_id = await seed_dataset()
    connector.fail_resolve = True

    response = await svc.post(f"{prefix}/api/integrations", json=integration_body(dataset_id))

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json() == {"error": "Cannot save: Site not found. Run test-connection first."}


async def test_ag25_create_rejects_taken_dataset(
    svc: Any, prefix: str, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """AG-25: drugi POST na ten sam `dataset_id` → 409 (`uq_integrations_dataset`)."""
    _owner, dataset_id = await seed_dataset()
    await create_integration(dataset_id)

    response = await svc.post(f"{prefix}/api/integrations", json=integration_body(dataset_id))

    assert response.status_code == CONFLICT, response.text
    assert response.json() == {
        "error": f"Dataset {dataset_id} is already linked to another integration"
    }


async def test_ag25_create_rejects_unknown_dataset(svc: Any, prefix: str, connector: Any) -> None:
    """AG-25: nieistniejący dataset → 400 „Dataset {id} not found”."""
    unknown = uuid.uuid4().hex

    response = await svc.post(f"{prefix}/api/integrations", json=integration_body(unknown))

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json() == {"error": f"Dataset {unknown} not found"}


async def test_ag25_create_stores_no_plaintext_secret(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-25/K7 §7 p. 6: sekret tylko zaszyfrowany (+ `secret_last4`), bez plaintextu w audycie."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)

    async with transaction(sm) as session:
        row = (
            (
                await session.execute(
                    text("SELECT secret_enc, secret_last4 FROM integrations WHERE id = :id"),
                    {"id": created["id"]},
                )
            )
            .mappings()
            .one()
        )
    assert row["secret_last4"] == CLIENT_SECRET[-4:]
    assert row["secret_enc"] is not None
    assert CLIENT_SECRET not in str(row["secret_enc"])

    details = await audit_details(sm, "integration_created")
    assert details, "brak wpisu audytu integration_created"
    assert all(CLIENT_SECRET not in value for value in details)


async def test_ag25_list_is_id_desc_and_get_returns_dto(
    svc: Any, prefix: str, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """AG-25 + §4: `GET /api/integrations` po `id DESC`, `GET /{id}` z dokładnymi kluczami."""
    _owner, first_dataset = await seed_dataset()
    first = await create_integration(first_dataset, name="Pierwsza")
    _owner2, second_dataset = await seed_dataset()
    second = await create_integration(second_dataset, name="Druga")

    listed = await svc.get(f"{prefix}/api/integrations")

    assert listed.status_code == OK, listed.text
    items = listed.json()["data"]
    assert [item["id"] for item in items] == [second["id"], first["id"]]
    assert all(set(item) == INTEGRATION_KEYS for item in items)

    got = await svc.get(f"{prefix}/api/integrations/{first['id']}")
    assert got.status_code == OK
    assert set(got.json()["data"]) == INTEGRATION_KEYS
    assert got.json()["data"]["id"] == first["id"]

    missing = await svc.get(f"{prefix}/api/integrations/999999")
    assert missing.status_code == NOT_FOUND
    assert missing.json() == {"error": "Not found"}

    invalid = await svc.get(f"{prefix}/api/integrations/abc")
    assert invalid.status_code == BAD_REQUEST
    assert invalid.json() == {"error": "Invalid integration id"}


async def test_ag25_update_subset_and_secret_mask(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-25: PUT zmienia podzbiór pól; pusty sekret nie rusza maski, nowy sekret ją zmienia."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)

    renamed = await svc.put(
        f"{prefix}/api/integrations/{created['id']}", json={"name": "Po zmianie"}
    )
    assert renamed.status_code == OK, renamed.text
    updated = renamed.json()["data"]
    assert set(updated) == INTEGRATION_KEYS
    assert updated["name"] == "Po zmianie"
    assert updated["client_secret_masked"] == CLIENT_SECRET_MASK
    assert updated["dataset_id"] == dataset_id
    assert updated["scan_interval_seconds"] == DEFAULT_SCAN_INTERVAL_SECONDS

    kept = await svc.put(
        f"{prefix}/api/integrations/{created['id']}",
        json={"client_secret": "", "scan_interval_seconds": UPDATED_SCAN_INTERVAL_SECONDS},
    )
    assert kept.status_code == OK, kept.text
    assert kept.json()["data"]["client_secret_masked"] == CLIENT_SECRET_MASK
    assert kept.json()["data"]["scan_interval_seconds"] == UPDATED_SCAN_INTERVAL_SECONDS

    rotated = await svc.put(
        f"{prefix}/api/integrations/{created['id']}",
        json={"client_secret": ROTATED_SECRET},
    )
    assert rotated.status_code == OK, rotated.text
    assert rotated.json()["data"]["client_secret_masked"] == "••••" + ROTATED_SECRET[-4:]
    assert ROTATED_SECRET not in rotated.text

    details = await audit_details(sm, "integration_updated")
    assert details
    assert all(ROTATED_SECRET not in value for value in details)


async def test_ag25_update_errors(
    svc: Any, prefix: str, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """AG-25: PUT daje 404 (brak integracji), 400 (brak datasetu), 409 (dataset zajęty)."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    _owner2, other_dataset = await seed_dataset()
    await create_integration(other_dataset)

    missing = await svc.put(f"{prefix}/api/integrations/999999", json={"name": "X"})
    assert missing.status_code == NOT_FOUND
    assert missing.json() == {"error": "Not found"}

    unknown_dataset = await svc.put(
        f"{prefix}/api/integrations/{created['id']}", json={"dataset_id": uuid.uuid4().hex}
    )
    assert unknown_dataset.status_code == BAD_REQUEST
    assert unknown_dataset.json()["error"].endswith("not found")

    taken = await svc.put(
        f"{prefix}/api/integrations/{created['id']}", json={"dataset_id": other_dataset}
    )
    assert taken.status_code == CONFLICT
    assert taken.json() == {
        "error": f"Dataset {other_dataset} is already linked to another integration"
    }


async def test_ag25_delete_keeps_runs_and_events(  # noqa: PLR0913, PLR0917 — fixture'y
    svc: Any,
    prefix: str,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-25/K7 §7 p. 7: DELETE kasuje kontenery i mappingi, zostawia przebiegi i zdarzenia."""
    _owner, dataset_id = await seed_dataset()
    created = await create_integration(dataset_id)
    integration_id = created["id"]
    run_id = await insert_finished_run(sm, integration_id)
    async with transaction(sm) as session:
        await integrations_repo.upsert_container(
            session, integration_id, CONTAINER_D1, name=CONTAINER_D1_NAME, now_ms=NOW_MS
        )
        await integrations_repo.upsert_mapping(
            session,
            MappingRow(
                integration_id=integration_id,
                container_id=CONTAINER_D1,
                item_id="i1",
                document_id=uuid.uuid4().hex,
                content_tag=None,
                meta_tag=None,
                name="a.txt",
                path="/a.txt",
                web_url=None,
                last_status="ok",
                last_error=None,
                updated_at=NOW_MS,
            ),
        )

    deleted = await svc.request("DELETE", f"{prefix}/api/integrations/{integration_id}")
    assert deleted.status_code == OK, deleted.text
    assert deleted.json() == {"data": {"id": integration_id, "deleted": True}}

    gone = await svc.get(f"{prefix}/api/integrations/{integration_id}")
    assert gone.status_code == NOT_FOUND

    runs = await svc.get(
        f"{prefix}/api/integrations/runs", params={"integration_id": integration_id}
    )
    assert runs.status_code == OK
    assert [run["id"] for run in runs.json()["data"]] == [run_id]

    again = await svc.request("DELETE", f"{prefix}/api/integrations/{integration_id}")
    assert again.status_code == NOT_FOUND
    assert again.json() == {"error": "Not found"}

    async with transaction(sm) as session:
        containers = (
            await session.execute(
                text("SELECT COUNT(*) FROM integration_containers WHERE integration_id = :id"),
                {"id": integration_id},
            )
        ).scalar_one()
        mappings = (
            await session.execute(
                text("SELECT COUNT(*) FROM integration_item_mappings WHERE integration_id = :id"),
                {"id": integration_id},
            )
        ).scalar_one()
    assert (int(containers), int(mappings)) == (0, 0)
