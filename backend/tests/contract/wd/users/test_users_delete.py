"""Trasa ``DELETE /api/wd/v1/users/{user_id}`` — tryby usunięcia (kontrakt E3-6a §0 p. 8, §2)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.contract.wd.admin_support import ADMIN_EMAIL, AuditRows, MakeUser

pytestmark = pytest.mark.contract

OK = 200
BAD_REQUEST = 400
NO_CONTENT = 204
NOT_FOUND = 404
CONFLICT = 409

BASE = "/api/wd/v1/users"


def wd_error(response: httpx.Response) -> dict[str, Any]:
    """Koperta błędu WD z odpowiedzi (kontrakt §0 p. 1)."""
    body: dict[str, Any] = response.json()
    return body["error"]


async def _id_of(admin: httpx.AsyncClient, email: str) -> str:
    """Identyfikator jedynego konta o podanym e-mailu (filtr ``email``)."""
    response = await admin.get(BASE, params={"email": email})
    assert response.status_code == OK, response.text
    items = response.json()["data"]["items"]
    assert len(items) == 1, items
    return str(items[0]["id"])


async def test_delete_defaults_to_transfer(
    admin: httpx.AsyncClient, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """Bez ``mode`` obowiązuje ``transfer`` (nie ustawienie serwera), 204 z pustym ciałem."""
    row = await make_user("delete-transfer@example.com")

    response = await admin.delete(f"{BASE}/{row.id}")

    assert response.status_code == NO_CONTENT, response.text
    assert response.content == b""
    rows = await audit_rows("user_deleted")
    assert len(rows) == 1
    assert rows[0].target_type == "user"
    assert rows[0].target_id == row.id
    assert rows[0].details["email"] == "delete-transfer@example.com"
    assert rows[0].details["mode"] == "transfer"
    assert rows[0].details["transferred_to"] == ADMIN_EMAIL

    gone = await admin.get(f"{BASE}/{row.id}")
    assert gone.status_code == NOT_FOUND


async def test_delete_cascade_mode(
    admin: httpx.AsyncClient, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """Jawny ``?mode=cascade`` usuwa zasoby zależne i trafia do audytu (kontrakt §0 p. 8)."""
    row = await make_user("delete-cascade@example.com")

    response = await admin.delete(f"{BASE}/{row.id}", params={"mode": "cascade"})

    assert response.status_code == NO_CONTENT, response.text
    rows = await audit_rows("user_deleted")
    assert len(rows) == 1
    assert rows[0].details["mode"] == "cascade"
    assert rows[0].details["transferred_to"] is None


async def test_delete_rejects_unknown_mode(admin: httpx.AsyncClient, make_user: MakeUser) -> None:
    """``mode`` spoza ``transfer|cascade`` → 400 ``validation_failed`` (kontrakt §0 p. 8)."""
    row = await make_user("delete-bad-mode@example.com")

    response = await admin.delete(f"{BASE}/{row.id}", params={"mode": "x"})

    assert response.status_code == BAD_REQUEST, response.text
    assert wd_error(response)["code"] == "validation_failed"


async def test_delete_sole_admin_is_conflict(admin: httpx.AsyncClient) -> None:
    """Usunięcie jedynego admina → 409 ``operation_not_allowed`` (straż w usłudze)."""
    admin_id = await _id_of(admin, ADMIN_EMAIL)

    response = await admin.delete(f"{BASE}/{admin_id}")

    assert response.status_code == CONFLICT, response.text
    assert wd_error(response)["code"] == "operation_not_allowed"


async def test_delete_unknown_user_is_not_found(admin: httpx.AsyncClient) -> None:
    """Nieznany identyfikator → 404 ``not_found`` z usługi (kontrakt §0 p. 4)."""
    response = await admin.delete(f"{BASE}/unknown-id")

    assert response.status_code == NOT_FOUND
    assert wd_error(response)["code"] == "not_found"
