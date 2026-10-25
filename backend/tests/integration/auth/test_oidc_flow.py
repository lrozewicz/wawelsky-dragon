"""Przepływ OIDC przez HTTP z FakeIdP: trasy login/keycloak i callback (07 §12 p. 4, brief T7)."""

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock
from app.db.engine import make_engine, make_sessionmaker
from app.main import create_app
from app.services.users import UserService
from tests.fakes.oidc_idp import FakeIdP

pytestmark = pytest.mark.db

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
# Stałe statusów HTTP (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_OK = 200
_REDIRECT = 302


@pytest.fixture
def idp() -> Iterator[FakeIdP]:
    with FakeIdP() as fake:
        yield fake


@pytest.fixture
def settings(auth_settings: Settings, idp: FakeIdP) -> Settings:
    """Ustawienia wg briefu T7: FakeIdP jako issuer, role/grupy admina, logout redirect."""
    return auth_settings.model_copy(
        update={
            "oidc_issuer": idp.issuer,
            "oidc_client_id": idp.client_id,
            "oidc_client_secret": SecretStr(idp.client_secret),
            "oidc_admin_roles": "wd-admin",
            "oidc_admin_groups": "wd-admins",
            "public_base_url": "http://localhost:8080",
            "oidc_logout_redirect": "http://localhost:8080/",
        }
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja z OIDC na FakeIdP; bez podążania za redirectami (sprawdzamy 302)."""
    with TestClient(
        create_app(settings, Container(settings)),
        base_url="https://testserver",
        follow_redirects=False,
    ) as test_client:
        yield test_client


@pytest.fixture
def plain_client(auth_settings: Settings) -> Iterator[TestClient]:
    """Aplikacja bez OIDC (auth_settings bez zmian)."""
    with TestClient(
        create_app(auth_settings, Container(auth_settings)),
        base_url="https://testserver",
        follow_redirects=False,
    ) as test_client:
        yield test_client


def login(client: TestClient, idp: FakeIdP, **kw: object) -> httpx.Response:
    """Pełny przepływ: begin → authorize na FakeIdP → callback."""
    r = client.get("/api/v1/auth/login/keycloak", params={"redirect": "/chat"})
    code, state = idp.authorize(r.headers["location"], **kw)  # type: ignore[arg-type]
    return client.get("/api/v1/auth/oauth/keycloak/callback", params={"code": code, "state": state})


def access_token(client: TestClient) -> str:
    """Access token z refresha po cookie wd_refresh."""
    body = client.post("/api/v1/auth/refresh").json()
    assert body["code"] == 0
    return str(body["data"]["access_token"])


def _me(client: TestClient, token: str) -> dict[str, object]:
    """GET /users/me z Bearer; zwraca data."""
    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.json()["code"] == 0
    data: dict[str, object] = response.json()["data"]
    return data


def _create_local_user(settings: Settings, email: str) -> None:
    """Utworzenie konta lokalnego usługą UserService (własna pętla, jak w kontraktowych)."""

    async def run() -> None:
        engine = make_engine(settings)
        try:
            users = UserService(
                make_sessionmaker(engine), settings, SystemClock(), UuidV7Generator()
            )
            await users.create(email=email, password=PASSWORD)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_login_keycloak_redirects_to_idp(client: TestClient, idp: FakeIdP) -> None:
    r = client.get("/api/v1/auth/login/keycloak", params={"redirect": "/chat"})
    assert r.status_code == _REDIRECT
    assert r.headers["location"].startswith(idp.issuer + "/auth?")
    cookies = " | ".join(r.headers.get_list("set-cookie")).lower()
    assert "wd_oidc=" in cookies
    assert "httponly" in cookies
    # env=test → bez Secure (C1); atrybuty rozdzielone po ';', żeby nie łapać wartości cookie.
    assert "secure" not in {part.strip() for part in cookies.split(";")}
    assert "samesite=lax" in cookies
    assert "path=/api/v1/auth/oauth/keycloak" in cookies


@pytest.mark.parametrize("redirect", ["https://evil.example", "//evil.example"])
def test_login_keycloak_open_redirect(client: TestClient, redirect: str) -> None:
    r = client.get("/api/v1/auth/login/keycloak", params={"redirect": redirect})
    assert r.status_code == _OK
    assert r.json() == {"code": 101, "message": "Invalid redirect", "data": None}


def test_callback_creates_session(client: TestClient, idp: FakeIdP) -> None:
    r = login(client, idp, sub="s-1", email="Ala@X.pl")
    assert r.status_code == _REDIRECT
    assert r.headers["location"] == "/chat"
    lowered = [c.lower() for c in r.headers.get_list("set-cookie")]
    assert any(c.startswith("wd_refresh=") for c in lowered)
    assert any("wd_oidc=" in c and "max-age=0" in c for c in lowered)
    data = _me(client, access_token(client))
    assert data["email"] == "ala@x.pl"
    assert data["login_channel"] == "keycloak"
    assert data["is_superuser"] is False


def test_admin_role_sync_over_http(client: TestClient, idp: FakeIdP) -> None:
    # Admin z roli realm (s-2) istnieje → zdegradowanie s-1 w trzecim logowaniu jest dozwolone.
    login(client, idp, sub="s-2", email="boss@x.pl", roles=("wd-admin",))
    assert _me(client, access_token(client))["is_superuser"] is True
    login(client, idp, sub="s-1", email="Ala@X.pl", groups=("/wd-admins",))
    assert _me(client, access_token(client))["is_superuser"] is True
    login(client, idp, sub="s-1", email="Ala@X.pl")
    assert _me(client, access_token(client))["is_superuser"] is False


def test_email_not_verified(client: TestClient, idp: FakeIdP) -> None:
    r = login(client, idp, sub="s-9", email="nover@x.pl", email_verified=False)
    assert r.status_code == _REDIRECT
    assert r.headers["location"] == "/?error=email_not_verified"
    lowered = [c.lower() for c in r.headers.get_list("set-cookie")]
    assert all("wd_refresh=" not in c for c in lowered)


def test_callback_without_state_cookie(client: TestClient, idp: FakeIdP) -> None:
    r = client.get("/api/v1/auth/login/keycloak", params={"redirect": "/chat"})
    code, state = idp.authorize(r.headers["location"], sub="s-1", email="Ala@X.pl")
    client.cookies.clear()
    r = client.get("/api/v1/auth/oauth/keycloak/callback", params={"code": code, "state": state})
    assert r.headers["location"] == "/?error=invalid_state"


def test_callback_with_bad_state(client: TestClient, idp: FakeIdP) -> None:
    client.get("/api/v1/auth/login/keycloak", params={"redirect": "/chat"})  # cookie w słoiku
    r = client.get("/api/v1/auth/oauth/keycloak/callback", params={"code": "kod", "state": "zly"})
    assert r.headers["location"] == "/?error=invalid_state"


def test_callback_without_code(client: TestClient, idp: FakeIdP) -> None:
    r = client.get("/api/v1/auth/login/keycloak", params={"redirect": "/chat"})
    _, state = idp.authorize(r.headers["location"], sub="s-1", email="Ala@X.pl")
    r = client.get("/api/v1/auth/oauth/keycloak/callback", params={"state": state})
    assert r.headers["location"] == "/?error=missing_code"


def test_callback_invalid_nonce(client: TestClient, idp: FakeIdP) -> None:
    r = login(client, idp, sub="s-1", email="Ala@X.pl", id_overrides={"nonce": "zly"})
    assert r.headers["location"] == "/?error=invalid_token"


def test_logout_oidc_user_returns_logout_url(client: TestClient, idp: FakeIdP) -> None:
    login(client, idp, sub="s-1", email="Ala@X.pl")
    headers = {"Authorization": f"Bearer {access_token(client)}"}
    body = client.post("/api/v1/auth/logout", headers=headers).json()
    assert body["code"] == 0
    assert body["data"] is True
    assert body["logout_url"] == (
        idp.issuer + "/logout?client_id=wawelsky-dragon"
        "&post_logout_redirect_uri=http%3A%2F%2Flocalhost%3A8080%2F"
    )


def test_logout_local_user_has_no_logout_url(client: TestClient, settings: Settings) -> None:
    _create_local_user(settings, "local@x.pl")
    r = client.post("/api/v1/auth/login", json={"email": "local@x.pl", "password": PASSWORD})
    assert r.json()["code"] == 0
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    body = client.post("/api/v1/auth/logout", headers=headers).json()
    assert "logout_url" not in body


def test_routes_disabled_without_oidc(plain_client: TestClient) -> None:
    envelope = {"code": 102, "message": "Invalid channel name: keycloak", "data": None}
    r = plain_client.get("/api/v1/auth/login/keycloak", params={"redirect": "/chat"})
    assert r.status_code == _OK
    assert r.json() == envelope
    r = plain_client.get("/api/v1/auth/oauth/keycloak/callback", params={"code": "k", "state": "s"})
    assert r.status_code == _OK
    assert r.json() == envelope


def test_logout_without_oidc_has_no_logout_url(
    plain_client: TestClient, auth_settings: Settings
) -> None:
    _create_local_user(auth_settings, "local2@x.pl")
    r = plain_client.post("/api/v1/auth/login", json={"email": "local2@x.pl", "password": PASSWORD})
    assert r.json()["code"] == 0
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    body = plain_client.post("/api/v1/auth/logout", headers=headers).json()
    assert body["code"] == 0
    assert "logout_url" not in body
