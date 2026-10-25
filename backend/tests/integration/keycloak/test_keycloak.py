"""Integracja z prawdziwym Keycloakiem, realm wawelsky-test (07 §12 p. 4b, brief T7).

Backchannel (token_endpoint, JWKS) idzie na KC_INTERNAL przez transport przepisujący;
issuer/authorization/end_session pozostają na KC_PUBLIC (frontchannel przeglądarki).
"""

import html
import os
import re
from collections.abc import Iterator
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.container import Container
from app.main import create_app
from app.services.oidc import OidcService

pytestmark = pytest.mark.keycloak

# WD_KC_PUBLIC_URL/WD_KC_INTERNAL_URL pozwalają wskazać instancję Keycloaka z innym portem
# hosta (KC_PORT) — gdy 8180 zajmuje inna, wspólna instancja (deploy/keycloak/up.sh jest
# idempotentny tylko w obrębie własnego projektu compose).
KC_PUBLIC = os.environ.get("WD_KC_PUBLIC_URL", "http://localhost:8180")
KC_INTERNAL = os.environ.get("WD_KC_INTERNAL_URL", "http://host.docker.internal:8180")
REALM = "wawelsky-test"
ISSUER = f"{KC_PUBLIC}/realms/{REALM}"
CLIENT_ID = "wawelsky-dragon"
CLIENT_SECRET = "wawelsky-test-secret"  # noqa: S105 — sekret klienta testowego Keycloaka
USER_PASSWORD = "Test1234!"  # noqa: S105 — hasło użytkowników testowych realmu
CALLBACK_URL = "http://localhost:8080/api/v1/auth/oauth/keycloak/callback"
_KC_PORT = urlsplit(KC_PUBLIC).port or 80
# Stałe statusów HTTP (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
HTTP_OK = 200
HTTP_NO_CONTENT = 204
REDIRECT = 302

_INTERNAL = urlsplit(KC_INTERNAL)


def _rewrite(url: httpx.URL) -> httpx.URL:
    """KC_PUBLIC → host/port z KC_INTERNAL (backchannel przez kontener)."""
    if url.host == "localhost" and url.port == _KC_PORT:
        return url.copy_with(host=_INTERNAL.hostname, port=_INTERNAL.port)
    return url


def _kc(url: str) -> str:
    """Frontchannel: KC_HOSTNAME jest ustalony na localhost — przepisane na KC_INTERNAL.

    Cookiejar httpx nie wysyła ciasteczek dla hosta bez kropki („localhost” → „localhost.local”)."""
    return url.replace(KC_PUBLIC, KC_INTERNAL)


class _SyncRewrite(httpx.BaseTransport):
    """Sync transport przepisujący host (klient-przeglądarka, frontchannel)."""

    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.url = _rewrite(request.url)
        return self._inner.handle_request(request)


class _AsyncRewrite(httpx.AsyncBaseTransport):
    """Async transport przepisujący host (OidcService, backchannel)."""

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        rewritten = _rewrite(request.url)
        if rewritten != request.url:
            request.url = rewritten
            # KC_HOSTNAME_BACKCHANNEL_DYNAMIC: discovery buduje token_endpoint i jwks_uri
            # z nagłówka Host — bez przepięcia jwks_uri wróci na localhost, gdzie urllib
            # (PyJWKClient) dostanie Connection refused.
            request.headers["host"] = rewritten.netloc.decode("ascii")
        return await self._inner.handle_async_request(request)


@pytest.fixture(scope="module")
def keycloak_up() -> None:
    """Skip, gdy testowy Keycloak nie odpowiada (deploy/keycloak/up.sh; verify.sh --sso)."""
    try:
        response = httpx.get(
            f"{KC_INTERNAL}/realms/{REALM}/.well-known/openid-configuration", timeout=5
        )
    except httpx.HTTPError:
        pytest.skip("Keycloak testowy nie odpowiada (deploy/keycloak/up.sh)")
    if response.status_code != HTTP_OK:
        pytest.skip("Keycloak testowy nie odpowiada (deploy/keycloak/up.sh)")


@pytest.fixture
def client(keycloak_up: None, auth_settings: Settings) -> Iterator[TestClient]:
    """Aplikacja z OIDC na testowym Keycloaku; backchannel przez _AsyncRewrite."""
    settings = auth_settings.model_copy(
        update={
            "oidc_issuer": ISSUER,
            "oidc_client_id": CLIENT_ID,
            "oidc_client_secret": SecretStr(CLIENT_SECRET),
            "oidc_admin_roles": "wd-admin",
            "oidc_admin_groups": "wd-admins",
            "public_base_url": "http://localhost:8080",
            "oidc_logout_redirect": "http://localhost:8080/",
        }
    )
    with TestClient(
        create_app(settings, Container(settings)),
        base_url="https://testserver",
        follow_redirects=False,
    ) as test_client:
        container = test_client.app.state.container
        old = container.oidc
        assert old is not None
        assert container.sessionmaker is not None
        assert container.users is not None
        container.oidc = OidcService(
            container.settings,
            container.clock,
            container.id_gen,
            httpx.AsyncClient(transport=_AsyncRewrite(), timeout=10.0),
            container.users,
            container.sessionmaker,
        )
        test_client.portal.call(old.aclose)
        yield test_client  # nowy oidc zamyka container.aclose() w __exit__


def _begin_browser_login(client: TestClient, email: str) -> tuple[httpx.Response, httpx.Client]:
    """Logowanie formularzem Keycloaka w httpx; zwraca (odpowiedź callbacku, otwarta przeglądarka).

    Nowy httpx.Client na każde logowanie — bez sesji SSO Keycloaka między logowaniami.
    """
    start = client.get("/api/v1/auth/login/keycloak")
    assert start.status_code == REDIRECT
    browser = httpx.Client(transport=_SyncRewrite(), follow_redirects=False)
    form_page = browser.get(_kc(start.headers["location"]))
    assert form_page.status_code == HTTP_OK
    match = re.search(r'id="kc-form-login"[^>]*action="([^"]+)"', form_page.text)
    assert match is not None
    action = _kc(html.unescape(match.group(1)))
    submitted = browser.post(
        action, data={"username": email, "password": USER_PASSWORD, "credentialId": ""}
    )
    assert submitted.status_code == REDIRECT
    location = submitted.headers["location"]
    assert location.startswith(CALLBACK_URL + "?")
    return (
        client.get("/api/v1/auth/oauth/keycloak/callback?" + urlsplit(location).query),
        browser,
    )


def _browser_login(client: TestClient, email: str) -> httpx.Response:
    """Jak _begin_browser_login, ale zamyka przeglądarkę (gdy nie potrzebna do end_session)."""
    callback, browser = _begin_browser_login(client, email)
    browser.close()
    return callback


def _me_after_refresh(client: TestClient) -> dict[str, object]:
    """Refresh po cookie wd_refresh → GET /users/me z Bearer; zwraca data."""
    body = client.post("/api/v1/auth/refresh").json()
    assert body["code"] == 0
    me = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {body['data']['access_token']}"},
    ).json()
    assert me["code"] == 0
    data: dict[str, object] = me["data"]
    return data


def _admin_headers() -> dict[str, str]:
    """Token admin-cli z master realmu → nagłówek Authorization do Admin API."""
    response = httpx.post(
        f"{KC_INTERNAL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": "admin",  # hasło admina bootstrapowego testowego Keycloaka
        },
        timeout=10.0,
    )
    assert response.status_code == HTTP_OK
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _set_demoted_role(*, grant: bool) -> None:
    """Nadanie (True) albo odebranie (False) roli wd-admin demoted@wd.test przez Admin API."""
    headers = _admin_headers()
    found = httpx.get(
        f"{KC_INTERNAL}/admin/realms/{REALM}/users",
        params={"email": "demoted@wd.test", "exact": "true"},
        headers=headers,
        timeout=10.0,
    ).json()
    role = httpx.get(
        f"{KC_INTERNAL}/admin/realms/{REALM}/roles/wd-admin", headers=headers, timeout=10.0
    ).json()
    response = httpx.request(
        "POST" if grant else "DELETE",
        f"{KC_INTERNAL}/admin/realms/{REALM}/users/{found[0]['id']}/role-mappings/realm",
        json=[role],
        headers=headers,
        timeout=10.0,
    )
    assert response.status_code in (HTTP_OK, HTTP_NO_CONTENT)


def test_discovery_via_internal(keycloak_up: None) -> None:
    data = httpx.get(
        f"{KC_INTERNAL}/realms/{REALM}/.well-known/openid-configuration", timeout=10.0
    ).json()
    assert data["issuer"] == ISSUER
    assert data["jwks_uri"]
    assert data["token_endpoint"]


def test_user_login_provisions_account(client: TestClient) -> None:
    callback = _browser_login(client, "user@wd.test")
    assert callback.status_code == REDIRECT
    assert callback.headers["location"] == "/"  # redirect nie podany → "/"
    data = _me_after_refresh(client)
    assert data["email"] == "user@wd.test"
    assert data["login_channel"] == "keycloak"
    assert data["is_superuser"] is False


def test_admin_role_grant_and_revoke(client: TestClient) -> None:
    admin = _browser_login(client, "admin@wd.test")
    assert admin.status_code == REDIRECT
    assert _me_after_refresh(client)["is_superuser"] is True
    try:
        _set_demoted_role(grant=True)  # stan realmu przeżywa między biegami
        demoted = _browser_login(client, "demoted@wd.test")
        assert demoted.status_code == REDIRECT
        assert _me_after_refresh(client)["is_superuser"] is True
        _set_demoted_role(grant=False)
        demoted_again = _browser_login(client, "demoted@wd.test")
        assert demoted_again.status_code == REDIRECT
        # admin@wd.test (wcześniej zalogowany) zostaje adminem, więc degradacja przechodzi.
        assert _me_after_refresh(client)["is_superuser"] is False
    finally:
        _set_demoted_role(grant=True)


def test_unverified_rejected_and_logout_url(client: TestClient) -> None:
    rejected = _browser_login(client, "unverified@wd.test")
    assert rejected.status_code == REDIRECT
    assert rejected.headers["location"] == "/?error=email_not_verified"
    callback, browser = _begin_browser_login(client, "user@wd.test")
    try:
        assert callback.status_code == REDIRECT
        body = client.post(
            "/api/v1/auth/refresh",
        ).json()
        logout = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {body['data']['access_token']}"},
        ).json()
        assert logout["code"] == 0
        url = logout["logout_url"]
        assert url.startswith(ISSUER + "/protocol/openid-connect/logout?")
        assert "client_id=wawelsky-dragon" in url
        # Obserwowane 200: strona potwierdzenia (bez id_token_hint Keycloak nie przekierowuje).
        ended = browser.get(_kc(url))  # ta sama przeglądarka, co przy logowaniu
        assert ended.status_code in (HTTP_OK, REDIRECT)
    finally:
        browser.close()
