"""Testy get_principal — nagłówek Authorization, odcięcie Bearer, cache (C9, 07 §2 p. 1-5)."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.auth.principal import PrincipalDep
from app.api.errors import install_error_handlers
from app.core.errors import Unauthorized
from app.domain.policy import Principal

# Koperta 401 przestrzeni ragflow (07 §2, handler K3).
UNAUTHORIZED_BODY = {"code": 401, "message": "<Unauthorized '401: Unauthorized'>", "data": None}
# Stałe statusów (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_OK = 200
_UNAUTHORIZED = 401


class FakeAuth:
    """Podstawka container.auth — zapamiętuje otrzymane tokeny (bez bazy)."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def authenticate(self, token: str) -> Principal:
        self.tokens.append(token)
        return Principal("u-1", "jan@x.pl", False, False, "jwt")


class RaisingAuth(FakeAuth):
    """authenticate rzuca Unauthorized — jak usługa przy złym tokenie (07 §2 p. 4)."""

    async def authenticate(self, token: str) -> Principal:
        raise Unauthorized("x")


def make_client(auth: object) -> TestClient:
    """Aplikacja z jedną trasą testową i podstawionym container.auth (brief: bez bazy)."""
    app = FastAPI()
    install_error_handlers(app)
    app.state.container = SimpleNamespace(auth=auth)

    @app.get("/api/v1/_t")
    async def probe(p: PrincipalDep) -> dict[str, str]:
        return {"u": p.user_id}

    return TestClient(app)


def test_missing_or_empty_header_is_401_without_authenticate() -> None:
    """Brak nagłówka, pusty i samo „Bearer ” → 401 z kopertą ragflow; usługa nie wołana."""
    fake = FakeAuth()
    client = make_client(fake)
    for headers in (None, {"authorization": ""}, {"authorization": "Bearer "}):
        response = client.get("/api/v1/_t", headers=headers)
        assert response.status_code == _UNAUTHORIZED
        assert response.json() == UNAUTHORIZED_BODY
    assert fake.tokens == []


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER  abc ", "abc"),
        ("abc", "abc"),  # surowy token, jak web UI RAGFlow
    ],
)
def test_bearer_is_cut_case_insensitive(header: str, expected: str) -> None:
    """„Bearer ” odcinane case-insensitive z resztą strip(); surowy token przechodzi cały."""
    fake = FakeAuth()
    response = make_client(fake).get("/api/v1/_t", headers={"authorization": header})
    assert response.status_code == _OK
    assert response.json() == {"u": "u-1"}
    assert fake.tokens == [expected]


def test_authenticate_failure_is_ragflow_401() -> None:
    """Unauthorized z usługi → handler K3: HTTP 401 i koperta ragflow."""
    response = make_client(RaisingAuth()).get("/api/v1/_t", headers={"authorization": "Bearer abc"})
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == UNAUTHORIZED_BODY


def test_state_cache_skips_authenticate() -> None:
    """principal obecny w request.state → zwrot bez ponownego uwierzytelniania (07 §2 p. 5)."""
    fake = FakeAuth()
    client = make_client(fake)
    preset = Principal("pre-set", "pre@x.pl", False, False, "session_cookie")

    @client.app.middleware("http")
    async def preset_principal(request: Request, call_next):
        request.state.principal = preset
        return await call_next(request)

    response = client.get("/api/v1/_t", headers={"authorization": "Bearer abc"})
    assert response.status_code == _OK
    assert response.json() == {"u": "pre-set"}
    assert fake.tokens == []
