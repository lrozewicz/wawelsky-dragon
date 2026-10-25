"""Hierarchia wyjątków domeny i przestrzenie API (kontrakt C4, K3 §2-§3)."""

from typing import Literal

from app.core.error_codes import RetCode


class WDError(Exception):
    """Bazowy wyjątek domeny: kod RAGFlow, status HTTP i slug koperty wd."""

    code: int = RetCode.EXCEPTION_ERROR
    http_status: int = 500
    slug: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


# Podklasy dziedziczą bezpośrednio po WDError i nadpisują tylko atrybuty klasowe (wartości z K3 §2).
class ValidationFailed(WDError):
    code = RetCode.ARGUMENT_ERROR
    http_status = 400
    slug = "validation_failed"


class NotFound(WDError):
    code = RetCode.DATA_ERROR
    http_status = 404
    slug = "not_found"


class ResourceNotFound(WDError):
    """Nie znaleziono zasobu (kod RAGFlow 404, K3 §1).

    Przestrzeń ``ragflow-dify`` zwraca wtedy prawdziwy HTTP 404 (K3 §3 tabela jedynek),
    a nie kopertę 200/102 używaną przez trasy ragflow (``NotFound``).
    """

    code = RetCode.NOT_FOUND
    http_status = 404
    slug = "not_found"


class Conflict(WDError):
    code = RetCode.DATA_ERROR
    http_status = 409
    slug = "conflict"


class PermissionDenied(WDError):
    code = RetCode.PERMISSION_ERROR
    http_status = 403
    slug = "permission_denied"


class AuthenticationFailed(WDError):
    code = RetCode.AUTHENTICATION_ERROR
    http_status = 401
    slug = "authentication_failed"


class Unauthorized(WDError):
    code = RetCode.UNAUTHORIZED
    http_status = 401
    slug = "unauthorized"


class OperationNotAllowed(WDError):
    code = RetCode.OPERATING_ERROR
    http_status = 409
    slug = "operation_not_allowed"


class UpstreamError(WDError):
    code = RetCode.CONNECTION_ERROR
    http_status = 502
    slug = "upstream_error"


class Forbidden(WDError):
    """Brak uprawnienia do zasobu z jawnym slugiem ``forbidden`` (K19 §Uprawnienia).

    ``PermissionDenied`` (E0) ma slug ``permission_denied`` i obsługuje trasy ragflow;
    przestrzeń WD deklaruje w kontrakcie slug ``forbidden`` (K19 §3 tabela kodów).
    """

    code = RetCode.FORBIDDEN
    http_status = 403
    slug = "forbidden"


class Busy(WDError):
    code = RetCode.RUNNING
    http_status = 409
    slug = "busy"


class RateLimited(WDError):
    code = 429
    http_status = 429
    slug = "rate_limited"


# Wyjątki powierzchni eksportu/importu paczki .wdkb (K19 §3, CONTRACT E7-1f §7).
# ``code`` to kod RAGFlow dla przestrzeni ragflow-*; koperta WD niesie wyłącznie ``slug``
# (``app/api/errors.py``), więc dla statusów bez odpowiednika w ``RetCode`` używamy HTTP.
class ExportInProgress(WDError):
    code = RetCode.CONFLICT
    http_status = 409
    slug = "export_in_progress"


class OffsetMismatch(WDError):
    code = RetCode.CONFLICT
    http_status = 409
    slug = "offset_mismatch"


class ImportNotReady(WDError):
    code = RetCode.CONFLICT
    http_status = 409
    slug = "import_not_ready"


class NameConflict(WDError):
    code = RetCode.CONFLICT
    http_status = 409
    slug = "name_conflict"


class EmbeddingModelRequired(WDError):
    code = RetCode.BAD_REQUEST
    http_status = 400
    slug = "embedding_model_required"


class EmbeddingModelUnknown(WDError):
    code = RetCode.BAD_REQUEST
    http_status = 400
    slug = "embedding_model_unknown"


class InvalidSignature(WDError):
    code = RetCode.FORBIDDEN
    http_status = 403
    slug = "invalid_signature"


class ExportExpired(WDError):
    code = 410
    http_status = 410
    slug = "export_expired"


class PackageTooLarge(WDError):
    code = 413
    http_status = 413
    slug = "package_too_large"


ApiSpace = Literal["ragflow-dify", "ragflow-openai", "ragflow", "wd", "hub_compat", "default"]

# Prefiksy ścieżek wg tabeli K3 §3 (sprawdzana od góry, pierwsze dopasowanie wygrywa).
_DIFY_PREFIXES: tuple[str, ...] = ("/api/v1/dify/retrieval",)
_OPENAI_PREFIXES: tuple[str, ...] = ("/api/v1/openai/", "/api/v1/chats_openai/")
_RAGFLOW_PREFIXES: tuple[str, ...] = ("/api/v1/", "/v1/")
_WD_PREFIXES: tuple[str, ...] = ("/api/wd/v1/", "/health/")
_HUB_COMPAT_ROOTS: tuple[str, ...] = ("", "/user-api", "/sharepoint-sync-api")
_HUB_COMPAT_BASES: tuple[str, ...] = (
    "/api/users",
    "/api/keys",
    "/api/access",
    "/api/integrations",
    "/api/datasets",
    "/api/documents/link",
)


def api_space(path: str) -> ApiSpace:
    """Przestrzeń API dla ścieżki żądania wg tabeli K3 §3."""
    for prefix in _DIFY_PREFIXES:
        if path.startswith(prefix):
            return "ragflow-dify"
    for prefix in _OPENAI_PREFIXES:
        if path.startswith(prefix):
            return "ragflow-openai"
    for prefix in _RAGFLOW_PREFIXES:
        if path.startswith(prefix):
            return "ragflow"
    for prefix in _WD_PREFIXES:
        if path.startswith(prefix):
            return "wd"
    # hub-compat: pełna baza R+B albo ta ścieżka z ukośnikiem (nie łapie np. /api/usersx).
    for root in _HUB_COMPAT_ROOTS:
        for base in _HUB_COMPAT_BASES:
            prefix = root + base
            if path == prefix or path.startswith(prefix + "/"):
                return "hub_compat"
    return "default"
