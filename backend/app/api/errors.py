"""Handlery błędów FastAPI mapujące wyjątki na koperty przestrzeni API (kontrakt C10, K3 §3-§4)."""

import logging
from collections.abc import Mapping
from typing import cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.ragflow.compat import explicit_compat
from app.core.error_codes import (
    MSG_AUTH_HEADER_MISSING,
    MSG_INTERNAL_ERROR,
    MSG_NOT_FOUND_PATH,
    MSG_RAGFLOW_UNAUTHORIZED,
    MSG_RAGFLOW_VALIDATION,
    MSG_V024_AUTH_EMPTY,
    MSG_V024_AUTH_INVALID,
    MSG_VALIDATION_FAILED,
)
from app.core.errors import Unauthorized, WDError, api_space
from app.core.ids import new_id

# Stała do porównań statusów (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_HTTP_NOT_FOUND = 404

# Kod RAGFlow koperty „pustego” uwierzytelnienia v0.24 (RetCode.SUCCESS).
_V024_EMPTY_CODE = 0
# Kod RAGFlow koperty złego klucza v0.24 (RetCode.AUTHENTICATION_ERROR).
_V024_INVALID_CODE = 109


def _request_id(request: Request) -> str:
    """Identyfikator żądania: z middleware, jeśli jest; inaczej nowy UUIDv7."""
    return getattr(request.state, "request_id", None) or new_id()


def dify_status(code: int) -> int:
    """Status HTTP koperty ragflow-dify dla kodu RAGFlow (tabela C10)."""
    if code in (101, 102, 103):
        return 400
    if code in (108, 109):
        return 403
    if code == _HTTP_NOT_FOUND:
        return _HTTP_NOT_FOUND
    return 500


def _ragflow(code: int, message: str) -> dict[str, object]:
    """Koperta przestrzeni ragflow/ragflow-openai."""
    return {"code": code, "message": message, "data": None}


def _ragflow_v024(code: int, message: str) -> dict[str, object]:
    """Koperta uwierzytelnienia shimu v0.24: ``data: false`` zamiast ``None`` (C4)."""
    return {"code": code, "message": message, "data": False}


def _dify(code: int, message: str) -> dict[str, object]:
    """Koperta przestrzeni ragflow-dify."""
    return {"code": code, "message": message}


def _wd(code: str, message: str, details: object = None) -> dict[str, object]:
    """Koperta przestrzeni wd (i domyślnej)."""
    return {"error": {"code": code, "message": message, "details": details}}


def _hub_compat(message: str) -> dict[str, object]:
    """Koperta przestrzeni hub-compat (bez pola code — wariant opcjonalny K3 pominięty w E0)."""
    return {"error": message}


async def _handle_wd_error(request: Request, exc: Exception) -> JSONResponse:
    """WDError: koperta zależna od przestrzeni (tabela C10)."""
    err = cast(WDError, exc)
    space = api_space(request.url.path)
    rid = _request_id(request)
    if space == "ragflow-dify":
        status, content = dify_status(int(err.code)), _dify(int(err.code), err.message)
    elif space in ("ragflow", "ragflow-openai"):
        if isinstance(err, Unauthorized) and explicit_compat(request) == "ragflow_0_24":
            # Shim v0.24 (C4): 200 zamiast 401; komunikat rozstrzyga kopertę.
            if err.message == MSG_AUTH_HEADER_MISSING:
                status, content = 200, _ragflow_v024(_V024_EMPTY_CODE, MSG_V024_AUTH_EMPTY)
            else:
                status, content = 200, _ragflow_v024(_V024_INVALID_CODE, MSG_V024_AUTH_INVALID)
        elif isinstance(err, Unauthorized):
            status, content = 401, _ragflow(401, MSG_RAGFLOW_UNAUTHORIZED)
        else:
            status, content = 200, _ragflow(int(err.code), err.message)
    elif space == "hub_compat":
        status, content = err.http_status, _hub_compat(err.message)
    else:
        status, content = err.http_status, _wd(err.slug, err.message, err.details)
    return JSONResponse(content, status_code=status, headers={"X-Request-ID": rid})


def _ragflow_value(first: Mapping[str, object]) -> object:
    """Wartość ``Value:`` komunikatu ragflow: kontener (całe ciało) zredagowany (K3 §5)."""
    value = first.get("input")
    if isinstance(value, dict):
        return {key: "***" for key in value}
    if isinstance(value, list):
        return "[...]"
    return value


async def _handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    """RequestValidationError: 200 w ragflow, 400 w pozostałych (tabela C10)."""
    err = cast(RequestValidationError, exc)
    space = api_space(request.url.path)
    rid = _request_id(request)
    first = err.errors()[0]
    name = str(first["loc"][-1])
    text = MSG_RAGFLOW_VALIDATION.format(name=name, msg=first["msg"], value=_ragflow_value(first))
    if space in ("ragflow", "ragflow-openai"):
        status, content = 200, _ragflow(101, text)
    elif space == "ragflow-dify":
        status, content = 400, _dify(101, text)
    elif space == "hub_compat":
        status, content = 400, _hub_compat(str(first["msg"]))
    else:
        # Lista błędów Pydantic bez pól ctx/url/input (K3 §5), w kształcie JSON (loc jako lista).
        errors = jsonable_encoder(
            [
                {k: v for k, v in error.items() if k not in ("ctx", "url", "input")}
                for error in err.errors()
            ]
        )
        status, content = 400, _wd("validation_failed", MSG_VALIDATION_FAILED, {"errors": errors})
    return JSONResponse(content, status_code=status, headers={"X-Request-ID": rid})


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """HTTPException (Starlette): nieznana trasa 404 i pozostałe statusy (tabela C10)."""
    err = cast(StarletteHTTPException, exc)
    space = api_space(request.url.path)
    rid = _request_id(request)
    if err.status_code == _HTTP_NOT_FOUND:
        msg = MSG_NOT_FOUND_PATH.format(path=request.url.path)
        if space in ("ragflow", "ragflow-openai"):
            status, content = 404, {"code": 404, "message": msg, "data": None, "error": "Not Found"}
        elif space == "ragflow-dify":
            status, content = 404, _dify(404, msg)
        elif space == "hub_compat":
            status, content = 404, _hub_compat(msg)
        else:
            status, content = 404, _wd("not_found", msg)
    else:
        detail = str(err.detail)
        if space in ("ragflow", "ragflow-openai"):
            status, content = 200, _ragflow(err.status_code, detail)
        elif space == "ragflow-dify":
            status, content = err.status_code, _dify(err.status_code, detail)
        elif space == "hub_compat":
            status, content = err.status_code, _hub_compat(detail)
        else:
            status, content = err.status_code, _wd(f"http_{err.status_code}", detail)
    # Nagłówki z wyjątku zachowane; X-Request-ID zawsze wygrywa (kontrakt K3 §4).
    return JSONResponse(
        content, status_code=status, headers={**(err.headers or {}), "X-Request-ID": rid}
    )


async def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Nieobsłużony wyjątek: log ERROR i koperta bez szczegółów (tabela C10)."""
    space = api_space(request.url.path)
    rid = _request_id(request)
    logging.getLogger("app.errors").error(
        "unhandled exception",
        exc_info=exc,
        extra={"event": "unhandled_exception", "request_id": rid, "path": request.url.path},
    )
    msg = MSG_INTERNAL_ERROR.format(request_id=rid)
    if space in ("ragflow", "ragflow-openai"):
        status, content = 200, _ragflow(100, msg)
    elif space == "ragflow-dify":
        status, content = 500, _dify(100, msg)
    elif space == "hub_compat":
        status, content = 500, _hub_compat(msg)
    else:
        status, content = 500, _wd("internal_error", msg)
    return JSONResponse(content, status_code=status, headers={"X-Request-ID": rid})


def install_error_handlers(app: FastAPI) -> None:
    """Rejestruje cztery handlery błędów (kontrakt C10)."""
    app.add_exception_handler(WDError, _handle_wd_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unhandled)
