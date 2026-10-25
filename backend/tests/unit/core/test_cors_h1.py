"""Dowody H1 (CORS): obcy origin bez ACAO, jawny origin z credentials, brak listy bez nagłówków.

Wzorzec aplikacji: `tests/unit/core/test_middleware.py::_app`.
Stan faktyczny (sprawdzony w źródle): `app/core/middleware.py::install_middleware`
dodaje `CORSMiddleware` tylko gdy `Settings.cors_origins` po odfiltrowaniu pustych
elementów jest niepuste; `allow_credentials=True`; `Settings._reject_wildcard_cors`
odrzuca `*` niezależnie od trybu.
"""

import os

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from app.core.config import Settings
from app.core.middleware import install_middleware

PING = "/api/wd/v1/ping"
ALLOWED_ORIGIN = "https://a.pl"
EVIL_ORIGIN = "https://evil.pl"
HTTP_OK = 200

# Nagłówki odpowiedzi CORS, które nie mogą się pojawić przy pustej liście originów.
_ACCESS_CONTROL_PREFIX = "access-control-"


@pytest.fixture(autouse=True)
def _clean_wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Izolacja od WD_* z env procesu — weryfikujemy wyłącznie wartości podane wprost."""
    for name in list(os.environ):
        if name.startswith("WD_"):
            monkeypatch.delenv(name, raising=False)


def _app(settings: Settings) -> FastAPI:
    """Aplikacja z trasą ping i middleware wg `settings`."""
    app = FastAPI()

    @app.get(PING)
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    install_middleware(app, settings)
    return app


def test_foreign_origin_gets_no_allow_origin_header() -> None:
    """(a) Lista `https://a.pl`, żądanie z `Origin: https://evil.pl` → brak ACAO."""
    client = TestClient(_app(Settings(env="test", cors_origins=ALLOWED_ORIGIN)))
    response = client.get(PING, headers={"Origin": EVIL_ORIGIN})
    assert response.status_code == HTTP_OK
    assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_gets_echo_not_wildcard() -> None:
    """(b) Preflight z dozwolonym originem: ACAO == origin i credentials true, nigdy `*`."""
    client = TestClient(_app(Settings(env="test", cors_origins=ALLOWED_ORIGIN)))
    response = client.options(
        PING,
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == HTTP_OK
    allow_origin = response.headers["access-control-allow-origin"]
    assert allow_origin == ALLOWED_ORIGIN
    assert allow_origin != "*"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_allowed_origin_on_simple_request_is_echoed_with_credentials() -> None:
    """(b) Proste GET z dozwolonym originem też dostaje echo + credentials (nie `*`)."""
    client = TestClient(_app(Settings(env="test", cors_origins=ALLOWED_ORIGIN)))
    response = client.get(PING, headers={"Origin": ALLOWED_ORIGIN})
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_empty_origins_list_adds_no_cors_headers() -> None:
    """(c) `cors_origins=""` → żądania z `Origin` nie dostają żadnych nagłówków CORS."""
    app = _app(Settings(env="test"))
    assert CORSMiddleware not in [middleware.cls for middleware in app.user_middleware]
    client = TestClient(app)
    response = client.get(PING, headers={"Origin": ALLOWED_ORIGIN})
    assert response.status_code == HTTP_OK
    assert [name for name in response.headers if name.startswith(_ACCESS_CONTROL_PREFIX)] == []


def test_wildcard_in_origins_list_is_rejected() -> None:
    """(d) `https://a.pl,*` → ValidationError z komunikatem WD_CORS_ORIGINS."""
    with pytest.raises(ValidationError, match="WD_CORS_ORIGINS"):
        Settings(env="test", cors_origins=f"{ALLOWED_ORIGIN},*")
