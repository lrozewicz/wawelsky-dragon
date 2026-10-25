"""Kontrakt API auth/users/system vs upstream v0.27.2 (07 §12 p. 5-6, brief T5)."""

import asyncio
import re
from collections.abc import Iterator
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock
from app.db.engine import make_engine, make_sessionmaker
from app.main import create_app
from app.services.users import UserService

pytestmark = pytest.mark.contract

# Koperta 401 przestrzeni ragflow (handler K3) i format dat (C9).
UNAUTHORIZED_BODY = {"code": 401, "message": "<Unauthorized '401: Unauthorized'>", "data": None}
DATE_RE = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
# Stałe statusów HTTP (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_OK = 200
_UNAUTHORIZED = 401
LOGIN_DATA_KEYS = {
    "id",
    "email",
    "nickname",
    "avatar",
    "language",
    "color_schema",
    "timezone",
    "is_superuser",
    "is_active",
    "last_login_time",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
    "login_channel",
    "access_token",
}
# Klucze listy kluczy API (złoto system__tokens/system--07.json) i odpowiedzi POST
# (system--08: upstream new_token nie oddaje dialog_id/source, znaczniki UPDATE = null).
TOKEN_DATA_KEYS = {
    "token",
    "tenant_id",
    "name",
    "dialog_id",
    "source",
    "beta",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
}
CREATED_TOKEN_DATA_KEYS = {
    "token",
    "tenant_id",
    "name",
    "beta",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
}


@pytest.fixture
def open_settings(auth_settings: Settings) -> Settings:
    """Ustawienia z włączoną rejestracją — zakładanie użytkowników przez POST /users."""
    return auth_settings.model_copy(update={"register_enabled": True})


@pytest.fixture
def client(auth_settings: Settings) -> Iterator[TestClient]:
    """Aplikacja domyślna (rejestracja wyłączona, login hasłem włączony)."""
    with TestClient(
        create_app(auth_settings, Container(auth_settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


@pytest.fixture
def open_client(open_settings: Settings) -> Iterator[TestClient]:
    """Aplikacja z włączoną rejestracją."""
    with TestClient(
        create_app(open_settings, Container(open_settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


def _register(client: TestClient, email: str, nickname: str) -> dict[str, object]:
    """Rejestracja przez POST /users; zwraca body (code 0)."""
    response = client.post(
        "/api/v1/users", json={"nickname": nickname, "email": email, "password": PASSWORD}
    )
    body = response.json()
    assert body["code"] == 0
    return body


def _login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    """Login → nagłówek Authorization z access tokenu."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.json()["code"] == 0
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _set_active(settings: Settings, user_id: str, active: bool) -> None:
    """Zmiana aktywności przez usługę we własnej pętli (test sync, TestClient ma własną)."""

    async def run() -> None:
        engine = make_engine(settings)
        try:
            service = UserService(
                make_sessionmaker(engine), settings, SystemClock(), UuidV7Generator()
            )
            await service.set_active(user_id, active)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_login_success_contract(open_client: TestClient) -> None:
    """Login OK: kształt body, klucze data, daty i nagłówki (upstream construct_response)."""
    _register(open_client, "jan@x.pl", "jan")
    response = open_client.post(
        "/api/v1/auth/login", json={"email": "jan@x.pl", "password": PASSWORD}
    )
    assert response.status_code == _OK
    body = response.json()
    assert set(body) == {"code", "message", "data"}
    assert body["message"] == "Welcome back!"
    data = body["data"]
    assert set(data) == LOGIN_DATA_KEYS
    assert data["is_active"] == "1"
    assert data["login_channel"] == "password"
    assert re.fullmatch(DATE_RE, data["create_date"])
    assert "password" not in data
    assert "password_hash" not in data
    assert response.headers["authorization"]
    assert response.headers["access-control-expose-headers"] == "Authorization"


def test_login_without_body(client: TestClient) -> None:
    """Puste ciało → upstream „Unauthorized!” (code 109, data false)."""
    response = client.post("/api/v1/auth/login")
    assert response.json() == {"code": 109, "message": "Unauthorized!", "data": False}


def test_login_unknown_email(client: TestClient) -> None:
    """Nieznany e-mail → upstream z e-mailem jak podany."""
    response = client.post("/api/v1/auth/login", json={"email": "x@x.pl", "password": PASSWORD})
    assert response.json() == {
        "code": 109,
        "message": "Email: x@x.pl is not registered!",
        "data": False,
    }


def test_login_bad_password(open_client: TestClient) -> None:
    """Złe hasło → upstream „Email and password do not match!”."""
    _register(open_client, "jan@x.pl", "jan")
    response = open_client.post(
        "/api/v1/auth/login", json={"email": "jan@x.pl", "password": "Wrong-pass1"}
    )
    assert response.json() == {
        "code": 109,
        "message": "Email and password do not match!",
        "data": False,
    }


def test_login_inactive_account(open_client: TestClient, open_settings: Settings) -> None:
    """Konto nieaktywne → code 403 z komunikatem upstream."""
    body = _register(open_client, "jan@x.pl", "jan")
    _set_active(open_settings, str(body["data"]["id"]), False)
    response = open_client.post(
        "/api/v1/auth/login", json={"email": "jan@x.pl", "password": PASSWORD}
    )
    assert response.json() == {
        "code": 403,
        "message": "This account has been disabled, please contact the administrator!",
        "data": False,
    }


def test_register_disabled(client: TestClient) -> None:
    """Pełne body przy wyłączonej rejestracji → upstream code 103."""
    response = client.post(
        "/api/v1/users", json={"nickname": "jan", "email": "jan@x.pl", "password": PASSWORD}
    )
    assert response.json() == {
        "code": 103,
        "message": "User registration is disabled!",
        "data": False,
    }


def test_register_missing_fields(open_client: TestClient) -> None:
    """Brakujące pola → upstream „required argument are missing: …; ” (code 101)."""
    response = open_client.post("/api/v1/users", json={"email": "a@x.pl"})
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"] == "required argument are missing: nickname,password; "


def test_register_success_contract(open_client: TestClient) -> None:
    """Rejestracja włączona: od razu sesja jak po loginie (R9) z nagłówkiem authorization."""
    response = open_client.post(
        "/api/v1/users", json={"nickname": "Nowy", "email": "nowy@x.pl", "password": PASSWORD}
    )
    body = response.json()
    assert body["code"] == 0
    assert body["message"] == "Nowy, welcome aboard!"
    assert response.headers["authorization"]


def test_system_config_contract(open_client: TestClient) -> None:
    """GET /system/config: dwie flagi jak w upstreamie i 07 §3.4.

    Kształt ze złota system__config/system--03.json (E2-1 SYS): bez bloku oidc, registerEnabled
    jako liczba (upstream REGISTER_ENABLED = 1/0). Kanały logowania: /auth/login/channels.
    """
    response = open_client.get("/api/v1/system/config")
    assert response.status_code == _OK
    assert response.json()["data"] == {"registerEnabled": 1, "disablePasswordLogin": False}


def test_login_channels_without_oidc(client: TestClient) -> None:
    """Bez OIDC → pusta lista kanałów."""
    response = client.get("/api/v1/auth/login/channels")
    assert response.json()["data"] == []


def test_login_channels_with_oidc(auth_settings: Settings) -> None:
    """OIDC skonfigurowane → dokładnie kanał keycloak (kształt upstream)."""
    settings = auth_settings.model_copy(
        update={"oidc_issuer": "http://idp", "oidc_client_id": "wd"}
    )
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        response = test_client.get("/api/v1/auth/login/channels")
    assert response.json()["data"] == [
        {"channel": "keycloak", "display_name": "Keycloak", "icon": "sso"}
    ]


def test_system_tokens_lifecycle(open_client: TestClient) -> None:
    """POST/GET/DELETE /system/tokens: kształt słownika, pełny token w liście,
    po DELETE token przestaje uwierzytelniać."""
    body = _register(open_client, "jan@x.pl", "jan")
    user_id = body["data"]["id"]
    headers = _login(open_client, "jan@x.pl")

    created = open_client.post("/api/v1/system/tokens", headers=headers)
    data = created.json()["data"]
    assert set(data) == CREATED_TOKEN_DATA_KEYS
    assert data["token"].startswith("ragflow-")
    assert data["tenant_id"] == user_id
    assert data["beta"] == data["token"][-32:]
    assert data["update_time"] is None
    assert data["update_date"] is None

    listed = open_client.get("/api/v1/system/tokens", headers=headers)
    entry = listed.json()["data"][0]
    assert set(entry) == TOKEN_DATA_KEYS
    assert entry["token"] == data["token"]
    assert entry["beta"] == data["token"][-32:]

    removed = open_client.delete(
        f"/api/v1/system/tokens/{quote(str(data['token']), safe='')}", headers=headers
    )
    assert removed.json() == {"code": 0, "message": "success", "data": True}
    assert (
        open_client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {data['token']}"}
        ).status_code
        == _UNAUTHORIZED
    )


def test_system_tokens_requires_principal(client: TestClient) -> None:
    """GET /system/tokens bez nagłówka → HTTP 401 z kopertą ragflow."""
    response = client.get("/api/v1/system/tokens")
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == UNAUTHORIZED_BODY
