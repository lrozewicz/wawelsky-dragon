"""Kody wyniku RAGFlow skopiowane z common/constants.py i komunikaty błędów (kontrakt C3, K3 §1)."""

from enum import IntEnum


class RetCode(IntEnum):
    """Kody wyniku zgodne z RAGFlow — wartości zamrożone, nie zmieniać."""

    SUCCESS = 0
    NOT_EFFECTIVE = 10
    EXCEPTION_ERROR = 100
    ARGUMENT_ERROR = 101
    DATA_ERROR = 102
    OPERATING_ERROR = 103
    CONNECTION_ERROR = 105
    RUNNING = 106
    PERMISSION_ERROR = 108
    AUTHENTICATION_ERROR = 109
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    SERVER_ERROR = 500


MSG_INTERNAL_ERROR = "Internal error, request_id={request_id}"
MSG_NOT_FOUND_PATH = "Not Found: {path}"
MSG_RAGFLOW_UNAUTHORIZED = "<Unauthorized '401: Unauthorized'>"
MSG_VALIDATION_FAILED = "Request validation failed"
MSG_RAGFLOW_VALIDATION = "Field: {name} - Message: {msg} - Value: {value}"

# Komunikat braku nagłówka w get_principal; po nim handler rozpoznaje „puste” uwierzytelnienie (C4).
MSG_AUTH_HEADER_MISSING = "Authorization header missing"
# Koperty uwierzytelnienia shimu v0.24 — dosłownie ze złota v0.24.0 (HTTP 200, data:false).
MSG_V024_AUTH_EMPTY = "`Authorization` can't be empty"
MSG_V024_AUTH_INVALID = "Authentication error: API key is invalid!"
