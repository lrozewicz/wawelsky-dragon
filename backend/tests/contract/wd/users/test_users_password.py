"""Trasy hasła i aktywności WD: ``/users/{id}/password|activate|deactivate`` (kontrakt E3-6a §4)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.container import Container
from tests.contract.wd.admin_support import ADMIN_EMAIL, AuditRows, MakeUser

pytestmark = pytest.mark.contract

OK = 200
BAD_REQUEST = 400
NO_CONTENT = 204
NOT_FOUND = 404
CONFLICT = 409

BASE = "/api/wd/v1/users"
NEW_PASSWORD = "Nowe-Haslo-1!"  # noqa: S105 — hasło wyłącznie testowe


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


async def test_set_password_changes_hash_and_audits(
    admin: httpx.AsyncClient, container: Container, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """204; hash i ``token_version`` się zmieniają, audyt ``user_password_set`` bez hasła (§4)."""
    row = await make_user("pwd@example.com")
    assert container.users is not None
    before = await container.users.get(row.id)

    response = await admin.post(f"{BASE}/{row.id}/password", json={"new_password": NEW_PASSWORD})

    assert response.status_code == NO_CONTENT, response.text
    assert response.content == b""
    assert NEW_PASSWORD not in response.text
    after = await container.users.get(row.id)
    assert after.password_hash != before.password_hash
    assert after.token_version == before.token_version + 1

    rows = await audit_rows("user_password_set")
    assert len(rows) == 1
    assert rows[0].target_id == row.id
    assert rows[0].details == {"email": "pwd@example.com"}
    assert NEW_PASSWORD not in str(rows[0].details)


async def test_set_password_rejects_weak_password(
    admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Za krótkie hasło → 400 z usługi (``validate_new_password``), bez wpisu audytu."""
    row = await make_user("weak-pwd@example.com")

    response = await admin.post(f"{BASE}/{row.id}/password", json={"new_password": "short"})

    assert response.status_code == BAD_REQUEST, response.text
    assert wd_error(response)["code"] == "validation_failed"


async def test_set_password_missing_field_is_400(
    admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Brak ``new_password`` → 400 ``validation_failed`` w kopercie WD (nigdy 422)."""
    row = await make_user("no-pwd@example.com")

    response = await admin.post(f"{BASE}/{row.id}/password", json={})

    assert response.status_code == BAD_REQUEST, response.text
    assert wd_error(response)["code"] == "validation_failed"


async def test_set_password_rejects_external_identity_source(
    admin: httpx.AsyncClient, container: Container
) -> None:
    """Konto ``auth_source != "local"`` → 409 ``operation_not_allowed`` (kontrakt §4).

    Schemat `users` dopuszcza ``ENUM('local','oidc','both')`` (0001_initial), więc konto
    o tożsamości zewnętrznej zakładamy z ``auth_source="oidc"`` — trasa sprawdza
    ``!= "local"``, nie konkretną nazwę dostawcy.
    """
    assert container.users is not None
    row = await container.users.create(email="oidc@example.com", password=None, auth_source="oidc")

    response = await admin.post(f"{BASE}/{row.id}/password", json={"new_password": NEW_PASSWORD})

    assert response.status_code == CONFLICT, response.text
    assert wd_error(response)["code"] == "operation_not_allowed"


async def test_set_password_unknown_user_is_not_found(admin: httpx.AsyncClient) -> None:
    """Nieznany identyfikator → 404 ``not_found``."""
    response = await admin.post(f"{BASE}/unknown-id/password", json={"new_password": NEW_PASSWORD})

    assert response.status_code == NOT_FOUND
    assert wd_error(response)["code"] == "not_found"


async def test_activate_toggles_state_and_audits(
    admin: httpx.AsyncClient, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """``deactivate``/``activate`` zwracają świeże konto i zapisują wpisy audytu (kontrakt §4)."""
    row = await make_user("toggle@example.com")

    off = await admin.post(f"{BASE}/{row.id}/deactivate")
    assert off.status_code == OK, off.text
    assert off.json()["data"]["is_active"] is False

    on = await admin.post(f"{BASE}/{row.id}/activate")
    assert on.status_code == OK, on.text
    assert on.json()["data"]["is_active"] is True

    deactivated = await audit_rows("user_deactivated")
    activated = await audit_rows("user_activated")
    assert [(r.action, r.target_id) for r in deactivated] == [("user_deactivated", row.id)]
    assert [(r.action, r.target_id) for r in activated] == [("user_activated", row.id)]
    assert deactivated[0].details == {"email": "toggle@example.com"}


async def test_deactivate_sole_admin_is_conflict(admin: httpx.AsyncClient) -> None:
    """Dezaktywacja jedynego admina → 409 ``operation_not_allowed`` (07 §6.2)."""
    admin_id = await _id_of(admin, ADMIN_EMAIL)

    response = await admin.post(f"{BASE}/{admin_id}/deactivate")

    assert response.status_code == CONFLICT, response.text
    assert wd_error(response)["code"] == "operation_not_allowed"


async def test_activate_unknown_user_is_not_found(admin: httpx.AsyncClient) -> None:
    """Aktywacja nieznanego konta → 404 ``not_found`` z usługi."""
    response = await admin.post(f"{BASE}/unknown-id/activate")

    assert response.status_code == NOT_FOUND
    assert wd_error(response)["code"] == "not_found"
