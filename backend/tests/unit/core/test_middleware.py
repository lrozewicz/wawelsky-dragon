"""Testy RequestContextMiddleware i install_middleware wg kontraktu C9 — przykłady z briefu T3."""

import logging
import re
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from app.core.config import Settings
from app.core.logging import request_id_var
from app.core.middleware import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    install_middleware,
    is_valid_request_id,
)

HEX32_RE = re.compile(r"[0-9a-f]{32}")

HTTP_OK = 200
HTTP_INTERNAL_ERROR = 500


@pytest.fixture(autouse=True)
def _clean_contextvar() -> Iterator[None]:
    """Po każdym teście contextvar request_id wraca do domyślnej None."""
    yield
    request_id_var.set(None)


def _app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/api/wd/v1/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/boom")
    async def boom() -> dict[str, bool]:
        raise RuntimeError("boom")

    @app.get("/api/wd/v1/state")
    async def state(request: Request) -> dict[str, str | None]:
        return {"rid": request.state.request_id, "space": request.state.api_space}

    install_middleware(app, settings or Settings(env="test"))
    return app


def test_is_valid_request_id_accepts_good_ids() -> None:
    assert is_valid_request_id("abc-123_X.y") is True
    assert is_valid_request_id("a" * 128) is True


def test_is_valid_request_id_rejects_bad_ids() -> None:
    assert is_valid_request_id("") is False
    assert is_valid_request_id("a" * 129) is False
    assert is_valid_request_id("bad id") is False
    assert is_valid_request_id("zły") is False
    assert is_valid_request_id("a/b") is False


def test_existing_request_id_is_passed_through() -> None:
    client = TestClient(_app())
    r = client.get("/api/wd/v1/ping", headers={REQUEST_ID_HEADER: "abc-123"})
    assert r.status_code == HTTP_OK
    assert r.headers[REQUEST_ID_HEADER] == "abc-123"


def test_missing_request_id_generates_one() -> None:
    client = TestClient(_app())
    r = client.get("/api/wd/v1/ping")
    assert HEX32_RE.fullmatch(r.headers[REQUEST_ID_HEADER]) is not None


def test_invalid_request_id_is_replaced() -> None:
    client = TestClient(_app())
    r = client.get("/api/wd/v1/ping", headers={REQUEST_ID_HEADER: "bad id!"})
    assert r.headers[REQUEST_ID_HEADER] != "bad id!"
    assert HEX32_RE.fullmatch(r.headers[REQUEST_ID_HEADER]) is not None


def test_too_long_request_id_is_replaced() -> None:
    client = TestClient(_app())
    r = client.get("/api/wd/v1/ping", headers={REQUEST_ID_HEADER: "a" * 129})
    assert HEX32_RE.fullmatch(r.headers[REQUEST_ID_HEADER]) is not None


def test_state_request_id_and_api_space() -> None:
    client = TestClient(_app())
    r = client.get("/api/wd/v1/state", headers={REQUEST_ID_HEADER: "r1"})
    assert r.json() == {"rid": "r1", "space": "wd"}


def test_access_log_record(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_app())
    with caplog.at_level(logging.INFO, logger="app.http"):
        r = client.get("/api/wd/v1/ping", params={"token": "sekret"})
    assert r.status_code == HTTP_OK
    records = [rec for rec in caplog.records if rec.name == "app.http"]
    assert len(records) == 1
    rec = records[0]
    assert rec.event == "http_request"
    assert rec.method == "GET"
    assert rec.path == "/api/wd/v1/ping"
    assert "sekret" not in rec.getMessage()
    assert rec.status == HTTP_OK
    assert rec.api_space == "wd"
    assert isinstance(rec.duration_ms, float)
    assert rec.duration_ms >= 0


def test_unhandled_exception_logs_status_500(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="app.http"):
        r = client.get("/api/v1/boom")
    assert r.status_code == HTTP_INTERNAL_ERROR
    records = [rec for rec in caplog.records if rec.name == "app.http"]
    assert len(records) == 1
    assert records[0].status == HTTP_INTERNAL_ERROR
    assert records[0].api_space == "ragflow"


def test_request_id_var_reset_after_request() -> None:
    client = TestClient(_app())
    client.get("/api/wd/v1/ping")
    assert request_id_var.get() is None


def test_install_without_cors_settings() -> None:
    app = FastAPI()
    install_middleware(app, Settings(env="test"))
    classes = [m.cls for m in app.user_middleware]
    assert CORSMiddleware not in classes
    assert RequestContextMiddleware in classes


def test_cors_preflight_gets_request_id() -> None:
    client = TestClient(_app(Settings(env="test", cors_origins="https://a.pl, https://b.pl")))
    r = client.options(
        "/api/wd/v1/ping",
        headers={"Origin": "https://a.pl", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == HTTP_OK
    assert r.headers["access-control-allow-origin"] == "https://a.pl"
    assert r.headers[REQUEST_ID_HEADER] != ""


def test_request_context_middleware_is_outermost() -> None:
    app = FastAPI()
    install_middleware(app, Settings(env="test", cors_origins="https://a.pl, https://b.pl"))
    assert app.user_middleware[0].cls is RequestContextMiddleware


def test_lifespan_scope_passes_through() -> None:
    with TestClient(_app()):
        pass
