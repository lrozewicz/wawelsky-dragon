"""Testy kodów błędów, hierarchii WDError i api_space (kontrakt C3, C4, K3)."""

import pytest

from app.core.error_codes import RetCode
from app.core.errors import (
    AuthenticationFailed,
    Busy,
    Conflict,
    EmbeddingModelRequired,
    EmbeddingModelUnknown,
    ExportExpired,
    ExportInProgress,
    Forbidden,
    ImportNotReady,
    InvalidSignature,
    NameConflict,
    NotFound,
    OffsetMismatch,
    OperationNotAllowed,
    PackageTooLarge,
    PermissionDenied,
    RateLimited,
    Unauthorized,
    UpstreamError,
    ValidationFailed,
    WDError,
    api_space,
)

_RETCODE_COUNT = 16

_SUBCLASSES: tuple[type[WDError], ...] = (
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
    Forbidden,
    ExportInProgress,
    OffsetMismatch,
    ImportNotReady,
    NameConflict,
    EmbeddingModelRequired,
    EmbeddingModelUnknown,
    InvalidSignature,
    ExportExpired,
    PackageTooLarge,
)


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        (RetCode.ARGUMENT_ERROR, 101),
        (RetCode.AUTHENTICATION_ERROR, 109),
        (RetCode.SERVER_ERROR, 500),
    ],
)
def test_retcode_values(member: RetCode, expected: int) -> None:
    assert member == expected


def test_retcode_member_count() -> None:
    assert len(RetCode) == _RETCODE_COUNT


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (ValidationFailed, (101, 400, "validation_failed")),
        (NotFound, (102, 404, "not_found")),
        (Conflict, (102, 409, "conflict")),
        (PermissionDenied, (108, 403, "permission_denied")),
        (AuthenticationFailed, (109, 401, "authentication_failed")),
        (Unauthorized, (401, 401, "unauthorized")),
        (OperationNotAllowed, (103, 409, "operation_not_allowed")),
        (UpstreamError, (105, 502, "upstream_error")),
        (Busy, (106, 409, "busy")),
        (RateLimited, (429, 429, "rate_limited")),
        # E7-1f T5: mapa slug → HTTP tras eksportu/importu (K19 §3 tabela kodów, CONTRACT §7).
        (Forbidden, (403, 403, "forbidden")),
        (ExportInProgress, (409, 409, "export_in_progress")),
        (OffsetMismatch, (409, 409, "offset_mismatch")),
        (ImportNotReady, (409, 409, "import_not_ready")),
        (NameConflict, (409, 409, "name_conflict")),
        (EmbeddingModelRequired, (400, 400, "embedding_model_required")),
        (EmbeddingModelUnknown, (400, 400, "embedding_model_unknown")),
        (InvalidSignature, (403, 403, "invalid_signature")),
        (ExportExpired, (410, 410, "export_expired")),
        (PackageTooLarge, (413, 413, "package_too_large")),
    ],
)
def test_subclass_attributes(cls: type[WDError], expected: tuple[int, int, str]) -> None:
    assert (cls.code, cls.http_status, cls.slug) == expected


@pytest.mark.parametrize("cls", _SUBCLASSES)
def test_subclasses_inherit_directly(cls: type[WDError]) -> None:
    assert cls.__bases__ == (WDError,)


def test_wderror_defaults() -> None:
    assert (WDError.code, WDError.http_status, WDError.slug) == (100, 500, "internal_error")


def test_not_found_instance() -> None:
    e = NotFound("no doc", details={"id": "x"})
    assert e.message == "no doc"
    assert e.details == {"id": "x"}
    assert str(e) == "no doc"
    assert isinstance(e, Exception)


def test_conflict_details_default() -> None:
    assert Conflict("c").details is None


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/dify/retrieval", "ragflow-dify"),
        ("/api/v1/openai/x/chat/completions", "ragflow-openai"),
        ("/api/v1/datasets", "ragflow"),
        ("/v1/conversation/set", "ragflow"),
        ("/api/wd/v1/users", "wd"),
        ("/health/live", "wd"),
        ("/api/users", "hub_compat"),
        ("/api/users/5/keys", "hub_compat"),
        ("/user-api/api/users", "hub_compat"),
        ("/sharepoint-sync-api/api/integrations/1", "hub_compat"),
        ("/api/usersx", "default"),
        ("/api/datasets", "hub_compat"),
        ("/", "default"),
        ("/health", "default"),
    ],
)
def test_api_space(path: str, expected: str) -> None:
    assert api_space(path) == expected
