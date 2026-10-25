"""Trasy users WD ``/api/wd/v1/users*``: lista, zakładanie, odczyt, zmiana (kontrakt E3-6a §2, §4).

Asercje na kopercie WD (``{"data": …}`` / ``{"error":{"code",…}}``), dokładnym zbiorze kluczy
``User``, braku kont serwisowych i pól wrażliwych w odpowiedziach oraz wpisach audytu
(``actor_label`` administratora, ``details`` bez haseł).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from app.core.container import Container
from app.db.repositories.users import UserRow
from tests.contract.wd.admin_support import ADMIN_EMAIL, MEMBER_EMAIL, AuditRows, MakeUser

pytestmark = pytest.mark.contract

OK = 200
CREATED = 201
BAD_REQUEST = 400
UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404
CONFLICT = 409

BASE = "/api/wd/v1/users"
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

USER_KEYS = frozenset(
    {
        "id",
        "email",
        "nickname",
        "auth_source",
        "is_superuser",
        "is_active",
        "language",
        "timezone",
        "avatar",
        "last_login_at",
        "created_at",
        "updated_at",
    }
)

# (metoda, ścieżka) każdej trasy users — dla testów 401/403 (kontrakt §0 p. 12).
WD_ROUTES = [
    ("get", BASE),
    ("post", BASE),
    ("get", f"{BASE}/unknown-id"),
    ("patch", f"{BASE}/unknown-id"),
    ("delete", f"{BASE}/unknown-id"),
    ("post", f"{BASE}/unknown-id/password"),
    ("post", f"{BASE}/unknown-id/activate"),
    ("post", f"{BASE}/unknown-id/deactivate"),
]

MakeServiceUser = Callable[[str], Awaitable[UserRow]]


def wd_error(response: httpx.Response) -> dict[str, Any]:
    """Koperta błędu WD z odpowiedzi (kontrakt §0 p. 1)."""
    body: dict[str, Any] = response.json()
    return body["error"]


async def _id_of(admin: httpx.AsyncClient, email: str) -> str:
    """Identyfikator jedynego konta o podanym e-mailu (filtr ``email``, kontrakt §0 p. 7)."""
    response = await admin.get(BASE, params={"email": email})
    assert response.status_code == OK, response.text
    items = response.json()["data"]["items"]
    assert len(items) == 1, items
    return str(items[0]["id"])


@pytest.fixture
def make_service_user(container: Container) -> MakeServiceUser:
    """Helper: konta serwisowe (``is_service=1``) nie trafiają na listę (kontrakt §0 p. 11)."""

    async def _make(email: str) -> UserRow:
        assert container.users is not None
        return await container.users.create(email=email, password=None, is_service=True)

    return _make


async def test_list_hides_service_accounts(
    admin: httpx.AsyncClient,
    member: httpx.AsyncClient,
    make_service_user: MakeServiceUser,
) -> None:
    """Admin + zwykły użytkownik widoczni, konto serwisowe pominięte, bez ``password_hash``."""
    service = await make_service_user("wd-service@example.com")

    response = await admin.get(BASE)

    assert response.status_code == OK, response.text
    body = response.json()
    assert set(body) == {"data"}
    data = body["data"]
    assert set(data) == {"items", "total", "page", "page_size"}
    assert (data["total"], data["page"], data["page_size"]) == (2, 1, 20)
    assert {item["email"] for item in data["items"]} == {ADMIN_EMAIL, MEMBER_EMAIL}
    assert service.id not in {item["id"] for item in data["items"]}
    assert all(set(item) == USER_KEYS for item in data["items"])
    assert "password_hash" not in response.text


async def test_list_filters_q_and_email(admin: httpx.AsyncClient, make_user: MakeUser) -> None:
    """``q`` szuka po e-mailu i nazwie, ``email`` dokładnie; znaki LIKE są dosłowne."""
    jan = await make_user("jan@example.com")
    await make_user("anna@example.com")

    by_q = await admin.get(BASE, params={"q": "jan"})
    assert by_q.status_code == OK, by_q.text
    assert by_q.json()["data"]["total"] == 1
    assert [item["id"] for item in by_q.json()["data"]["items"]] == [jan.id]

    by_email = await admin.get(BASE, params={"email": "JAN@example.com"})
    assert by_email.status_code == OK, by_email.text
    assert [item["email"] for item in by_email.json()["data"]["items"]] == ["jan@example.com"]

    percent = await admin.get(BASE, params={"q": "%"})
    underscore = await admin.get(BASE, params={"q": "_"})
    assert percent.json()["data"]["total"] == 0
    assert underscore.json()["data"]["total"] == 0


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


async def test_create_returns_user_and_audits(
    admin: httpx.AsyncClient, audit_rows: AuditRows
) -> None:
    """201 z pełnym kontem (e-mail lowercase), wpis ``user_created`` aktora-administratora."""
    response = await admin.post(
        BASE, json={"email": "Nowy@Example.com", "password": "Str0ng-pass!"}
    )

    assert response.status_code == CREATED, response.text
    body = response.json()
    assert set(body) == {"data"}
    data = body["data"]
    assert set(data) == USER_KEYS
    assert data["email"] == "nowy@example.com"
    assert data["nickname"] == "nowy"
    assert data["auth_source"] == "local"
    assert data["is_superuser"] is False
    assert data["is_active"] is True
    assert data["last_login_at"] is None
    assert ISO_RE.fullmatch(str(data["created_at"])) is not None
    assert ISO_RE.fullmatch(str(data["updated_at"])) is not None
    assert "Str0ng-pass!" not in response.text

    rows = await audit_rows("user_created")
    assert len(rows) == 1
    assert rows[0].actor_label == ADMIN_EMAIL
    assert rows[0].target_type == "user"
    assert rows[0].target_id == data["id"]
    assert rows[0].details == {"email": "nowy@example.com"}


async def test_create_rejects_taken_email(admin: httpx.AsyncClient, make_user: MakeUser) -> None:
    """Drugi POST na ten sam e-mail → 409 ``conflict`` (usługa ``create``)."""
    await make_user("taken@example.com")

    response = await admin.post(BASE, json={"email": "Taken@Example.com"})

    assert response.status_code == CONFLICT, response.text
    assert wd_error(response)["code"] == "conflict"


async def test_create_without_email_does_not_echo_password(admin: httpx.AsyncClient) -> None:
    """Brak ``email`` przy podanym ``password`` → 400, a hasło nie występuje w treści (K3 §5)."""
    response = await admin.post(BASE, json={"password": "Str0ng-pass!"})

    assert response.status_code == BAD_REQUEST, response.text
    assert wd_error(response)["code"] == "validation_failed"
    assert "Str0ng-pass!" not in response.text


async def test_create_rejects_weak_password(admin: httpx.AsyncClient) -> None:
    """Za krótkie hasło odrzuca usługa (``validate_new_password``) → 400 (kontrakt §4)."""
    response = await admin.post(BASE, json={"email": "weak@example.com", "password": "short"})

    assert response.status_code == BAD_REQUEST, response.text
    assert wd_error(response)["code"] == "validation_failed"


async def test_get_returns_user_and_not_found(
    admin: httpx.AsyncClient, make_user: MakeUser, make_service_user: MakeServiceUser
) -> None:
    """Konto po ``user_id`` (także serwisowe), nieznany identyfikator → 404 ``not_found``."""
    row = await make_user("get-user@example.com")
    service = await make_service_user("get-service@example.com")

    found = await admin.get(f"{BASE}/{row.id}")
    assert found.status_code == OK, found.text
    assert found.json()["data"]["email"] == "get-user@example.com"
    assert set(found.json()["data"]) == USER_KEYS

    service_found = await admin.get(f"{BASE}/{service.id}")
    assert service_found.status_code == OK, service_found.text
    assert service_found.json()["data"]["email"] == "get-service@example.com"

    missing = await admin.get(f"{BASE}/unknown-id")
    assert missing.status_code == NOT_FOUND
    assert wd_error(missing)["code"] == "not_found"


async def test_patch_changes_nickname_and_audits(
    admin: httpx.AsyncClient, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """``PATCH`` zmienia nazwę i zapisuje świeży wiersz; audyt ``user_updated`` z ``changes``."""
    row = await make_user("patch@example.com", password=None)

    response = await admin.patch(f"{BASE}/{row.id}", json={"nickname": "Nowa Nazwa"})

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert set(data) == USER_KEYS
    assert data["nickname"] == "Nowa Nazwa"
    assert data["email"] == "patch@example.com"

    rows = await audit_rows("user_updated")
    assert len(rows) == 1
    assert rows[0].target_id == row.id
    assert rows[0].details == {"email": "patch@example.com", "changes": ["nickname"]}


async def test_patch_empty_body_changes_nothing_and_audits_nothing(
    admin: httpx.AsyncClient, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """Puste ciało ``{}`` → 200 bez zmian, bez wpisu audytu (kontrakt §2)."""
    row = await make_user("noop@example.com")
    before = (await admin.get(f"{BASE}/{row.id}")).json()["data"]

    response = await admin.patch(f"{BASE}/{row.id}", json={})

    assert response.status_code == OK, response.text
    assert response.json()["data"] == before
    assert await audit_rows("user_updated") == []


async def test_patch_demoting_sole_admin_is_conflict(admin: httpx.AsyncClient) -> None:
    """Odebranie roli jedynemu adminowi → 409 ``operation_not_allowed`` (straż w usłudze)."""
    admin_id = await _id_of(admin, ADMIN_EMAIL)

    response = await admin.patch(f"{BASE}/{admin_id}", json={"is_superuser": False})

    assert response.status_code == CONFLICT, response.text
    assert wd_error(response)["code"] == "operation_not_allowed"


@pytest.mark.parametrize(("method", "path"), WD_ROUTES)
async def test_routes_require_authentication(
    anon: httpx.AsyncClient, method: str, path: str
) -> None:
    """Bez nagłówka ``Authorization`` każda trasa → 401 ``unauthorized`` (przed walidacją)."""
    response = await anon.request(method, path, json={})

    assert response.status_code == UNAUTHORIZED, response.text
    assert wd_error(response)["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path"), WD_ROUTES)
async def test_routes_reject_non_admin(member: httpx.AsyncClient, method: str, path: str) -> None:
    """Nie-superuser na każdej trasie → 403 ``permission_denied`` (polityka, kontrakt §0 p. 2)."""
    response = await member.request(method, path, json={})

    assert response.status_code == FORBIDDEN, response.text
    assert wd_error(response)["code"] == "permission_denied"
