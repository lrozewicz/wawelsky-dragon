"""Test dymny tras `/api/users*` i `/api/keys*` (brief T5b, kontrakt C8; AG-01…AG-11).

Pełny zestaw przypadków AG jest w T6 — tutaj ścieżka create → get → list → key
create/list/delete → delete user, po prefiksie. E-mail `a+b@example.com` w ścieżce
jako `a%2Bb%40example.com` (wymaganie 6 briefu).
"""

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import audit_log as audit_repo
from app.db.uow import transaction

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

_OK = 200
_CREATED = 201
_BAD_REQUEST = 400
_NOT_FOUND = 404

_EMAIL = "a+b@example.com"
_EMAIL_PATH = "a%2Bb%40example.com"
_ADMIN_EMAIL = "boss@x.pl"
_ANN_EMAIL_PATH = "ann%40x.pl"
_UNKNOWN_PATH = "ghost%40nowhere.test"
# Hasło atrapy (nie jest prawdziwym sekretem), ≥ 8 znaków wg validate_new_password.
_PASSWORD = "Sup3r-secret-pw"  # noqa: S105


async def _user_id(sm: async_sessionmaker[AsyncSession], email: str) -> str:
    """Id wiersza `users` o danym e-mailu (do sprawdzenia `tenant_id` klucza)."""
    async with transaction(sm) as session:
        result = await session.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": email}
        )
    return str(result.scalar_one())


async def _audit(sm: async_sessionmaker[AsyncSession], action: str) -> list[audit_repo.AuditRow]:
    """Wpisy audytu danej akcji, kolejność wstawienia (kontrakt C3)."""
    async with transaction(sm) as session:
        return await audit_repo.list_by_action(session, action)


async def test_users_and_keys_smoke(
    svc: httpx.AsyncClient, prefix: str, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wymaganie 6: create → get → list → key create/list/delete → delete user."""
    admin = await svc.post(
        f"{prefix}/api/users",
        json={"email": _ADMIN_EMAIL, "password": _PASSWORD, "role": "admin"},
    )
    assert admin.status_code == _CREATED
    assert admin.json()["data"]["is_superuser"] is True

    created = await svc.post(f"{prefix}/api/users", json={"email": _EMAIL, "password": _PASSWORD})
    assert created.status_code == _CREATED
    detail = created.json()["data"]
    assert detail["email"] == _EMAIL
    assert detail["is_active"] == "1"
    assert detail["is_superuser"] is False
    assert detail["nickname"] == "a+b"

    got = await svc.get(f"{prefix}/api/users/{_EMAIL_PATH}")
    assert got.status_code == _OK
    assert got.json()["data"]["email"] == _EMAIL

    listed = await svc.get(f"{prefix}/api/users")
    assert listed.status_code == _OK
    assert _EMAIL in [item["email"] for item in listed.json()["data"]]

    key = await svc.post(f"{prefix}/api/keys/{_EMAIL_PATH}")
    assert key.status_code == _CREATED
    record = key.json()["data"]
    assert record["token"].startswith("ragflow-")
    assert record["tenant_id"] == await _user_id(sm, _EMAIL)
    assert record["dialog_id"] is None
    assert record["source"] is None
    assert record["beta"] == ""

    keys = await svc.get(f"{prefix}/api/keys/{_EMAIL_PATH}")
    assert keys.status_code == _OK
    assert [item["token"] for item in keys.json()["data"]] == [record["token"]]

    removed_key = await svc.request("DELETE", f"{prefix}/api/keys/{_EMAIL_PATH}/{record['token']}")
    assert removed_key.status_code == _OK
    assert removed_key.json() == {"data": {"message": "Key deleted"}}

    removed = await svc.request("DELETE", f"{prefix}/api/users/{_EMAIL_PATH}")
    assert removed.status_code == _OK
    assert removed.json() == {"data": {"message": "User deleted"}}


async def test_create_without_password_is_400(svc: httpx.AsyncClient, prefix: str) -> None:
    """C8: brak `password` → 400 `email and password are required`."""
    response = await svc.post(f"{prefix}/api/users", json={"email": "ann@x.pl"})
    assert response.status_code == _BAD_REQUEST
    assert response.json() == {"error": "email and password are required"}


async def test_unknown_user_is_404(svc: httpx.AsyncClient, prefix: str) -> None:
    """C8: nieznany e-mail → 404 `User not found` (users i keys)."""
    user = await svc.get(f"{prefix}/api/users/{_UNKNOWN_PATH}")
    assert user.status_code == _NOT_FOUND
    assert user.json() == {"error": "User not found"}
    keys = await svc.get(f"{prefix}/api/keys/{_UNKNOWN_PATH}")
    assert keys.status_code == _NOT_FOUND
    assert keys.json() == {"error": "User not found"}


async def test_delete_foreign_key_is_404(svc: httpx.AsyncClient, prefix: str) -> None:
    """C8/K7 §1.5: klucz innego użytkownika → 404 `Key not found`."""
    await svc.post(f"{prefix}/api/users", json={"email": "ann@x.pl", "password": _PASSWORD})
    await svc.post(f"{prefix}/api/users", json={"email": "bob@x.pl", "password": _PASSWORD})
    foreign = (await svc.post(f"{prefix}/api/keys/bob%40x.pl")).json()["data"]["token"]
    response = await svc.request("DELETE", f"{prefix}/api/keys/ann%40x.pl/{foreign}")
    assert response.status_code == _NOT_FOUND
    assert response.json() == {"error": "Key not found"}
    still_there = await svc.get(f"{prefix}/api/keys/bob%40x.pl")
    assert [item["token"] for item in still_there.json()["data"]] == [foreign]


@pytest.mark.parametrize("field", ["is_active", "is_superuser"])
async def test_put_rejects_non_boolean_flag(
    svc: httpx.AsyncClient, prefix: str, field: str
) -> None:
    """Wymaganie 3: flaga inna niż bool → 400 `… must be a boolean`."""
    await svc.post(f"{prefix}/api/users", json={"email": "ann@x.pl", "password": _PASSWORD})
    response = await svc.put(f"{prefix}/api/users/{_ANN_EMAIL_PATH}", json={field: "yes"})
    assert response.status_code == _BAD_REQUEST
    assert response.json() == {"error": f"{field} must be a boolean"}


async def test_put_message_and_audit(
    svc: httpx.AsyncClient, prefix: str, sm: async_sessionmaker[AsyncSession]
) -> None:
    """C8: komunikat z fragmentów zmian + audyt `user_updated`; brak zmian → `no changes`."""
    await svc.post(f"{prefix}/api/users", json={"email": "ann@x.pl", "password": _PASSWORD})
    changed = await svc.put(
        f"{prefix}/api/users/{_ANN_EMAIL_PATH}",
        json={"nickname": "Ann", "is_active": False, "is_superuser": True},
    )
    assert changed.json() == {
        "data": {"message": "nickname updated, is_active set to off, is_superuser set to true"}
    }
    rows = await _audit(sm, "user_updated")
    assert rows[0].actor_label == "X-API-Secret"
    assert rows[0].details == {
        "email": "ann@x.pl",
        "changes": ["nickname", "is_active", "is_superuser"],
    }
    same = await svc.put(f"{prefix}/api/users/{_ANN_EMAIL_PATH}", json={})
    assert same.json() == {"data": {"message": "no changes"}}
    assert len(await _audit(sm, "user_updated")) == 1
