"""Testy kontraktowe tras `/api/users*` (brief T6a, kontrakt C8; AG-09, AG-10, AG-15…AG-17).

Obejmuje też dwie poprawki znalezione w T5b: walidację typu `nickname` w POST oraz jawne
`null` w polach PUT. Każdy test parametryzowany po prefiksie montażu (`""`, `"/user-api"`).
"""

import json
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import audit_log as audit_repo
from app.db.uow import transaction

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

SeedChat = Callable[[str | None], Awaitable[str]]

_OK = 200
_CREATED = 201
_BAD_REQUEST = 400
_NOT_FOUND = 404
_CONFLICT = 409

_ADMIN = "boss%40x.pl"
_ANN = "ann%40x.pl"
_ANN_PLUS = "a%2Bb%40x.pl"
# Hasła atrapy (nie są prawdziwymi sekretami), ≥ 8 znaków wg validate_new_password.
_PASSWORD = "Sup3r-secret-pw"  # noqa: S105
_NEW_PASSWORD = "N0we-haslo-xyz"  # noqa: S105

# AG-10: `new Date()` w Node/Bun (K7 §3); bez `bun` schodzimy do parsedate_to_datetime.
_BUN = shutil.which("bun")
_BUN_JS = "console.log(new Date(process.argv[1]).getTime())"


async def _user_id(sm: async_sessionmaker[AsyncSession], email: str) -> str:
    """Id wiersza `users` o danym e-mailu (porównanie `tenant_id` po transferze)."""
    async with transaction(sm) as session:
        result = await session.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": email}
        )
    return str(result.scalar_one())


async def _count(sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, str]) -> int:
    """Wartość COUNT(*) zapytania (weryfikacja skutków usunięcia konta)."""
    async with transaction(sm) as session:
        return int((await session.execute(text(sql), params)).scalar_one())


async def _audit(sm: async_sessionmaker[AsyncSession], action: str) -> list[audit_repo.AuditRow]:
    """Wpisy audytu danej akcji, kolejność wstawienia (kontrakt C3)."""
    async with transaction(sm) as session:
        return await audit_repo.list_by_action(session, action)


async def _create(svc: httpx.AsyncClient, prefix: str, email: str, **extra: object) -> str:
    """POST /api/users z asercją 201; zwraca e-mail z odpowiedzi (znormalizowany)."""
    response = await svc.post(
        f"{prefix}/api/users", json={"email": email, "password": _PASSWORD, **extra}
    )
    assert response.status_code == _CREATED, response.text
    return str(response.json()["data"]["email"])


# --- poprawki T5b ---


async def test_post_user_nickname_not_string_400(svc: httpx.AsyncClient, prefix: str) -> None:
    """Poprawka T5b(a): `nickname` inny niż string → 400, nie 500 (walidacja w routerze)."""
    response = await svc.post(
        f"{prefix}/api/users",
        json={"email": "ann@x.pl", "password": _PASSWORD, "nickname": 123},
    )
    assert response.status_code == _BAD_REQUEST
    assert response.json() == {"error": "nickname must be a string"}


@pytest.mark.parametrize("field", ["nickname", "is_active", "is_superuser"])
async def test_put_user_null_fields_400(svc: httpx.AsyncClient, prefix: str, field: str) -> None:
    """Poprawka T5b(b): jawne `null` w PUT → 400; pole nieobecne = brak zmiany."""
    await _create(svc, prefix, "ann@x.pl")
    response = await svc.put(f"{prefix}/api/users/{_ANN}", json={field: None})
    assert response.status_code == _BAD_REQUEST
    expected = "nickname must be a string" if field == "nickname" else f"{field} must be a boolean"
    assert response.json() == {"error": expected}
    empty = await svc.put(f"{prefix}/api/users/{_ANN}", json={})
    assert empty.status_code == _OK
    assert empty.json() == {"data": {"message": "no changes"}}


# --- AG-09, AG-10, AG-15…AG-17 ---


async def test_ag09_is_active_is_string(svc: httpx.AsyncClient, prefix: str) -> None:
    """AG-09: `is_active` to `"1"`/`"0"` (string); po deactivate `"0"` (K7 §9)."""
    created = await _create(svc, prefix, "ann@x.pl")
    assert created == "ann@x.pl"
    detail = (await svc.get(f"{prefix}/api/users/{_ANN}")).json()["data"]
    assert isinstance(detail["is_active"], str)
    assert detail["is_active"] == "1"

    deactivated = await svc.put(f"{prefix}/api/users/{_ANN}/deactivate")
    assert deactivated.status_code == _OK
    after = (await svc.get(f"{prefix}/api/users/{_ANN}")).json()["data"]
    assert after["is_active"] == "0"
    assert after["status"] == "0"
    listed = (await svc.get(f"{prefix}/api/users")).json()["data"]
    assert [item["is_active"] for item in listed if item["email"] == "ann@x.pl"] == ["0"]

    activated = await svc.put(f"{prefix}/api/users/{_ANN}/activate")
    assert activated.status_code == _OK
    assert (await svc.get(f"{prefix}/api/users/{_ANN}")).json()["data"]["is_active"] == "1"


async def test_ag10_create_date_parsable(svc: httpx.AsyncClient, prefix: str) -> None:
    """AG-10: `create_date` parsowalne przez `new Date()` (test w Node: `bun -e`).

    Wyrocznie mają `bun` (K7 §3), więc uruchamiamy `new Date(...).getTime()` i wymagamy
    liczby ≠ NaN. Bez `bun` (np. laptop) używamy `email.utils.parsedate_to_datetime` —
    ten sam format RFC 1123, bez zależności od Node.
    """
    await _create(svc, prefix, "ann@x.pl")
    create_date = (await svc.get(f"{prefix}/api/users/{_ANN}")).json()["data"]["create_date"]
    assert isinstance(create_date, str)
    if _BUN is not None:
        result = subprocess.run(  # noqa: S603, ASYNC221 — stały skrypt, krótki proces Node
            [_BUN, "-e", _BUN_JS, create_date],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        epoch = result.stdout.strip()
        assert epoch != "NaN"
        assert int(epoch) > 0
    else:
        assert parsedate_to_datetime(create_date) is not None


async def test_ag15_duplicate_and_missing_password(svc: httpx.AsyncClient, prefix: str) -> None:
    """AG-15: istniejący e-mail (case-insensitive) → 409; brak `password` → 400 (K7 §9)."""
    await _create(svc, prefix, "ann@x.pl")
    duplicate = await svc.post(
        f"{prefix}/api/users", json={"email": "ANN@x.pl", "password": _PASSWORD}
    )
    assert duplicate.status_code == _CONFLICT
    assert duplicate.json() == {"error": "User already exists"}
    for body in ({"email": "missing@x.pl"}, {"password": _PASSWORD}):
        response = await svc.post(f"{prefix}/api/users", json=body)
        assert response.status_code == _BAD_REQUEST
        assert response.json() == {"error": "email and password are required"}


async def test_ag17_case_insensitive_users_keys(svc: httpx.AsyncClient, prefix: str) -> None:
    """AG-17: users/keys case-insensitive; e-mail z `+` działa w ścieżce (K7 §1.4)."""
    assert await _create(svc, prefix, "Ann@X.pl") == "ann@x.pl"
    got = await svc.get(f"{prefix}/api/users/ANN@x.PL")
    assert got.status_code == _OK
    assert got.json()["data"]["email"] == "ann@x.pl"
    keys = await svc.get(f"{prefix}/api/keys/ann@X.pl")
    assert keys.status_code == _OK
    assert keys.json() == {"data": []}

    assert await _create(svc, prefix, "a+b@x.pl") == "a+b@x.pl"
    plus_user = await svc.get(f"{prefix}/api/users/{_ANN_PLUS}")
    assert plus_user.status_code == _OK
    assert plus_user.json()["data"]["email"] == "a+b@x.pl"
    plus_keys = await svc.get(f"{prefix}/api/keys/{_ANN_PLUS}")
    assert plus_keys.status_code == _OK
    assert plus_keys.json() == {"data": []}


# --- komunikaty, hasło i audyt ---


async def test_put_user_messages(svc: httpx.AsyncClient, prefix: str) -> None:
    """C8: komunikat z fragmentów zmian; brak zmian → `no changes`."""
    await _create(svc, prefix, "ann@x.pl")
    changed = await svc.put(
        f"{prefix}/api/users/{_ANN}", json={"nickname": "Ann", "is_active": False}
    )
    assert changed.status_code == _OK
    assert changed.json() == {"data": {"message": "nickname updated, is_active set to off"}}
    same = await svc.put(f"{prefix}/api/users/{_ANN}", json={})
    assert same.status_code == _OK
    assert same.json() == {"data": {"message": "no changes"}}


async def test_password_change_works(svc: httpx.AsyncClient, prefix: str) -> None:
    """`PUT …/password`: nowe hasło loguje, stare nie (K7 §1.9, 07 §6.2)."""
    await _create(svc, prefix, "ann@x.pl")
    changed = await svc.put(
        f"{prefix}/api/users/{_ANN}/password", json={"new_password": _NEW_PASSWORD}
    )
    assert changed.status_code == _OK
    assert changed.json() == {"data": {"message": "Password changed"}}

    login = await svc.post(
        "/api/v1/auth/login", json={"email": "ann@x.pl", "password": _NEW_PASSWORD}
    )
    assert login.json()["code"] == 0
    assert login.json()["data"]["access_token"]
    stale = await svc.post("/api/v1/auth/login", json={"email": "ann@x.pl", "password": _PASSWORD})
    assert stale.json()["code"] != 0
    assert stale.json()["data"] is False


async def test_audit_rows_for_user_and_key_mutations(
    svc: httpx.AsyncClient, prefix: str, sm: async_sessionmaker[AsyncSession]
) -> None:
    """K7 §1.10: mutacje SVC zostawiają wpis audytu bez hasła i tokenu; klucz → id klucza (§5)."""
    await _create(svc, prefix, "boss@x.pl", role="admin")  # cel transferu przy usunięciu
    await _create(svc, prefix, "ann@x.pl")
    await svc.put(f"{prefix}/api/users/{_ANN}", json={"nickname": "Ann"})
    await svc.put(f"{prefix}/api/users/{_ANN}/password", json={"new_password": _NEW_PASSWORD})
    await svc.put(f"{prefix}/api/users/{_ANN}/deactivate")
    await svc.put(f"{prefix}/api/users/{_ANN}/activate")
    token = (await svc.post(f"{prefix}/api/keys/{_ANN}")).json()["data"]["token"]
    await svc.request("DELETE", f"{prefix}/api/keys/{_ANN}/{token}")
    removed = await svc.request("DELETE", f"{prefix}/api/users/{_ANN}")
    assert removed.status_code == _OK

    actions = [
        "user_created",
        "user_updated",
        "user_password_set",
        "user_deactivated",
        "user_activated",
        "api_key_created",
        "api_key_deleted",
        "user_deleted",
    ]
    rows = {action: await _audit(sm, action) for action in actions}
    assert all(rows[action] for action in actions)
    serialized = json.dumps(
        [row.details for action in actions for row in rows[action]], ensure_ascii=False
    )
    assert _PASSWORD not in serialized
    assert _NEW_PASSWORD not in serialized
    assert token not in serialized
    # K7 §5 p. 2: audyt unieważnienia klucza celuje w id klucza (tworzenie już tak robi).
    deleted_key = rows["api_key_deleted"][-1]
    assert deleted_key.target_type == "api_key"
    assert deleted_key.target_id == rows["api_key_created"][-1].target_id


async def test_ag16_delete_user_removes_access_rows(
    svc: httpx.AsyncClient, prefix: str, sm: async_sessionmaker[AsyncSession], seed_chat: SeedChat
) -> None:
    """AG-16: DELETE konta przenosi zasoby do admina, usuwa granty i klucze (K7 §1.9)."""
    await _create(svc, prefix, "boss@x.pl", role="admin")
    await _create(svc, prefix, "ann@x.pl")
    ann_id = await _user_id(sm, "ann@x.pl")
    admin_id = await _user_id(sm, "boss@x.pl")
    ann_chat = await seed_chat(ann_id)
    admin_chat = await seed_chat(admin_id)
    granted = await svc.put(
        f"{prefix}/api/access", json={"email": "ann@x.pl", "dialog_ids": [admin_chat]}
    )
    assert granted.status_code == _OK
    await svc.post(f"{prefix}/api/keys/{_ANN}")
    assert (
        await _count(
            sm, "SELECT COUNT(*) FROM assistant_access WHERE email = :e", {"e": "ann@x.pl"}
        )
        == 1
    )
    assert await _count(sm, "SELECT COUNT(*) FROM api_keys WHERE user_id = :u", {"u": ann_id}) == 1

    removed = await svc.request("DELETE", f"{prefix}/api/users/{_ANN}")
    assert removed.status_code == _OK
    assert removed.json() == {"data": {"message": "User deleted"}}

    missing = await svc.get(f"{prefix}/api/users/{_ANN}")
    assert missing.status_code == _NOT_FOUND
    assert (
        await _count(
            sm, "SELECT COUNT(*) FROM assistant_access WHERE email = :e", {"e": "ann@x.pl"}
        )
        == 0
    )
    assert await _count(sm, "SELECT COUNT(*) FROM api_keys WHERE user_id = :u", {"u": ann_id}) == 0
    moved = await _count(
        sm,
        "SELECT COUNT(*) FROM chats WHERE id = :c AND tenant_id = :t",
        {"c": ann_chat, "t": admin_id},
    )
    assert moved == 1


async def test_ag16_last_superuser_400(svc: httpx.AsyncClient, prefix: str) -> None:
    """AG-16/K7 §1.9: usunięcie ostatniego aktywnego admina → 400 (nie 500)."""
    await _create(svc, prefix, "boss@x.pl", role="admin")
    response = await svc.request("DELETE", f"{prefix}/api/users/{_ADMIN}")
    assert response.status_code == _BAD_REQUEST
    assert response.json() == {
        "error": "The last active administrator cannot be deactivated or demoted."
    }
    assert (await svc.get(f"{prefix}/api/users/{_ADMIN}")).status_code == _OK
