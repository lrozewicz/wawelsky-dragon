"""Testy mapowania wyjątków SDK i httpx2 na błędy LLM (kontrakt C3, K5 §3.4)."""

import httpx2
import openai
import pytest

from app.core.errors import UpstreamError
from app.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMError,
    LLMRateLimited,
    LLMUnavailable,
    map_http_error,
    map_sdk_error,
)

MODEL = "m"
_REQ = httpx2.Request("POST", "http://x/v1/chat/completions")


def _resp(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=_REQ, json={})


def _not_found(body: object) -> openai.NotFoundError:
    return openai.NotFoundError("nf", response=httpx2.Response(404, request=_REQ), body=body)


def _mapped_errors() -> list[LLMError]:
    return [
        map_sdk_error(openai.APITimeoutError(request=_REQ), MODEL),
        map_sdk_error(openai.APIConnectionError(request=_REQ), MODEL),
        map_sdk_error(openai.RateLimitError("rl", response=_resp(429), body=None), MODEL),
        map_sdk_error(openai.AuthenticationError("a", response=_resp(401), body=None), MODEL),
        map_sdk_error(openai.PermissionDeniedError("p", response=_resp(403), body=None), MODEL),
        map_sdk_error(openai.InternalServerError("i", response=_resp(500), body=None), MODEL),
        map_sdk_error(_not_found({"code": "model_not_found"}), MODEL),
        map_sdk_error(openai.BadRequestError("b", response=_resp(400), body=None), MODEL),
        map_sdk_error(_not_found(None), MODEL),
        map_sdk_error(openai.UnprocessableEntityError("u", response=_resp(422), body=None), MODEL),
        map_sdk_error(openai.ConflictError("c", response=_resp(409), body=None), MODEL),
        map_sdk_error(openai.APIStatusError("s", response=_resp(503), body=None), MODEL),
        map_sdk_error(openai.APIResponseValidationError(response=_resp(200), body=None), MODEL),
        map_http_error(httpx2.ReadTimeout("t", request=_REQ), MODEL),
        map_http_error(httpx2.ConnectError("c", request=_REQ), MODEL),
        map_http_error(httpx2.HTTPStatusError("x", request=_REQ, response=_resp(429)), MODEL),
        map_http_error(httpx2.HTTPStatusError("x", request=_REQ, response=_resp(401)), MODEL),
        map_http_error(httpx2.HTTPStatusError("x", request=_REQ, response=_resp(400)), MODEL),
        map_http_error(httpx2.HTTPStatusError("x", request=_REQ, response=_resp(500)), MODEL),
    ]


@pytest.mark.parametrize("err", _mapped_errors())
def test_upstream_shape(err: LLMError) -> None:
    # wartości dziedziczone z UpstreamError (K3: 105 / 502) — bez nadpisywania.
    assert isinstance(err, UpstreamError)
    assert err.code == UpstreamError.code
    assert err.http_status == UpstreamError.http_status


def test_transient_flags() -> None:
    assert LLMError.transient is False
    assert LLMUnavailable.transient is True
    assert LLMRateLimited.transient is True
    assert LLMAuthError.transient is False
    assert LLMBadRequest.transient is False


def test_timeout_error() -> None:
    err = map_sdk_error(openai.APITimeoutError(request=_REQ), MODEL)
    assert type(err) is LLMUnavailable
    assert err.transient is True
    assert err.details == {"model": MODEL, "status": None}


def test_connection_error() -> None:
    err = map_sdk_error(openai.APIConnectionError(request=_REQ), MODEL)
    assert type(err) is LLMUnavailable
    assert err.transient is True
    assert err.details == {"model": MODEL, "status": None}


def test_rate_limited() -> None:
    exc = openai.RateLimitError("rate limited", response=_resp(429), body=None)
    err = map_sdk_error(exc, MODEL)
    assert type(err) is LLMRateLimited
    assert err.transient is True
    assert err.details == {"model": MODEL, "status": 429}


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (openai.AuthenticationError("a", response=_resp(401), body=None), 401),
        (openai.PermissionDeniedError("p", response=_resp(403), body=None), 403),
    ],
)
def test_auth_error(exc: openai.OpenAIError, status: int) -> None:
    err = map_sdk_error(exc, MODEL)
    assert type(err) is LLMAuthError
    assert err.transient is False
    assert err.message.startswith("Please set LLM API-Key")
    assert err.details == {"model": MODEL, "status": status}


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (openai.InternalServerError("i", response=_resp(500), body=None), 500),
        (openai.APIStatusError("s", response=_resp(503), body=None), 503),
    ],
)
def test_server_error(exc: openai.OpenAIError, status: int) -> None:
    err = map_sdk_error(exc, MODEL)
    assert type(err) is LLMUnavailable
    assert err.transient is True
    assert err.details == {"model": MODEL, "status": status}


def test_model_not_found() -> None:
    err = map_sdk_error(_not_found({"code": "model_not_found"}), MODEL)
    assert type(err) is LLMBadRequest
    assert err.transient is False
    assert err.message == "model not found: m"
    assert err.details == {"model": MODEL, "status": 404}


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (openai.BadRequestError("b", response=_resp(400), body=None), 400),
        (_not_found(None), 404),
        (openai.UnprocessableEntityError("u", response=_resp(422), body=None), 422),
        (openai.ConflictError("c", response=_resp(409), body=None), 409),
    ],
)
def test_bad_request_family(exc: openai.OpenAIError, status: int) -> None:
    err = map_sdk_error(exc, MODEL)
    assert type(err) is LLMBadRequest
    assert err.transient is False
    assert err.details == {"model": MODEL, "status": status}


def test_response_validation_error() -> None:
    err = map_sdk_error(openai.APIResponseValidationError(response=_resp(200), body=None), MODEL)
    assert type(err) is LLMUnavailable
    assert err.details == {"model": MODEL, "status": None}


def test_http_read_timeout() -> None:
    err = map_http_error(httpx2.ReadTimeout("t", request=_REQ), MODEL)
    assert type(err) is LLMUnavailable
    assert err.details == {"model": MODEL, "status": None}


def test_http_connect_error() -> None:
    err = map_http_error(httpx2.ConnectError("c", request=_REQ), MODEL)
    assert type(err) is LLMUnavailable
    assert err.details == {"model": MODEL, "status": None}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, LLMRateLimited),
        (401, LLMAuthError),
        (403, LLMAuthError),
        (400, LLMBadRequest),
        (422, LLMBadRequest),
        (500, LLMUnavailable),
        (503, LLMUnavailable),
    ],
)
def test_http_status_error(status: int, expected: type[LLMError]) -> None:
    err = map_http_error(httpx2.HTTPStatusError("x", request=_REQ, response=_resp(status)), MODEL)
    assert type(err) is expected
    assert err.details == {"model": MODEL, "status": status}
