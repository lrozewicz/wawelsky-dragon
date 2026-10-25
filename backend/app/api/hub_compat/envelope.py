"""Koperta powierzchni hub-compat (SVC): sukces `{"data": …}`, błąd `{"error": …}` (kontrakt C7)."""

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import (
    Conflict,
    NotFound,
    OperationNotAllowed,
    ResourceNotFound,
    Unauthorized,
    ValidationFailed,
    WDError,
)

_BAD_REQUEST = 400
_UNAUTHORIZED = 401
_NOT_FOUND = 404
_METHOD_NOT_ALLOWED = 405
_CONFLICT = 409


class MethodNotAllowed(WDError):
    """Zła metoda na trasie SVC → 405 `{"error": "Method not allowed"}` (C7)."""

    http_status = _METHOD_NOT_ALLOWED
    slug = "method_not_allowed"


def data(payload: object, status: int = 200) -> JSONResponse:
    """Sukces hub-compat: `{"data": payload}` ze statusem (domyślnie 200) — C7."""
    return JSONResponse({"data": payload}, status_code=status)


def svc_error(exc: WDError | RequestValidationError) -> JSONResponse:
    """Błąd hub-compat: `{"error": komunikat}` ze statusem z tabeli C7.

    `ValidationFailed`/`OperationNotAllowed`/`RequestValidationError` → 400 (nigdy 422),
    `NotFound`/`ResourceNotFound` → 404, `Conflict` → 409, `Unauthorized` → 401,
    `MethodNotAllowed` → 405, pozostałe `WDError` → `exc.http_status`.
    """
    if isinstance(exc, RequestValidationError):
        return JSONResponse({"error": str(exc.errors()[0]["msg"])}, status_code=_BAD_REQUEST)
    if isinstance(exc, (ValidationFailed, OperationNotAllowed)):
        return JSONResponse({"error": exc.message}, status_code=_BAD_REQUEST)
    if isinstance(exc, (NotFound, ResourceNotFound)):
        return JSONResponse({"error": exc.message}, status_code=_NOT_FOUND)
    if isinstance(exc, Conflict):
        return JSONResponse({"error": exc.message}, status_code=_CONFLICT)
    if isinstance(exc, Unauthorized):
        return JSONResponse({"error": exc.message}, status_code=_UNAUTHORIZED)
    return JSONResponse({"error": exc.message}, status_code=exc.http_status)
