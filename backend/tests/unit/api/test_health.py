"""Test GET /health/live i /health/ready (T4 kontrakt C11, T3 kontrakt C6)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import router
from app.core.config import Settings
from app.main import create_app

_OK = 200
_NOT_READY = 503


def test_health_live() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/health/live")
    assert resp.status_code == _OK
    assert resp.json() == {"status": "ok"}


def test_health_ready_engine_not_started() -> None:
    """Bez wejścia w lifespan engine jest None → 503 "database engine not started"."""
    app = create_app(Settings(env="test", db_host="127.0.0.1", db_port=1))
    client = TestClient(app)
    resp = client.get("/health/ready")
    assert resp.status_code == _NOT_READY
    assert resp.json() == {
        "error": {"code": "not_ready", "message": "database engine not started", "details": None}
    }


def test_health_ready_db_unavailable() -> None:
    """Lifespan tworzy engine, baza na porcie 1 nie odpowiada → 503 w kopercie wd."""
    app = create_app(Settings(env="test", db_host="127.0.0.1", db_port=1))
    with TestClient(app) as client:
        resp = client.get("/health/ready")
    assert resp.status_code == _NOT_READY
    assert resp.json() == {
        "error": {"code": "not_ready", "message": "database unavailable", "details": None}
    }
    assert "x-request-id" in resp.headers
