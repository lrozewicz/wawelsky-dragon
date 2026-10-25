"""Cookie `wd_refresh` i `wd_oidc`: flaga `Secure` wg `WD_COOKIE_SECURE` i `X-Forwarded-Proto`.

Kontrakt C1, brief T1. Tabela prawdy: `WD_ENV` != `prod` → bez `Secure` (sesja po HTTP musi przeżyć
F5); `prod` + `true` → zawsze; `prod` + `false` → nigdy; `prod` + `auto` → pierwsza wartość
`X-Forwarded-Proto` == `https`, a przy braku nagłówka → schemat żądania == `https`. Flagi kasowania
(logout, callback OIDC) muszą zgadzać się z ustawianiem. Testy HTTP są `db` (świeża baza per
przypadek); test walidacji `Settings` i helper bez bazy działają też w `verify-fast`.
"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack

import httpx
import pytest
from fastapi import Request
from fastapi.responses import Response
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.ragflow.auth import _clear_oidc_cookie, _cookie_secure
from app.core.config import Settings
from app.core.container import Container
from app.main import create_app

EMAIL = "jan@x.pl"
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
_OK = 200
# Wspólne flagi cookie wd_refresh, niezależne od env i WD_COOKIE_SECURE (B3 + C1).
REFRESH_ATTRS = {"httponly", "samesite=strict", "path=/api/v1/auth"}
# Ta sama reguła dla cookie stanu OIDC (C9 + C1).
OIDC_ATTRS = {"httponly", "samesite=lax", "path=/api/v1/auth/oauth/keycloak"}

# Wartości X-Forwarded-Proto z macierzy briefu T1 (+ odwrotna kolejność z tabeli prawdy C1).
XFP_VALUES: tuple[str | None, ...] = ("https", "http", None, "https, http", "http, https")
# prod + auto: X-Forwarded-Proto → Secure (C1; liczy się pierwsza wartość, brak → schemat żądania).
PROD_AUTO: dict[str | None, bool] = {
    "https": True,
    "http": False,
    None: False,  # brak nagłówka + żądanie po http
    "https, http": True,
    "http, https": False,
}
# prod: WD_COOKIE_SECURE → Secure niezależnie od nagłówka.
PROD_FIXED: dict[str, bool] = {"true": True, "false": False}


def _expected_secure(env: str, cookie_secure: str, proto: str | None) -> bool:
    """Tabela prawdy C1 dla loginu po `http` (osobny test pokrywa sam schemat `https`)."""
    if env != "prod":
        return False
    if cookie_secure in PROD_FIXED:
        return PROD_FIXED[cookie_secure]
    return PROD_AUTO[proto]


def _set_cookie_headers(response: httpx.Response | Response) -> list[str]:
    """Nagłówki Set-Cookie — httpx.Headers ma `get_list`, starlette MutableHeaders `getlist`."""
    headers = response.headers
    get_all = getattr(headers, "get_list", None) or getattr(headers, "getlist", None)
    assert get_all is not None, f"nieznane API nagłówków: {type(headers)}"
    return list(get_all("set-cookie"))


def _cookie_attrs(response: httpx.Response | Response, name: str) -> set[str]:
    """Atrybuty nagłówka Set-Cookie o danej nazwie (lowercase, bez pary nazwa=wartość)."""
    for header in _set_cookie_headers(response):
        if header.startswith(f"{name}="):
            return {part.strip().lower() for part in header.split(";")[1:]}
    raise AssertionError(f"brak nagłówka Set-Cookie dla {name}")


def _settings(env: str, **overrides: object) -> Settings:
    """Ustawienia bez bazy: sekrety prod wypełnione, żeby przejść walidację K8 część A."""
    base: dict[str, object] = {
        "env": env,
        "db_password": "p",
        "secret_key": "s" * 48,
        "crypto_key": "ab" * 32,
        "llm_base_url": "http://llm",
    }
    return Settings(**(base | overrides))  # type: ignore[arg-type]


@pytest.fixture
def make_client(auth_settings: Settings) -> Iterator[Callable[..., TestClient]]:
    """Fabryka klientów na świeżej bazie (env/cookie_secure/schemat/nagłówek); zamykane po test."""

    with ExitStack() as stack:

        def make(
            env: str,
            *,
            cookie_secure: str = "auto",
            base_url: str = "http://testserver",
            forwarded_proto: str | None = None,
        ) -> TestClient:
            settings = auth_settings.model_copy(
                update={"env": env, "register_enabled": True, "cookie_secure": cookie_secure}
            )
            headers = (
                {"X-Forwarded-Proto": forwarded_proto} if forwarded_proto is not None else None
            )
            client = TestClient(
                create_app(settings, Container(settings)), base_url=base_url, headers=headers
            )
            return stack.enter_context(client)

        yield make


def _login(client: TestClient) -> httpx.Response:
    """Rejestracja i login; zwraca odpowiedź loginu z nagłówkiem Set-Cookie."""
    client.post("/api/v1/users", json={"nickname": "jan", "email": EMAIL, "password": PASSWORD})
    return client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})


_MATRIX = [
    pytest.param(env, secure, proto, id=f"{env}-{secure}-{proto or 'no-xfp'}")
    for env in ("dev", "prod")
    for secure in ("auto", "true", "false")
    for proto in XFP_VALUES
]


@pytest.mark.db
@pytest.mark.parametrize(("env", "cookie_secure", "proto"), _MATRIX)
def test_login_and_logout_cookie_secure_matrix(
    make_client: Callable[..., TestClient],
    env: str,
    cookie_secure: str,
    proto: str | None,
) -> None:
    """Macierz C1: login ustawia, a logout kasuje cookie wd_refresh z tą samą flagą `Secure`."""
    client = make_client(env, cookie_secure=cookie_secure, forwarded_proto=proto)
    expected = _expected_secure(env, cookie_secure, proto)
    login = _login(client)
    assert login.status_code == _OK
    assert login.json()["code"] == 0
    attrs = _cookie_attrs(login, "wd_refresh")
    assert ("secure" in attrs) is expected
    assert attrs >= REFRESH_ATTRS
    bearer = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    out = client.post("/api/v1/auth/logout", headers=bearer)
    assert out.json()["data"] is True
    deleted = _cookie_attrs(out, "wd_refresh")
    assert ("secure" in deleted) is expected
    assert "max-age=0" in deleted
    assert deleted >= REFRESH_ATTRS


@pytest.mark.db
@pytest.mark.parametrize(("scheme", "secure"), [("https", True), ("http", False)])
def test_login_cookie_secure_auto_without_header_uses_request_scheme(
    make_client: Callable[..., TestClient],
    scheme: str,
    secure: bool,
) -> None:
    """prod + auto bez nagłówka: o fladze decyduje schemat żądania (C1 tabela prawdy)."""
    client = make_client("prod", cookie_secure="auto", base_url=f"{scheme}://testserver")
    attrs = _cookie_attrs(_login(client), "wd_refresh")
    assert ("secure" in attrs) is secure


def _request_for(settings: Settings, forwarded_proto: str | None = None) -> Request:
    """Minimalny Request z kontenerem aplikacji (bez lifespana) — do helperów cookie."""
    app = create_app(settings, Container(settings))
    headers = [] if forwarded_proto is None else [(b"x-forwarded-proto", forwarded_proto.encode())]
    scope = {
        "type": "http",
        "scheme": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": headers,
        "app": app,
    }
    return Request(scope)


@pytest.mark.parametrize(("env", "secure"), [("dev", False), ("test", False), ("prod", True)])
def test_cookie_secure_helper_by_env(env: str, secure: bool) -> None:
    """Helper czyta env i WD_COOKIE_SECURE z ustawień kontenera (C1); auto + brak nagłówka."""
    settings = _settings(env, cookie_secure="true")
    assert _cookie_secure(_request_for(settings)) is secure


@pytest.mark.parametrize(
    ("cookie_secure", "proto", "secure"),
    [
        ("auto", "https", True),
        ("auto", "http", False),
        ("auto", None, False),
        ("true", None, True),
        ("false", "https", False),
    ],
)
def test_clear_oidc_cookie_flags_match_set(
    cookie_secure: str, proto: str | None, secure: bool
) -> None:
    """Kasowanie cookie wd_oidc bierze tę samą regułę Secure co ustawianie (C1)."""
    settings = _settings("prod", cookie_secure=cookie_secure)
    response = Response()
    _clear_oidc_cookie(response, _request_for(settings, proto))
    attrs = _cookie_attrs(response, "wd_oidc")
    assert ("secure" in attrs) is secure
    assert "max-age=0" in attrs
    assert attrs >= OIDC_ATTRS


def test_settings_cookie_secure_defaults_to_auto() -> None:
    """Brak WD_COOKIE_SECURE → `auto` (K8 poprawka 2026-10-04b p. 2)."""
    assert _settings("test").cookie_secure == "auto"


def test_settings_reject_cookie_secure_outside_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wartość spoza {auto, true, false} → ValidationError przy Settings() (C1)."""
    monkeypatch.delenv("WD_COOKIE_SECURE", raising=False)
    with pytest.raises(ValidationError, match="cookie_secure"):
        Settings(env="test", cookie_secure="maybe")
