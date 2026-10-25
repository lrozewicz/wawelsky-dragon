"""Trasy kluczy API WD ``/api/wd/v1/users/{id}/api-keys*`` (brief T3, kontrakt §2, §3, §4, §7).

Sprawdzamy: kształt odpowiedzi (``ApiKey`` **bez** pola ``token``, ``ApiKeyCreated`` z tokenem),
brak pełnego tokenu w treści listy i w ``details`` audytu, audyt ``api_key_deleted`` z ``target_id``
równym **id klucza** (K7 §5 p. 2), 404 dla nieznanego użytkownika i cudzego klucza, 400 walidacji
(``max_length`` nazwy, ``expires_at``: bez strefy, nieparsowalne, z przeszłości), termin wygaśnięcia
w odpowiedzi i w audycie, klucz wygasły nadal na liście (K14 §3), 401/403 straży administratora
oraz to, że klucz z WD działa jako Bearer w ``/api/v1``.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.uow import transaction
from tests.contract.wd.admin_support import AuditRows, MakeUser

pytestmark = pytest.mark.contract

OK = 200
CREATED = 201
NO_CONTENT = 204
BAD_REQUEST = 400
UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404

BASE = "/api/wd/v1/users"
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

API_KEY_KEYS = frozenset({"id", "name", "prefix", "created_at", "last_used_at", "expires_at"})
API_KEY_CREATED_KEYS = API_KEY_KEYS | {"token"}
LONG_NAME = "n" * 256

# Terminy wygaśnięcia z K14 §3: ISO ze strefą w przyszłości oraz 1 000 000 000 000 ms (2001-09-09).
FUTURE_ISO = "2030-01-01T00:00:00Z"
FUTURE_EXPIRES_AT = "2030-01-01T00:00:00.000Z"
PAST_MS = 1_000_000_000_000
PAST_EXPIRES_AT = "2001-09-09T01:46:40.000Z"
# Bez strefy, sama data, bez sensu i w przeszłości — wszystkie odrzucane (K14 §3 p. 1).
INVALID_EXPIRES_AT = ("2030-01-01T00:00:00", "2030-01-01", "nie-data", "2020-01-01T00:00:00Z")

_KEYS_PATH = "/api/wd/v1/users/{user_id}/api-keys"
_KEY_PATH = "/api/wd/v1/users/{user_id}/api-keys/{key_id}"


def _create_body(name: str | None = "ci", expires_at: str | None = None) -> dict[str, object]:
    """Ciało POST: nazwa klucza i opcjonalny termin wygaśnięcia; puste ciało = brak obu (§7)."""
    body: dict[str, object] = {}
    if name is not None:
        body["name"] = name
    if expires_at is not None:
        body["expires_at"] = expires_at
    return body


async def _create_key(
    admin: httpx.AsyncClient, user_id: str, name: str | None = "ci", expires_at: str | None = None
) -> dict[str, Any]:
    """Tworzy klucz klientem administratora i zwraca ``data`` z odpowiedzi 201."""
    response = await admin.post(
        _KEYS_PATH.format(user_id=user_id), json=_create_body(name, expires_at)
    )
    assert response.status_code == CREATED, response.text
    return response.json()["data"]


async def test_create_returns_token_once_and_list_hides_it(
    admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """POST zwraca pełny token, GET listy już nie; token nie występuje w treści listy (§7)."""
    user = await make_user("key-owner@example.com")

    empty = await admin.get(_KEYS_PATH.format(user_id=user.id))
    assert empty.status_code == OK, empty.text
    assert empty.json() == {"data": {"items": []}}

    created = await _create_key(admin, user.id)
    token = created["token"]
    assert set(created) == API_KEY_CREATED_KEYS
    assert created["name"] == "ci"
    assert created["prefix"] == token[:16]
    assert token.startswith(created["prefix"])
    assert ISO_RE.match(created["created_at"])
    assert created["last_used_at"] is None
    assert created["expires_at"] is None

    listed = await admin.get(_KEYS_PATH.format(user_id=user.id))
    assert listed.status_code == OK, listed.text
    (item,) = listed.json()["data"]["items"]
    assert set(item) == API_KEY_KEYS
    assert item["id"] == created["id"]
    assert item["prefix"] == created["prefix"]
    assert token not in listed.text


async def test_delete_revokes_key_and_audits_the_key_id(
    admin: httpx.AsyncClient, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """DELETE unieważnia klucz, drugie DELETE → 404, audyt wskazuje id klucza (K7 §5 p. 2)."""
    user = await make_user("key-delete@example.com")
    created = await _create_key(admin, user.id)

    deleted = await admin.delete(_KEY_PATH.format(user_id=user.id, key_id=created["id"]))
    assert deleted.status_code == NO_CONTENT, deleted.text

    listed = await admin.get(_KEYS_PATH.format(user_id=user.id))
    assert listed.json()["data"]["items"] == []

    again = await admin.delete(_KEY_PATH.format(user_id=user.id, key_id=created["id"]))
    assert again.status_code == NOT_FOUND, again.text
    assert again.json()["error"]["code"] == "not_found"

    (entry,) = await audit_rows("api_key_deleted")
    assert entry.target_type == "api_key"
    assert entry.target_id == created["id"]
    assert entry.details == {"user_id": user.id}


async def test_delete_key_of_another_user_is_not_found(
    admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Klucz innego użytkownika pod nie swoim ``user_id`` → 404 bez unieważnienia (§7)."""
    owner = await make_user("key-owner-2@example.com")
    stranger = await make_user("key-stranger@example.com")
    created = await _create_key(admin, owner.id)

    response = await admin.delete(_KEY_PATH.format(user_id=stranger.id, key_id=created["id"]))
    assert response.status_code == NOT_FOUND, response.text

    listed = await admin.get(_KEYS_PATH.format(user_id=owner.id))
    assert [item["id"] for item in listed.json()["data"]["items"]] == [created["id"]]


async def test_unknown_user_id_is_not_found_on_every_route(
    admin: httpx.AsyncClient,
) -> None:
    """Nieznany ``user_id`` → 404 ``not_found`` na każdej z trzech tras (kontrakt §0 p. 4)."""
    paths = [
        ("GET", _KEYS_PATH.format(user_id="nope")),
        ("POST", _KEYS_PATH.format(user_id="nope")),
        ("DELETE", _KEY_PATH.format(user_id="nope", key_id="k1")),
    ]
    for method, path in paths:
        response = await admin.request(method, path, json={})
        assert response.status_code == NOT_FOUND, (method, path, response.text)
        assert response.json()["error"]["code"] == "not_found"


async def test_too_long_name_fails_validation_with_400(
    admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Nazwa dłuższa niż 255 znaków → 400 ``validation_failed`` (nigdy 422; kontrakt §0 p. 3)."""
    user = await make_user("key-long-name@example.com")

    response = await admin.post(_KEYS_PATH.format(user_id=user.id), json=_create_body(LONG_NAME))
    assert response.status_code == BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "validation_failed"


async def test_missing_header_is_401_and_member_is_403_on_every_route(
    anon: httpx.AsyncClient, member: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Bez nagłówka → 401, zwykły użytkownik → 403 na każdej trasie (kontrakt §0 p. 2)."""
    admin_user = await make_user("key-guard@example.com")
    routes = [
        ("GET", _KEYS_PATH.format(user_id=admin_user.id), None),
        ("POST", _KEYS_PATH.format(user_id=admin_user.id), _create_body()),
        (
            "DELETE",
            _KEY_PATH.format(user_id=admin_user.id, key_id="k1"),
            None,
        ),
    ]
    for method, path, body in routes:
        unauth = await anon.request(method, path, json=body)
        assert unauth.status_code == UNAUTHORIZED, (method, path, unauth.text)
        forbidden = await member.request(method, path, json=body)
        assert forbidden.status_code == FORBIDDEN, (method, path, forbidden.text)


async def test_created_key_authenticates_as_bearer_in_v1(
    app: FastAPI, admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Klucz z WD działa jako Bearer w ``GET /api/v1/users/me`` → ``code == 0`` (§7)."""
    user = await make_user("key-bearer@example.com")
    token = (await _create_key(admin, user.id))["token"]

    with_token = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )
    async with with_token:
        response = await with_token.get("/api/v1/users/me")

    assert response.status_code == OK, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["email"] == "key-bearer@example.com"


async def test_audit_details_never_contain_the_full_token(
    admin: httpx.AsyncClient, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """Ani ``api_key_created``, ani ``api_key_deleted`` nie zapisują pełnego tokenu (§4)."""
    user = await make_user("key-audit@example.com")
    created = await _create_key(admin, user.id)
    deleted = await admin.delete(_KEY_PATH.format(user_id=user.id, key_id=created["id"]))
    assert deleted.status_code == NO_CONTENT, deleted.text
    token = created["token"]

    rows = await audit_rows("api_key_created") + await audit_rows("api_key_deleted")
    assert rows
    assert all(token not in str(row.details) for row in rows)


async def test_expires_at_from_the_future_is_returned_in_iso_and_listed(
    admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Termin z przyszłości → 201 i to samo ``expires_at`` (ISO UTC) w odpowiedzi i na liście."""
    user = await make_user("key-expires@example.com")

    created = await _create_key(admin, user.id, "z-terminem", FUTURE_ISO)
    assert created["expires_at"] == FUTURE_EXPIRES_AT
    assert ISO_RE.match(created["expires_at"])

    (item,) = (await admin.get(_KEYS_PATH.format(user_id=user.id))).json()["data"]["items"]
    assert item["id"] == created["id"]
    assert item["expires_at"] == FUTURE_EXPIRES_AT


async def test_invalid_expires_at_is_400_and_no_key_is_created(
    admin: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Bez strefy, sama data, nieparsowalne i z przeszłości → 400 ``validation_failed`` (§3)."""
    user = await make_user("key-bad-expires@example.com")

    for value in INVALID_EXPIRES_AT:
        response = await admin.post(
            _KEYS_PATH.format(user_id=user.id), json=_create_body("zły", value)
        )
        assert response.status_code == BAD_REQUEST, (value, response.text)
        assert response.json()["error"]["code"] == "validation_failed", value

    listed = await admin.get(_KEYS_PATH.format(user_id=user.id))
    assert listed.json()["data"]["items"] == []


async def test_list_returns_expired_key_with_its_past_term(
    admin: httpx.AsyncClient, make_user: MakeUser, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Klucz wygasły zostaje na liście razem z terminem z przeszłości (K14 §3 p. 3)."""
    user = await make_user("key-expired-list@example.com")
    created = await _create_key(admin, user.id, "wygasły", FUTURE_ISO)

    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE api_keys SET expires_at = :expires_at WHERE id = :id"),
            {"expires_at": PAST_MS, "id": created["id"]},
        )

    (item,) = (await admin.get(_KEYS_PATH.format(user_id=user.id))).json()["data"]["items"]
    assert item["id"] == created["id"]
    assert item["expires_at"] == PAST_EXPIRES_AT


async def test_audit_created_details_carry_expires_at(
    admin: httpx.AsyncClient, make_user: MakeUser, audit_rows: AuditRows
) -> None:
    """``api_key_created`` zapisuje ``expires_at`` z żądania (także ``null``), bez tokenu (§3)."""
    user = await make_user("key-audit-expires@example.com")
    with_term = await _create_key(admin, user.id, "z-terminem", FUTURE_ISO)
    without_term = await _create_key(admin, user.id, "bez-terminu")

    assert [row.details for row in await audit_rows("api_key_created")] == [
        {"user_id": user.id, "prefix": with_term["prefix"], "expires_at": FUTURE_ISO},
        {"user_id": user.id, "prefix": without_term["prefix"], "expires_at": None},
    ]
