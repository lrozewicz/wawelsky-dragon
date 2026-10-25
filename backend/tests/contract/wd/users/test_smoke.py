"""Dym kontraktowych testów tras WD admina (zadanie T1): fixture'y i działające trasy users.

``tests/contract/wd/users/conftest.py`` re-eksportuje fixture'y z ``admin_support`` — te dwa
testy dowodzą, że działają (klient ``admin`` z kluczem API superusera, helpery ``make_user``
i ``audit_rows``). Po T2 router users nie jest już pusty, więc dym sprawdza realną odpowiedź
strony kont zamiast 404 pustego routera.
"""

from __future__ import annotations

import httpx
import pytest

from tests.contract.wd.admin_support import AuditRows, MakeUser

pytestmark = pytest.mark.contract

OK = 200
BASE = "/api/wd/v1/users"


async def test_users_route_serves_the_page_from_the_admin_client(
    admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Klient ``admin`` dostaje kopertę strony kont z założonym użytkownikiem (T2)."""
    row = await make_user("smoke-user@example.com")

    response = await admin.get(BASE)

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert set(data) == {"items", "total", "page", "page_size"}
    assert any(item["id"] == row.id for item in data["items"])


async def test_fixtures_provide_user_and_audit_helpers(
    make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """Helpery fixture'ów: ``make_user`` zakłada konto, ``audit_rows`` czyta dziennik audytu."""
    row = await make_user("smoke-user@example.com")

    assert row.email == "smoke-user@example.com"
    assert row.is_superuser is False
    assert await audit_rows("smoke_no_such_action") == []
