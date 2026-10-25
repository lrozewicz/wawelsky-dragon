"""Testy złożonej aplikacji: create_app, lifespan, middleware, handlery (T5, kontrakt C12)."""

import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.container import Container
from app.core.version import APP_VERSION
from app.main import create_app
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

BACKEND_DIR = Path(__file__).resolve().parents[2]

_HEX32 = re.compile(r"[0-9a-f]{32}")

_OK = 200
_NOT_FOUND = 404
_NOT_READY = 503


@pytest.fixture(autouse=True)
def _clean_wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Izolacja od WD_* z env procesu — Settings() czyta tylko to, co test ustawi."""
    for name in list(os.environ):
        if name.startswith("WD_"):
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _remove_wd_logging_handlers() -> Iterator[None]:
    """configure_logging dodaje handler `wd` do root loggera — sprzątamy po teście."""
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == "wd":
            root.removeHandler(handler)


@pytest.fixture
def settings() -> Settings:
    return Settings(env="test")


@pytest.fixture
def container(settings: Settings) -> Container:
    return Container(settings, clock=FrozenClock(), id_gen=SeqIdGenerator())


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    return create_app(settings, container)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_create_app_returns_fastapi() -> None:
    app = create_app(Settings(env="test"))
    assert isinstance(app, FastAPI)
    assert app.title == "Wawelsky Dragon"
    assert app.version == APP_VERSION


def test_import_with_empty_environ() -> None:
    process = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_DIR,
        env={},
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")


def test_create_app_default_prod_requires_secrets() -> None:
    with pytest.raises(ValidationError) as err:
        create_app()
    assert "WD_SECRET_KEY" in str(err.value)


def test_create_app_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WD_ENV", "dev")
    app = create_app()
    assert app.state.settings.env == "dev"
    assert isinstance(app.state.container, Container)


def test_state_holds_passed_objects(app: FastAPI, settings: Settings, container: Container) -> None:
    assert app.state.settings is settings
    assert app.state.container is container


def test_lifespan_starts_and_closes_container(app: FastAPI) -> None:
    container: Container = app.state.container
    with TestClient(app):
        assert container.started is True
    assert container.started is False


def test_health_live(client: TestClient) -> None:
    resp = client.get("/health/live")
    assert resp.status_code == _OK
    assert resp.json() == {"status": "ok"}
    assert _HEX32.fullmatch(resp.headers["X-Request-ID"]) is not None


def test_request_id_passthrough(client: TestClient) -> None:
    resp = client.get("/health/live", headers={"X-Request-ID": "my-req.1"})
    assert resp.headers["X-Request-ID"] == "my-req.1"


def test_request_id_invalid_replaced(client: TestClient) -> None:
    resp = client.get("/health/live", headers={"X-Request-ID": "bad header!"})
    rid = resp.headers["X-Request-ID"]
    assert _HEX32.fullmatch(rid) is not None
    assert rid != "bad header!"


def test_404_ragflow_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/nope")
    assert resp.status_code == _NOT_FOUND
    assert resp.json() == {
        "code": 404,
        "message": "Not Found: /api/v1/nope",
        "data": None,
        "error": "Not Found",
    }
    assert "X-Request-ID" in resp.headers


def test_single_request_id_header(client: TestClient) -> None:
    resp = client.get("/api/v1/nope", headers={"X-Request-ID": "abc"})
    assert resp.headers.get_list("x-request-id") == ["abc"]


def test_404_wd_envelope(client: TestClient) -> None:
    resp = client.get("/api/wd/v1/nope")
    assert resp.status_code == _NOT_FOUND
    assert resp.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found: /api/wd/v1/nope",
            "details": None,
        }
    }


def test_openapi_contains_health_live(client: TestClient) -> None:
    resp = client.get("/api/wd/v1/openapi.json")
    assert resp.status_code == _OK
    assert "/health/live" in resp.json()["paths"]


def test_docs(client: TestClient) -> None:
    assert client.get("/api/wd/v1/docs").status_code == _OK


def test_default_openapi_is_404(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == _NOT_FOUND


def test_health_ready_without_lifespan_is_503(client: TestClient) -> None:
    """Trasa /health/ready istnieje (C6); bez lifespan engine None → 503 not_ready."""
    resp = client.get("/health/ready")
    assert resp.status_code == _NOT_READY
    assert resp.json()["error"]["code"] == "not_ready"
    assert resp.json()["error"]["message"] == "database engine not started"


def test_unhandled_exception_ragflow_envelope(app: FastAPI) -> None:
    @app.get("/api/v1/t/boom")
    async def boom() -> None:
        raise RuntimeError("secret")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/t/boom", headers={"X-Request-ID": "rid-1"})
    assert resp.status_code == _OK
    assert resp.json() == {
        "code": 100,
        "message": "Internal error, request_id=rid-1",
        "data": None,
    }
    assert resp.headers["X-Request-ID"] == "rid-1"
    assert "secret" not in resp.text


def test_cors_preflight() -> None:
    app = create_app(Settings(env="test", cors_origins="https://a.pl"))
    client = TestClient(app)
    resp = client.options(
        "/health/live",
        headers={
            "Origin": "https://a.pl",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers["access-control-allow-origin"] == "https://a.pl"
