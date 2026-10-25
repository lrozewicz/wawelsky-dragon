"""CRUD integracji WD ``/api/wd/v1/integrations*`` (brief T3, kontrakt E4-3b §4).

Asercje na dokładnym zbiorze kluczy DTO (``integration_dto`` plus ``type`` = 20 kluczy),
kopercie WD (``{"data": …}`` / ``{"error":{"code",…}}``), statusach HTTP i braku plaintextu
sekretu w każdej odpowiedzi. Wpis audytu po ``create`` ma ``actor_label`` administratora
(nie ``"X-API-Secret"`` — trasy WD nie mają tego nagłówka, kontrakt §0 p. 3).
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.uow import transaction
from tests.contract.wd.integrations.conftest import (
    ADMIN_EMAIL,
    CLIENT_ID,
    CLIENT_SECRET,
    SITE_ID,
    SITE_URL,
    TENANT_ID,
    integration_body,
)

pytestmark = pytest.mark.contract

OK = 200
CREATED = 201
NO_CONTENT = 204
BAD_REQUEST = 400
UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404
CONFLICT = 409

BASE = "/api/wd/v1/integrations"
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
CLIENT_SECRET_MASK = "••••abcd"  # noqa: S105 — maska, nie sekret

INTEGRATION_KEYS = frozenset(
    {
        "id",
        "type",
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
DEFAULT_MAX_FILE_SIZE_BYTES = 209_715_200
DEFAULT_SCAN_INTERVAL_SECONDS = 300

# Paginacja w pamięci: trzy integracje po dwie na stronę (kontrakt §0 p. 4).
TOTAL = 3
PAGE_SIZE = 2

# (metoda, ścieżka) każdej trasy CRUD — dla testów 401/403 (brief „Testy negatywne”).
_WD_ROUTES = [
    ("get", BASE),
    ("post", BASE),
    ("post", f"{BASE}/test"),
    ("get", f"{BASE}/1"),
    ("patch", f"{BASE}/1"),
    ("delete", f"{BASE}/1"),
    ("post", f"{BASE}/1/test"),
]


def create_body(dataset_id: str, **over: object) -> dict[str, object]:
    """Poprawne ciało ``POST /integrations``: ``type`` plus pola SVC (kontrakt §2)."""
    return {"type": "sharepoint", **integration_body(dataset_id), **over}


def wd_error(response: httpx.Response) -> dict[str, Any]:
    """Koperta błędu WD z odpowiedzi (kontrakt §0 p. 6)."""
    body: dict[str, Any] = response.json()
    return body["error"]


async def test_list_empty_page(admin: httpx.AsyncClient) -> None:
    """Brak integracji → 200 z pustą stroną domyślną (kontrakt §4)."""
    response = await admin.get(BASE)

    assert response.status_code == OK, response.text
    assert response.json() == {"data": {"items": [], "total": 0, "page": 1, "page_size": 20}}


@pytest.mark.parametrize(
    "params", [{"page": 0}, {"page": -1}, {"page": "x"}, {"page_size": 0}, {"page_size": 101}]
)
async def test_list_rejects_page_out_of_range(
    admin: httpx.AsyncClient, params: dict[str, object]
) -> None:
    """``page``/``page_size`` poza zakresem → 400 ``validation_failed`` bez cichego clampu."""
    response = await admin.get(BASE, params=params)

    assert response.status_code == BAD_REQUEST, response.text
    error = wd_error(response)
    assert error["code"] == "validation_failed"
    assert error["details"]["errors"]


async def test_list_paginates_in_memory(
    admin: httpx.AsyncClient, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """Trzy integracje, ``page_size=2`` → dwie strony po 2 i 1, ``total`` niezmienne, id DESC."""
    created = [await create_integration(await seed_dataset()) for _ in range(TOTAL)]
    newest_first = [item["id"] for item in reversed(created)]

    first = await admin.get(BASE, params={"page": 1, "page_size": PAGE_SIZE})
    second = await admin.get(BASE, params={"page": 2, "page_size": PAGE_SIZE})

    assert first.status_code == OK, first.text
    assert second.status_code == OK, second.text
    page1 = first.json()["data"]
    page2 = second.json()["data"]
    assert (page1["total"], page1["page"], page1["page_size"]) == (TOTAL, 1, PAGE_SIZE)
    assert [item["id"] for item in page1["items"]] == newest_first[:PAGE_SIZE]
    assert [item["id"] for item in page2["items"]] == newest_first[PAGE_SIZE:]
    assert page2["total"] == TOTAL
    assert all(set(item) == INTEGRATION_KEYS for item in page1["items"] + page2["items"])


async def test_create_returns_exact_integration_dto(
    admin: httpx.AsyncClient, connector: Any, seed_dataset: Any
) -> None:
    """201 + dokładne 20 kluczy, ``type``, maska sekretu, ``site_id`` z ``resolve``, ISO czasy."""
    dataset_id = await seed_dataset()

    response = await admin.post(BASE, json=create_body(dataset_id))

    assert response.status_code == CREATED, response.text
    body = response.json()
    assert set(body) == {"data"}
    created = body["data"]
    assert set(created) == INTEGRATION_KEYS
    assert created["type"] == "sharepoint"
    assert isinstance(created["id"], int)
    assert not isinstance(created["id"], bool)
    assert created["dataset_id"] == dataset_id
    assert created["client_secret_masked"] == CLIENT_SECRET_MASK
    assert created["client_id"] == CLIENT_ID
    assert created["tenant_id"] == TENANT_ID
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


@pytest.mark.parametrize(
    "over",
    [
        {"type": "other"},
        {"type": None},
        {"scan_interval_seconds": 10},
        {"scan_interval_seconds": "60"},
        {"max_file_size_bytes": 0},
        {"name": ""},
    ],
)
async def test_create_validation_is_400(
    admin: httpx.AsyncClient, connector: Any, seed_dataset: Any, over: dict[str, object]
) -> None:
    """Złe pola ciała create → 400 ``validation_failed`` w kopercie WD (nigdy 422)."""
    dataset_id = await seed_dataset()
    body = create_body(dataset_id, **over)

    response = await admin.post(BASE, json=body)

    assert response.status_code == BAD_REQUEST, response.text
    error = wd_error(response)
    assert error["code"] == "validation_failed"
    assert error["details"]["errors"]


async def test_create_without_type_is_400_and_keeps_secret_out(
    admin: httpx.AsyncClient, connector: Any, seed_dataset: Any
) -> None:
    """Brak ``type`` → 400 (``type`` wymagany), a ``input`` błędu nie wynosi ciała z sekretem.

    Błąd ``missing`` ma w pydanticu ``input`` = całe ciało żądania; od zmiany 14 (K3 §5)
    ``input`` usuwa globalny handler K3 dla przestrzeni ``wd`` (DEC-082 → DEC-094).
    """
    dataset_id = await seed_dataset()
    body = integration_body(dataset_id)

    response = await admin.post(BASE, json=body)

    assert response.status_code == BAD_REQUEST, response.text
    assert wd_error(response)["code"] == "validation_failed"
    assert wd_error(response)["details"]["errors"][0]["type"] == "missing"
    assert "input" not in wd_error(response)["details"]["errors"][0]
    assert CLIENT_SECRET not in response.text


async def test_create_error_response_never_leaks_secret(
    admin: httpx.AsyncClient, connector: Any, seed_dataset: Any
) -> None:
    """Poprawny sekret + błędne inne pole → 400, ale sekret nie występuje w treści (K3 §4)."""
    dataset_id = await seed_dataset()
    body = create_body(dataset_id, scan_interval_seconds=10)

    response = await admin.post(BASE, json=body)

    assert response.status_code == BAD_REQUEST, response.text
    assert CLIENT_SECRET not in response.text


async def test_create_rejects_taken_dataset(
    admin: httpx.AsyncClient, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """Drugi POST na ten sam dataset → 409 ``conflict`` (jak SVC)."""
    dataset_id = await seed_dataset()
    await create_integration(dataset_id)

    response = await admin.post(BASE, json=create_body(dataset_id))

    assert response.status_code == CONFLICT, response.text
    assert wd_error(response)["code"] == "conflict"


async def test_create_rejects_unknown_dataset(admin: httpx.AsyncClient, connector: Any) -> None:
    """Nieistniejący dataset → 400 ``validation_failed`` z komunikatem usługi."""
    response = await admin.post(BASE, json=create_body("a" * 32))

    assert response.status_code == BAD_REQUEST, response.text
    error = wd_error(response)
    assert error["code"] == "validation_failed"
    assert error["message"] == f"Dataset {'a' * 32} not found"


async def test_create_audits_admin_email(
    admin: httpx.AsyncClient,
    connector: Any,
    create_integration: Any,
    seed_dataset: Any,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Audyt create: ``actor_label`` = e-mail administratora, ``details`` bez sekretu (§0 p. 3)."""
    dataset_id = await seed_dataset()
    await create_integration(dataset_id)

    async with transaction(sm) as session:
        rows = (
            await session.execute(
                text("SELECT actor_label, details FROM audit_log WHERE action = :action"),
                {"action": "integration_created"},
            )
        ).all()

    assert len(rows) == 1
    assert rows[0][0] == ADMIN_EMAIL
    assert rows[0][0] != "X-API-Secret"
    assert CLIENT_SECRET not in str(rows[0][1])


async def test_get_returns_dto_and_not_found(
    admin: httpx.AsyncClient, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """``GET /{id}`` zwraca ten sam DTO; brak → 404 ``not_found``; zły ``id`` → 400."""
    created = await create_integration(await seed_dataset())

    got = await admin.get(f"{BASE}/{created['id']}")

    assert got.status_code == OK, got.text
    assert got.json()["data"] == created

    missing = await admin.get(f"{BASE}/999")
    assert missing.status_code == NOT_FOUND
    assert wd_error(missing) == {"code": "not_found", "message": "Not found", "details": None}

    invalid = await admin.get(f"{BASE}/abc")
    assert invalid.status_code == BAD_REQUEST
    assert wd_error(invalid)["code"] == "validation_failed"


async def test_patch_changes_only_given_fields(
    admin: httpx.AsyncClient, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """``PATCH`` zmienia podane pole, reszta bez zmian; ``type`` niezmienialny (§4)."""
    created = await create_integration(await seed_dataset())

    response = await admin.patch(f"{BASE}/{created['id']}", json={"name": "nowa"})

    assert response.status_code == OK, response.text
    updated = response.json()["data"]
    assert set(updated) == INTEGRATION_KEYS
    assert updated["name"] == "nowa"
    unchanged = {key: value for key, value in updated.items() if key not in {"name", "updated_at"}}
    assert unchanged == {
        key: value for key, value in created.items() if key not in {"name", "updated_at"}
    }

    same_type = await admin.patch(f"{BASE}/{created['id']}", json={"type": "sharepoint"})
    assert same_type.status_code == OK, same_type.text
    assert same_type.json()["data"]["type"] == "sharepoint"


async def test_patch_error_response_never_leaks_secret(
    admin: httpx.AsyncClient, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """Poprawny sekret w PATCH + błędne inne pole → 400, ale sekret nie w tekście (errata §7)."""
    created = await create_integration(await seed_dataset())
    body = {"client_secret": CLIENT_SECRET, "site_url": ""}

    response = await admin.patch(f"{BASE}/{created['id']}", json=body)

    assert response.status_code == BAD_REQUEST, response.text
    assert wd_error(response)["code"] == "validation_failed"
    assert CLIENT_SECRET not in response.text


async def test_patch_rejects_bad_type_and_missing_integration(
    admin: httpx.AsyncClient, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """``PATCH`` z innym ``type`` → 400; brak integracji → 404 (kontrakt §4)."""
    created = await create_integration(await seed_dataset())

    bad_type = await admin.patch(f"{BASE}/{created['id']}", json={"type": "other"})
    assert bad_type.status_code == BAD_REQUEST
    assert wd_error(bad_type)["code"] == "validation_failed"

    missing = await admin.patch(f"{BASE}/999", json={"name": "X"})
    assert missing.status_code == NOT_FOUND
    assert wd_error(missing)["code"] == "not_found"


async def test_delete_is_204_then_not_found(
    admin: httpx.AsyncClient, connector: Any, create_integration: Any, seed_dataset: Any
) -> None:
    """``DELETE`` → 204 z pustym ciałem; kolejny ``GET`` i ``DELETE`` → 404 (kontrakt §4)."""
    created = await create_integration(await seed_dataset())

    deleted = await admin.delete(f"{BASE}/{created['id']}")

    assert deleted.status_code == NO_CONTENT, deleted.text
    assert deleted.content == b""

    gone = await admin.get(f"{BASE}/{created['id']}")
    assert gone.status_code == NOT_FOUND

    again = await admin.delete(f"{BASE}/{created['id']}")
    assert again.status_code == NOT_FOUND
    assert wd_error(again)["code"] == "not_found"


@pytest.mark.parametrize(("method", "path"), _WD_ROUTES)
async def test_routes_require_authentication(
    anon: httpx.AsyncClient, method: str, path: str
) -> None:
    """Bez nagłówka ``Authorization`` każda trasa → 401 ``unauthorized`` (przed walidacją)."""
    response = await anon.request(method, path, json={})

    assert response.status_code == UNAUTHORIZED, response.text
    assert wd_error(response)["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path"), _WD_ROUTES)
async def test_routes_reject_non_admin(member: httpx.AsyncClient, method: str, path: str) -> None:
    """Nie-superuser na każdej trasie → 403 ``permission_denied`` (polityka, kontrakt §0 p. 2)."""
    response = await member.request(method, path, json={})

    assert response.status_code == FORBIDDEN, response.text
    assert wd_error(response)["code"] == "permission_denied"
