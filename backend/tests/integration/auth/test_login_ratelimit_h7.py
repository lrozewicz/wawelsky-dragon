"""HTTP: 11. próba logowania błędnym hasłem → odmowa limitu (H7, CONTRACT E5-2a §4).

Trasa i kształt logowania wg `tests/integration/auth/test_auth_flow.py`. Domyślne
`settings.rate_limit_login` = `"10/min"`: pierwsze 10 prób to odmowa poświadczeń,
11. to odmowa limitu.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.core.errors import RateLimited
from app.main import create_app

pytestmark = pytest.mark.db

EMAIL = "jan@x.pl"
# 405 znaków > VARCHAR(320) kolumny `email_key` — limiter musi obciąć, nie wysypać 500.
LONG_EMAIL = "a" * 400 + "@x.pl"
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
BAD_PASSWORD = "Wrong-pass1"  # noqa: S105 — celowa atrapa hasła w teście
MSG_TOO_MANY = "Too many login attempts, please try again later."

_OK = 200
_AUTH_FAILED_CODE = int(RetCode.AUTHENTICATION_ERROR)
_RATE_LIMITED_CODE = int(RateLimited.code)


@pytest.fixture
def settings(auth_settings: Settings) -> Settings:
    """Rejestracja włączona — użytkownika zakłada trasa POST /users."""
    return auth_settings.model_copy(update={"register_enabled": True})


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


def _login(client: TestClient, password: str, email: str = EMAIL) -> dict[str, object]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    body = response.json()
    return {"status": response.status_code, **body}


def test_login_rate_limited_after_ten_bad_passwords(client: TestClient) -> None:
    register = client.post(
        "/api/v1/users", json={"nickname": "jan", "email": EMAIL, "password": PASSWORD}
    )
    assert register.status_code == _OK

    for _ in range(10):
        body = _login(client, BAD_PASSWORD)
        assert body["status"] == _OK
        assert body["code"] == _AUTH_FAILED_CODE  # odmowa poświadczeń (109)
        assert body["data"] is False

    limited = _login(client, BAD_PASSWORD)
    assert limited["status"] == _OK
    assert limited["code"] == _RATE_LIMITED_CODE
    assert limited["message"] == MSG_TOO_MANY


def test_long_email_gets_normal_denial_not_500(client: TestClient) -> None:
    """E-mail > 320 znaków: limiter obcina klucz → zwykła odmowa poświadczeń, nie 500."""
    body = _login(client, BAD_PASSWORD, email=LONG_EMAIL)
    assert body["status"] == _OK
    assert body["code"] == _AUTH_FAILED_CODE
    assert body["data"] is False
