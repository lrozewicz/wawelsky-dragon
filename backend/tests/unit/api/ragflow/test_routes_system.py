"""Testy tras system z E2-1 (brief SYS p. 1-2, 5-6): koperty, healthz bez koperty, 401."""

from fastapi.testclient import TestClient

from app.api.ragflow.routes.system import (
    COMPAT_VERSION,
    healthz_body,
    stats_body,
    status_body,
)
from app.core.config import Settings
from app.main import create_app
from app.services.system_info import ComponentProbe, SystemStatusRecord

_OK = 200
_UNAUTHORIZED = 401
UNAUTHORIZED_BODY = {"code": 401, "message": "<Unauthorized '401: Unauthorized'>", "data": None}
# Timeout/czas sondy w teście (PLR2004): wartość bez znaczenia, byle z jednym miejscem.
ELAPSED_MS = 1.25


def _client() -> TestClient:
    """TestClient bez lifespanu: trasy publiczne i 401 działają bez bazy (brief SYS p. 6)."""
    return TestClient(create_app(Settings(env="test", db_host="127.0.0.1", db_port=1)))


def test_ping_is_text_pong() -> None:
    """GET /system/ping: „pong” jako text/html (upstream Quart; złoto system--01.json)."""
    response = _client().get("/api/v1/system/ping")
    assert response.status_code == _OK
    assert response.text == "pong"
    assert response.headers["content-type"].startswith("text/html")


def test_version_is_golden_value() -> None:
    """GET /system/version: dosłownie „v0.27.2” (złoto system--02.json)."""
    response = _client().get("/api/v1/system/version")
    assert response.status_code == _OK
    assert response.json() == {"code": 0, "message": "success", "data": COMPAT_VERSION}
    assert COMPAT_VERSION == "v0.27.2"


def test_config_has_exactly_two_flags() -> None:
    """GET /system/config: registerEnabled jako liczba, bez bloku oidc (złoto system--03.json)."""
    data = _client().get("/api/v1/system/config").json()["data"]
    assert set(data) == {"registerEnabled", "disablePasswordLogin"}
    assert data["registerEnabled"] == 0
    assert data["disablePasswordLogin"] is False


def test_language_is_python() -> None:
    """GET /language: {"language": "python"} (złoto system--05.json)."""
    response = _client().get("/api/v1/language")
    assert response.json() == {"code": 0, "message": "success", "data": {"language": "python"}}


def test_healthz_body_ok_and_nok() -> None:
    """Ciało /system/healthz: „ok”/„nok” jak upstream, db_engine i redis bez sondy (p. 2)."""
    assert healthz_body(True, True) == {
        "db": "ok",
        "doc_engine": "ok",
        "redis": "ok",
        "status": "ok",
        "storage": "ok",
    }
    assert healthz_body(False, True) == {
        "db": "nok",
        "doc_engine": "ok",
        "redis": "ok",
        "status": "nok",
        "storage": "ok",
    }


def test_status_body_shape() -> None:
    """Ciało /system/status: bloki sond i tętna workerów (złoto system--06.json)."""
    record = SystemStatusRecord(
        database=ComponentProbe(ok=True, elapsed_ms=ELAPSED_MS),
        storage=ComponentProbe(ok=False, elapsed_ms=ELAPSED_MS),
        heartbeats={"host:1": [{"heartbeat_at": 1}]},
    )
    body = status_body(record)
    assert set(body) == {
        "database",
        "doc_engine",
        "redis",
        "storage",
        "task_executor_heartbeats",
    }
    assert body["database"] == {"database": "mysql", "status": "green", "elapsed": "1.2"}
    assert body["storage"] == {"storage": "local", "status": "red", "elapsed": "1.2"}
    assert body["redis"] == {"status": "green", "elapsed": "0.0"}
    assert body["doc_engine"]["elapsed"] == "0.0"
    assert body["doc_engine"]["type"] == "elasticsearch"
    assert body["task_executor_heartbeats"] == {"host:1": [{"heartbeat_at": 1}]}


def test_stats_body_empty_series() -> None:
    """Ciało /system/stats: sześć pustych serii (złoto system--10.json)."""
    assert stats_body() == {
        "pv": [],
        "uv": [],
        "speed": [],
        "tokens": [],
        "round": [],
        "thumb_up": [],
    }


def test_models_without_api_key_is_unauthorized() -> None:
    """GET /models bez nagłówka Authorization → 401 z kopertą ragflow (brief SYS p. 6)."""
    response = _client().get("/api/v1/models")
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == UNAUTHORIZED_BODY


def test_system_status_without_api_key_is_unauthorized() -> None:
    """GET /system/status bez nagłówka Authorization → 401 z kopertą ragflow."""
    response = _client().get("/api/v1/system/status")
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == UNAUTHORIZED_BODY
