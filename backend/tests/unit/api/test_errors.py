"""Testy handlerów błędów: tabela klasa x przestrzeń i wiersze dosłowne z briefu (T4, C10)."""

import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import Request

from app.api.errors import _request_id, dify_status, install_error_handlers
from app.core.errors import (
    AuthenticationFailed,
    Busy,
    Conflict,
    NotFound,
    OperationNotAllowed,
    PermissionDenied,
    RateLimited,
    Unauthorized,
    UpstreamError,
    ValidationFailed,
    WDError,
)

ERRORS = {
    c.__name__: c
    for c in (
        WDError,
        ValidationFailed,
        NotFound,
        Conflict,
        PermissionDenied,
        AuthenticationFailed,
        Unauthorized,
        OperationNotAllowed,
        UpstreamError,
        Busy,
        RateLimited,
    )
}

PREFIXES = {
    "ragflow": "/api/v1/t",
    "ragflow-openai": "/api/v1/openai/t",
    "ragflow-dify": "/api/v1/dify/retrieval/t",
    "wd": "/api/wd/v1/t",
    "hub_compat": "/api/users/t",
    "hub_compat-user-api": "/user-api/api/users/t",
    "default": "/t",
}

# Statusy HTTP do asercji (PLR2004: porównania tylko ze stałymi modułowymi).
_OK = 200
_BAD_REQUEST = 400
_UNAUTHORIZED = 401
_FORBIDDEN = 403
_NOT_FOUND = 404
_METHOD_NOT_ALLOWED = 405
_CONFLICT = 409
_RATE_LIMITED = 429
_SERVER_ERROR = 500
_BAD_GATEWAY = 502

_HEX32 = re.compile(r"[0-9a-f]{32}")

_INT_PARSE_MSG = "Input should be a valid integer, unable to parse string as an integer"
_RAGFLOW_VALIDATION_TEXT = f"Field: size - Message: {_INT_PARSE_MSG} - Value: x"

# Mapowanie kod → status dla ragflow-dify, wprost z tabeli C10 (nie z kodu produkcyjnego).
_DIFY_HTTP = {101: 400, 102: 400, 103: 400, 108: 403, 109: 403, 404: 404}

_TABLE_SPACES = ("ragflow", "ragflow-dify", "wd", "hub_compat")


class Body(BaseModel):
    name: str
    size: int


def _make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    async def raise_error(name: str) -> None:
        raise ERRORS[name]("msg " + name, details={"k": 1})

    async def validate(body: Body) -> dict[str, str]:
        return {"ok": body.name}

    async def boom() -> None:
        raise RuntimeError("secret-value")

    for prefix in PREFIXES.values():
        app.get(prefix + "/raise/{name}")(raise_error)
        app.post(prefix + "/validate")(validate)
        app.get(prefix + "/boom")(boom)
    return app


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


def _expected_wd_error(space: str, name: str) -> tuple[int, dict[str, object]]:
    """Oczekiwania wyliczone wprost z tabel C10, nie z kodu produkcyjnego."""
    cls = ERRORS[name]
    msg = "msg " + name
    if space == "ragflow":
        if name == "Unauthorized":
            return _UNAUTHORIZED, {
                "code": 401,
                "message": "<Unauthorized '401: Unauthorized'>",
                "data": None,
            }
        return _OK, {"code": int(cls.code), "message": msg, "data": None}
    if space == "ragflow-dify":
        code = int(cls.code)
        return _DIFY_HTTP.get(code, 500), {"code": code, "message": msg}
    if space == "wd":
        return cls.http_status, {"error": {"code": cls.slug, "message": msg, "details": {"k": 1}}}
    return cls.http_status, {"error": msg}


@pytest.mark.parametrize(("space", "name"), [(s, n) for s in _TABLE_SPACES for n in ERRORS])
def test_wd_error_by_space_and_class(client: TestClient, space: str, name: str) -> None:
    resp = client.get(f"{PREFIXES[space]}/raise/{name}")
    status, body = _expected_wd_error(space, name)
    assert resp.status_code == status
    assert resp.json() == body


# --- Wiersze dosłowne z tabeli briefu: WDError ---


def test_row_ragflow_not_found(client: TestClient) -> None:
    resp = client.get(PREFIXES["ragflow"] + "/raise/NotFound")
    assert resp.status_code == _OK
    assert resp.json() == {"code": 102, "message": "msg NotFound", "data": None}


def test_row_ragflow_unauthorized(client: TestClient) -> None:
    resp = client.get(PREFIXES["ragflow"] + "/raise/Unauthorized")
    assert resp.status_code == _UNAUTHORIZED
    assert resp.json() == {
        "code": 401,
        "message": "<Unauthorized '401: Unauthorized'>",
        "data": None,
    }


def test_row_openai_busy(client: TestClient) -> None:
    resp = client.get(PREFIXES["ragflow-openai"] + "/raise/Busy")
    assert resp.status_code == _OK
    assert resp.json() == {"code": 106, "message": "msg Busy", "data": None}


def test_row_dify_validation_failed(client: TestClient) -> None:
    resp = client.get(PREFIXES["ragflow-dify"] + "/raise/ValidationFailed")
    assert resp.status_code == _BAD_REQUEST
    assert resp.json() == {"code": 101, "message": "msg ValidationFailed"}


def test_row_dify_permission_denied(client: TestClient) -> None:
    resp = client.get(PREFIXES["ragflow-dify"] + "/raise/PermissionDenied")
    assert resp.status_code == _FORBIDDEN
    assert resp.json() == {"code": 108, "message": "msg PermissionDenied"}


def test_row_dify_upstream_error(client: TestClient) -> None:
    resp = client.get(PREFIXES["ragflow-dify"] + "/raise/UpstreamError")
    assert resp.status_code == _SERVER_ERROR
    assert resp.json() == {"code": 105, "message": "msg UpstreamError"}


def test_row_wd_conflict(client: TestClient) -> None:
    resp = client.get(PREFIXES["wd"] + "/raise/Conflict")
    assert resp.status_code == _CONFLICT
    assert resp.json() == {
        "error": {"code": "conflict", "message": "msg Conflict", "details": {"k": 1}}
    }


def test_row_wd_rate_limited(client: TestClient) -> None:
    resp = client.get(PREFIXES["wd"] + "/raise/RateLimited")
    assert resp.status_code == _RATE_LIMITED
    assert resp.json() == {
        "error": {"code": "rate_limited", "message": "msg RateLimited", "details": {"k": 1}}
    }


def test_row_hub_compat_authentication_failed(client: TestClient) -> None:
    resp = client.get(PREFIXES["hub_compat"] + "/raise/AuthenticationFailed")
    assert resp.status_code == _UNAUTHORIZED
    assert resp.json() == {"error": "msg AuthenticationFailed"}


def test_row_hub_compat_user_api_not_found(client: TestClient) -> None:
    resp = client.get(PREFIXES["hub_compat-user-api"] + "/raise/NotFound")
    assert resp.status_code == _NOT_FOUND
    assert resp.json() == {"error": "msg NotFound"}


def test_row_default_upstream_error(client: TestClient) -> None:
    resp = client.get(PREFIXES["default"] + "/raise/UpstreamError")
    assert resp.status_code == _BAD_GATEWAY
    assert resp.json() == {
        "error": {"code": "upstream_error", "message": "msg UpstreamError", "details": {"k": 1}}
    }


# --- Wiersze dosłowne: RequestValidationError ---


def test_row_ragflow_validation(client: TestClient) -> None:
    resp = client.post(PREFIXES["ragflow"] + "/validate", json={"name": "a", "size": "x"})
    assert resp.status_code == _OK
    assert resp.json() == {"code": 101, "message": _RAGFLOW_VALIDATION_TEXT, "data": None}


def test_row_dify_validation(client: TestClient) -> None:
    resp = client.post(PREFIXES["ragflow-dify"] + "/validate", json={"name": "a", "size": "x"})
    assert resp.status_code == _BAD_REQUEST
    assert resp.json() == {"code": 101, "message": _RAGFLOW_VALIDATION_TEXT}


def test_row_wd_validation_missing(client: TestClient) -> None:
    resp = client.post(PREFIXES["wd"] + "/validate", json={"size": 1})
    assert resp.status_code == _BAD_REQUEST
    assert resp.json() == {
        "error": {
            "code": "validation_failed",
            "message": "Request validation failed",
            "details": {
                "errors": [
                    {
                        "type": "missing",
                        "loc": ["body", "name"],
                        "msg": "Field required",
                    }
                ]
            },
        }
    }


def test_row_wd_validation_without_input_for_scalar(client: TestClient) -> None:
    """K3 §5: w ``wd`` ``input`` wypada zawsze — także gdy jest skalarem wadliwego pola."""
    resp = client.post(PREFIXES["wd"] + "/validate", json={"name": "a", "size": "x"})
    assert resp.status_code == _BAD_REQUEST
    first = resp.json()["error"]["details"]["errors"][0]
    assert "input" not in first
    assert first["type"] == "int_parsing"


def test_row_default_validation_without_input(client: TestClient) -> None:
    """K3 §5: przestrzeń domyślna ma tę samą redakcję co ``wd`` (bez ``input``)."""
    resp = client.post(PREFIXES["default"] + "/validate", json={"size": 1})
    assert resp.status_code == _BAD_REQUEST
    first = resp.json()["error"]["details"]["errors"][0]
    assert first["type"] == "missing"
    assert "input" not in first


@pytest.mark.parametrize("space", ["ragflow", "ragflow-dify"])
def test_ragflow_validation_redacts_object_input(client: TestClient, space: str) -> None:
    """K3 §5: ``Value:`` w ``ragflow`` nie echuje obiektu ciała — klucze bez wartości."""
    resp = client.post(PREFIXES[space] + "/validate", json={"size": 1, "password": "s3cret-value"})
    assert "s3cret-value" not in resp.text
    message = resp.json()["message"]
    assert message.endswith("Value: {'size': '***', 'password': '***'}")


@pytest.mark.parametrize("space", ["ragflow", "ragflow-dify"])
def test_ragflow_validation_redacts_list_input(client: TestClient, space: str) -> None:
    """K3 §5: ciało-liśta w ``ragflow`` daje ``Value: [...]`` zamiast treści."""
    resp = client.post(PREFIXES[space] + "/validate", json=[{"password": "s3cret-value"}])
    assert "s3cret-value" not in resp.text
    assert resp.json()["message"].endswith("Value: [...]")


def test_row_hub_compat_validation(client: TestClient) -> None:
    resp = client.post(PREFIXES["hub_compat"] + "/validate", json={"name": "a", "size": "x"})
    assert resp.status_code == _BAD_REQUEST
    assert resp.json() == {"error": _INT_PARSE_MSG}


def test_row_wd_validation_no_ctx_url(client: TestClient) -> None:
    resp = client.post(PREFIXES["wd"] + "/validate", json={"name": "a", "size": "x"})
    first = resp.json()["error"]["details"]["errors"][0]
    assert "ctx" not in first
    assert "url" not in first


def test_extra_wd_validation_json_invalid_strips_ctx(client: TestClient) -> None:
    resp = client.post(
        PREFIXES["wd"] + "/validate",
        content=b"{invalid",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == _BAD_REQUEST
    first = resp.json()["error"]["details"]["errors"][0]
    assert "ctx" not in first
    assert "url" not in first


# --- Wiersze dosłowne: nieobsłużony wyjątek ---


def test_row_ragflow_boom(client: TestClient) -> None:
    resp = client.get(PREFIXES["ragflow"] + "/boom")
    rid = resp.headers["X-Request-ID"]
    assert _HEX32.fullmatch(rid) is not None
    assert resp.status_code == _OK
    assert resp.json() == {
        "code": 100,
        "message": f"Internal error, request_id={rid}",
        "data": None,
    }
    assert "secret-value" not in resp.text


def test_row_wd_boom(client: TestClient) -> None:
    resp = client.get(PREFIXES["wd"] + "/boom")
    rid = resp.headers["X-Request-ID"]
    assert resp.status_code == _SERVER_ERROR
    assert resp.json() == {
        "error": {
            "code": "internal_error",
            "message": f"Internal error, request_id={rid}",
            "details": None,
        }
    }


def test_row_hub_compat_boom(client: TestClient) -> None:
    resp = client.get(PREFIXES["hub_compat"] + "/boom")
    rid = resp.headers["X-Request-ID"]
    assert resp.status_code == _SERVER_ERROR
    assert resp.json() == {"error": f"Internal error, request_id={rid}"}


def test_row_dify_boom(client: TestClient) -> None:
    resp = client.get(PREFIXES["ragflow-dify"] + "/boom")
    rid = resp.headers["X-Request-ID"]
    assert resp.status_code == _SERVER_ERROR
    assert resp.json() == {"code": 100, "message": f"Internal error, request_id={rid}"}


def test_row_boom_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="app.errors"):
        resp = client.get(PREFIXES["ragflow"] + "/boom")
    records = [record for record in caplog.records if record.name == "app.errors"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info
    assert records[0].request_id == resp.headers["X-Request-ID"]


# --- Wiersze dosłowne: HTTPException (404 nieznana trasa, 405 metoda) ---


def test_row_ragflow_404(client: TestClient) -> None:
    resp = client.get("/api/v1/nope")
    assert resp.status_code == _NOT_FOUND
    assert resp.json() == {
        "code": 404,
        "message": "Not Found: /api/v1/nope",
        "data": None,
        "error": "Not Found",
    }


def test_row_wd_404(client: TestClient) -> None:
    resp = client.get("/api/wd/v1/nope")
    assert resp.status_code == _NOT_FOUND
    assert resp.json() == {
        "error": {"code": "not_found", "message": "Not Found: /api/wd/v1/nope", "details": None}
    }


def test_row_hub_compat_404(client: TestClient) -> None:
    resp = client.get("/api/users/nope/x")
    assert resp.status_code == _NOT_FOUND
    assert resp.json() == {"error": "Not Found: /api/users/nope/x"}


def test_row_default_404(client: TestClient) -> None:
    resp = client.get("/nope")
    assert resp.status_code == _NOT_FOUND
    assert resp.json() == {
        "error": {"code": "not_found", "message": "Not Found: /nope", "details": None}
    }


def test_extra_dify_404(client: TestClient) -> None:
    resp = client.get("/api/v1/dify/retrieval/nope")
    assert resp.status_code == _NOT_FOUND
    assert resp.json() == {"code": 404, "message": "Not Found: /api/v1/dify/retrieval/nope"}


def test_row_wd_405(client: TestClient) -> None:
    resp = client.delete(PREFIXES["wd"] + "/boom")
    assert resp.status_code == _METHOD_NOT_ALLOWED
    assert resp.json() == {
        "error": {"code": "http_405", "message": "Method Not Allowed", "details": None}
    }


def test_row_ragflow_405(client: TestClient) -> None:
    resp = client.delete(PREFIXES["ragflow"] + "/boom")
    assert resp.status_code == _OK
    assert resp.json() == {"code": 405, "message": "Method Not Allowed", "data": None}


def test_extra_dify_405(client: TestClient) -> None:
    resp = client.delete(PREFIXES["ragflow-dify"] + "/boom")
    assert resp.status_code == _METHOD_NOT_ALLOWED
    assert resp.json() == {"code": 405, "message": "Method Not Allowed"}


def test_extra_hub_compat_405(client: TestClient) -> None:
    resp = client.delete(PREFIXES["hub_compat"] + "/boom")
    assert resp.status_code == _METHOD_NOT_ALLOWED
    assert resp.json() == {"error": "Method Not Allowed"}


# --- Nagłówek X-Request-ID i pomocnicze ---


def test_row_request_id_header_on_handler_responses(client: TestClient) -> None:
    for path in (
        PREFIXES["ragflow"] + "/raise/NotFound",
        PREFIXES["wd"] + "/raise/Conflict",
        PREFIXES["hub_compat"] + "/boom",
    ):
        resp = client.get(path)
        assert _HEX32.fullmatch(resp.headers["X-Request-ID"]) is not None


def test_extra_request_id_prefers_state() -> None:
    scope = {
        "type": "http",
        "path": "/x",
        "scheme": "http",
        "server": ("testserver", 80),
        "headers": [],
        "state": {"request_id": "fixed-id"},
    }
    assert _request_id(Request(scope)) == "fixed-id"


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (101, 400),
        (102, 400),
        (103, 400),
        (108, 403),
        (109, 403),
        (404, 404),
        (100, 500),
        (105, 500),
        (106, 500),
        (401, 500),
        (429, 500),
    ],
)
def test_dify_status(code: int, expected_status: int) -> None:
    assert dify_status(code) == expected_status
