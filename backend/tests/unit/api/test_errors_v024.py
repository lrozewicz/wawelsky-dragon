"""Handler WDError w przestrzeni ragflow dla profilu 0.24 (brief T2, kontrakt C4).

Bez bazy: ``explicit_compat`` czyta wyłącznie nagłówek/query żądania, więc testujemy
``_handle_wd_error`` na minimalnej aplikacji (wzór ``tests/unit/api/test_errors.py``).
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.errors import install_error_handlers
from app.api.ragflow.compat import explicit_compat
from app.core.error_codes import MSG_AUTH_HEADER_MISSING
from app.core.errors import Unauthorized

_OK = 200
_UNAUTHORIZED = 401

_RAGFLOW = "/api/v1/t"
_OPENAI = "/api/v1/openai/t"

_EMPTY_AUTH_BODY = {
    "code": 0,
    "data": False,
    "message": "`Authorization` can't be empty",
}
_INVALID_KEY_BODY = {
    "code": 109,
    "data": False,
    "message": "Authentication error: API key is invalid!",
}
_UNAUTHORIZED_BODY = {
    "code": 401,
    "data": None,
    "message": "<Unauthorized '401: Unauthorized'>",
}


def _make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    async def missing() -> None:
        raise Unauthorized(MSG_AUTH_HEADER_MISSING)

    async def invalid() -> None:
        raise Unauthorized("bad api key")

    for prefix in (_RAGFLOW, _OPENAI):
        app.get(prefix + "/missing")(missing)
        app.get(prefix + "/invalid")(invalid)
    return app


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


def test_missing_header_with_v024_header_envelope(client: TestClient) -> None:
    """Brak Authorization + nagłówek 0.24 → 200, code 0, data false (C4)."""
    resp = client.get(_RAGFLOW + "/missing", headers={"X-RAGFlow-Compat": "0.24"})
    assert resp.status_code == _OK
    assert resp.json() == _EMPTY_AUTH_BODY
    assert resp.headers.get("X-Request-ID")


def test_invalid_key_with_v024_header_envelope(client: TestClient) -> None:
    """Zły klucz + nagłówek 0.24 → 200, code 109, data false (C4)."""
    resp = client.get(_RAGFLOW + "/invalid", headers={"X-RAGFlow-Compat": "0.24"})
    assert resp.status_code == _OK
    assert resp.json() == _INVALID_KEY_BODY


def test_missing_header_with_v024_query_envelope(client: TestClient) -> None:
    """Brak Authorization + query compat=0.24 → 200, code 0 (C4)."""
    resp = client.get(_RAGFLOW + "/missing?compat=0.24")
    assert resp.status_code == _OK
    assert resp.json() == _EMPTY_AUTH_BODY


def test_openai_space_missing_header_with_v024(client: TestClient) -> None:
    """Przestrzeń ragflow-openai też dostaje kopertę v0.24 (C4)."""
    resp = client.get(_OPENAI + "/missing", headers={"X-RAGFlow-Compat": "0.24"})
    assert resp.status_code == _OK
    assert resp.json() == _EMPTY_AUTH_BODY


def test_without_profile_keeps_401(client: TestClient) -> None:
    """Bez profilu → dotychczasowa koperta 401 (C4)."""
    resp = client.get(_RAGFLOW + "/missing")
    assert resp.status_code == _UNAUTHORIZED
    assert resp.json() == _UNAUTHORIZED_BODY


def test_profile_0_27_keeps_401(client: TestClient) -> None:
    """Profil 0.27 → dotychczasowa koperta 401 (C4)."""
    resp = client.get(_RAGFLOW + "/missing", headers={"X-RAGFlow-Compat": "0.27"})
    assert resp.status_code == _UNAUTHORIZED
    assert resp.json() == _UNAUTHORIZED_BODY


def test_header_wins_over_query(client: TestClient) -> None:
    """Nagłówek 0.27 wygrywa z query compat=0.24 → 401 (kolejność nagłówek→query, C4)."""
    resp = client.get(_RAGFLOW + "/missing?compat=0.24", headers={"X-RAGFlow-Compat": "0.27"})
    assert resp.status_code == _UNAUTHORIZED
    assert resp.json() == _UNAUTHORIZED_BODY


def test_unknown_profile_value_keeps_401(client: TestClient) -> None:
    """Nieznana wartość profilu → 401 (explicit_compat zwraca None, bez wyjątku, C4)."""
    resp = client.get(_RAGFLOW + "/missing", headers={"X-RAGFlow-Compat": "9.9"})
    assert resp.status_code == _UNAUTHORIZED
    assert resp.json() == _UNAUTHORIZED_BODY


def test_explicit_compat_reads_header_then_query() -> None:
    """explicit_compat: nagłówek przed query; nieznana wartość → None (C4)."""
    app = FastAPI()

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, object]:
        return {"profile": explicit_compat(request)}

    client = TestClient(app)
    assert client.get("/probe", headers={"X-RAGFlow-Compat": "0.24"}).json() == {
        "profile": "ragflow_0_24"
    }
    assert client.get("/probe?compat=0.24").json() == {"profile": "ragflow_0_24"}
    assert client.get("/probe?compat=0.24", headers={"X-RAGFlow-Compat": "0.27"}).json() == {
        "profile": "ragflow_0_27"
    }
    assert client.get("/probe", headers={"X-RAGFlow-Compat": "nope"}).json() == {"profile": None}
    assert client.get("/probe").json() == {"profile": None}
