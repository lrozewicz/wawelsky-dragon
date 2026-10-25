"""Przepływ auth na MariaDB: login → me → refresh → reuse → logout, profil, klucze (07 §12 p. 3)."""

from collections.abc import Iterator
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.main import create_app

pytestmark = pytest.mark.db

EMAIL = "jan@x.pl"
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
NEW_PASSWORD = "Nowe-haslo-1"  # noqa: S105 — celowa atrapa hasła w teście
ACCESS_TTL_S = 900  # access_token_ttl_min=15
# Stałe statusów HTTP (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_OK = 200
_UNAUTHORIZED = 401


@pytest.fixture
def settings(auth_settings: Settings) -> Settings:
    """Rejestracja włączona — użytkownika zakłada trasa POST /users (bez mieszania pętli)."""
    return auth_settings.model_copy(update={"register_enabled": True})


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


def register_jan(client: TestClient) -> dict[str, object]:
    """Użytkownik jan@x.pl przez trasę rejestracji; zwraca body odpowiedzi."""
    response = client.post(
        "/api/v1/users", json={"nickname": "jan", "email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    return body


def login_headers(client: TestClient) -> dict[str, str]:
    """Login jan@x.pl → nagłówek Authorization z access tokenu."""
    response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.json()["code"] == 0
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def test_login_sets_cookie_headers_and_me_works(client: TestClient) -> None:
    """Login: cookie wd_refresh z flagami B3; /users/me z Bearer i surowym legacy tokenem."""
    register_jan(client)
    response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    cookie = response.headers["set-cookie"]
    assert "wd_refresh=" in cookie
    lower = cookie.lower()
    # env=test → bez Secure (C1); flagi z B3 bez zmian.
    attrs = {part.strip() for part in lower.split(";")}
    assert "httponly" in attrs and "samesite=strict" in attrs
    assert "secure" not in attrs
    assert "path=/api/v1/auth" in attrs

    bearer = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {body['data']['access_token']}"},
    )
    assert bearer.json()["code"] == 0
    assert bearer.json()["data"]["email"] == EMAIL

    raw = client.get(
        "/api/v1/users/me", headers={"Authorization": response.headers["Authorization"]}
    )
    assert raw.json()["code"] == 0


def test_refresh_rotation_and_reuse_invalidates_family(client: TestClient) -> None:
    """Refresh rotuje cookie; reuse starego R1 unieważnia rodzinę — R2 też odrzucone."""
    register_jan(client)
    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    first = login.cookies["wd_refresh"]

    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == _OK
    body = refreshed.json()
    assert body["code"] == 0
    assert body["data"]["expires_in"] == ACCESS_TTL_S
    assert body["data"]["access_token"] != login.json()["data"]["access_token"]
    second = refreshed.cookies["wd_refresh"]
    assert second != first

    client.cookies.clear()
    reuse = client.post("/api/v1/auth/refresh", headers={"Cookie": f"wd_refresh={first}"})
    assert reuse.status_code == _UNAUTHORIZED
    after_reuse = client.post("/api/v1/auth/refresh", headers={"Cookie": f"wd_refresh={second}"})
    assert after_reuse.status_code == _UNAUTHORIZED


def test_logout_all_invalidates_access_and_legacy(client: TestClient) -> None:
    """logout?all=true: data true; po nim stary access i legacy → 401 (token_version)."""
    register_jan(client)
    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    data = login.json()["data"]
    bearer = {"Authorization": f"Bearer {data['access_token']}"}
    legacy = {"Authorization": login.headers["Authorization"]}

    out = client.post("/api/v1/auth/logout?all=true", headers=bearer)
    assert out.status_code == _OK
    assert out.json() == {"code": 0, "message": "success", "data": True}

    assert client.get("/api/v1/users/me", headers=bearer).status_code == _UNAUTHORIZED
    assert client.get("/api/v1/users/me", headers=legacy).status_code == _UNAUTHORIZED


def test_logout_single_kills_refresh_keeps_access(client: TestClient) -> None:
    """logout bez all: kasuje cookie (Max-Age=0), refresh tym cookie → 401, access działa."""
    register_jan(client)
    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    data = login.json()["data"]
    bearer = {"Authorization": f"Bearer {data['access_token']}"}

    out = client.post("/api/v1/auth/logout", headers=bearer)
    assert out.json()["data"] is True
    cleared = out.headers["set-cookie"].lower()
    assert "wd_refresh=" in cleared and "max-age=0" in cleared

    client.cookies.clear()
    dead = client.post(
        "/api/v1/auth/refresh", headers={"Cookie": f"wd_refresh={login.cookies['wd_refresh']}"}
    )
    assert dead.status_code == _UNAUTHORIZED
    alive = client.get("/api/v1/users/me", headers=bearer)
    assert alive.json()["code"] == 0


def test_patch_profile_updates_fields(client: TestClient) -> None:
    """PATCH /users/me zmienia nickname i language; GET /me to potwierdza."""
    register_jan(client)
    headers = login_headers(client)
    patched = client.patch(
        "/api/v1/users/me", json={"nickname": "Janek", "language": "English"}, headers=headers
    )
    assert patched.json() == {"code": 0, "message": "success", "data": True}
    me = client.get("/api/v1/users/me", headers=headers)
    assert me.json()["data"]["nickname"] == "Janek"


def test_change_password_rejects_wrong_old_then_rotates(client: TestClient) -> None:
    """Złe stare hasło → code 109 „Password error!”; poprawna zmiana → login nowym hasłem,
    stary access → 401 (token_version)."""
    register_jan(client)
    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    wrong = client.patch(
        "/api/v1/users/me",
        json={"password": "zle", "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert wrong.status_code == _OK
    assert wrong.json()["code"] == RetCode.AUTHENTICATION_ERROR
    assert wrong.json()["message"] == "Password error!"

    ok = client.patch(
        "/api/v1/users/me",
        json={"password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert ok.json()["data"] is True

    relogin = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD})
    assert relogin.json()["code"] == 0
    assert client.get("/api/v1/users/me", headers=headers).status_code == _UNAUTHORIZED


def test_api_key_lifecycle_and_bearer_auth(client: TestClient) -> None:
    """POST/GET/DELETE /system/tokens: pełny token, Bearer kluczem, po DELETE lista pusta."""
    register_jan(client)
    headers = login_headers(client)

    created = client.post("/api/v1/system/tokens", headers=headers)
    assert created.status_code == _OK
    token = created.json()["data"]["token"]
    assert token.startswith("ragflow-")

    listed = client.get("/api/v1/system/tokens", headers=headers)
    assert [row["token"] for row in listed.json()["data"]] == [token]

    used = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert used.json()["code"] == 0

    removed = client.delete(f"/api/v1/system/tokens/{quote(token, safe='')}", headers=headers)
    assert removed.json() == {"code": 0, "message": "success", "data": True}

    empty = client.get("/api/v1/system/tokens", headers=headers)
    assert empty.json()["data"] == []


def test_api_key_name_round_trip(client: TestClient) -> None:
    """Nazwa klucza (K20 §1): echo po POST, obecna na liście, przycięta, pusta → None."""
    register_jan(client)
    headers = login_headers(client)

    named = client.post(
        "/api/v1/system/tokens", params={"name": "  Klucz produkcyjny  "}, headers=headers
    )
    assert named.json()["data"]["name"] == "Klucz produkcyjny"

    unnamed = client.post("/api/v1/system/tokens", headers=headers)
    assert unnamed.json()["data"]["name"] is None

    rows = client.get("/api/v1/system/tokens", headers=headers).json()["data"]
    by_token = {row["token"]: row["name"] for row in rows}
    assert by_token[named.json()["data"]["token"]] == "Klucz produkcyjny"
    assert by_token[unnamed.json()["data"]["token"]] is None


def test_api_key_name_length_limit(client: TestClient) -> None:
    """Nazwa klucza po strip() (K21 §5 p. 1): >128 → ValidationFailed (code 101), 128 → sukces."""
    register_jan(client)
    headers = login_headers(client)

    before = client.get("/api/v1/system/tokens", headers=headers).json()["data"]
    rejected = client.post("/api/v1/system/tokens", params={"name": "a" * 129}, headers=headers)
    assert rejected.status_code == _OK
    assert rejected.json()["code"] == RetCode.ARGUMENT_ERROR
    assert rejected.json()["message"] == "Token name must be at most 128 characters."
    after = client.get("/api/v1/system/tokens", headers=headers).json()["data"]
    assert [row["token"] for row in after] == [row["token"] for row in before]

    exactly = client.post("/api/v1/system/tokens", params={"name": "a" * 128}, headers=headers)
    assert exactly.json()["code"] == 0
    assert exactly.json()["data"]["name"] == "a" * 128

    padded = client.post(
        "/api/v1/system/tokens", params={"name": " " * 129 + "a" * 128}, headers=headers
    )
    assert padded.json()["code"] == 0
    assert padded.json()["data"]["name"] == "a" * 128
