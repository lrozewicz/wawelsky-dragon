"""Błędy modułu LLM i mapowanie wyjątków SDK/httpx2 (kontrakt C3, K5 §3.4)."""

from typing import ClassVar

import httpx2
import openai

from app.core.errors import UpstreamError
from app.llm.param_retry import error_text, safe_message

_HTTP_BAD_REQUEST_MIN = 400
_HTTP_BAD_REQUEST_MAX = 500
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403


class LLMError(UpstreamError):
    """Baza błędów modułu LLM — kod/HTTP/slug dziedziczone z UpstreamError (105 / 502)."""

    transient: ClassVar[bool] = False


class LLMUnavailable(LLMError):
    """Błąd dostępności: timeout, brak połączenia, 5xx — do retry."""

    transient = True


class LLMRateLimited(LLMError):
    """Limit żądań (429) — do retry."""

    transient = True


class LLMAuthError(LLMError):
    """Brak/niepoprawny klucz API (401/403) — nie do retry."""

    transient = False


class LLMBadRequest(LLMError):
    """Błędne żądanie (4xx inne niż auth/rate limit) — nie do retry."""

    transient = False


def _details(model: str, status: int | None) -> dict[str, object]:
    """Dane diagnostyczne błędu — nigdy klucz API ani treść promptu."""
    return {"model": model, "status": status}


def map_sdk_error(exc: openai.OpenAIError, model: str) -> LLMError:
    """Wyjątek SDK OpenAI → błąd LLM; rozróżnienie po klasach, kolejność sprawdzania wg C3."""
    error: LLMError
    if isinstance(exc, openai.APITimeoutError):
        error = LLMUnavailable("LLM timeout", details=_details(model, None))
    elif isinstance(exc, openai.APIConnectionError):
        error = LLMUnavailable("LLM connection error", details=_details(model, None))
    elif isinstance(exc, openai.RateLimitError):
        error = LLMRateLimited("LLM rate limited", details=_details(model, _HTTP_TOO_MANY_REQUESTS))
    elif isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        error = LLMAuthError(
            f"Please set LLM API-Key (model: {model})",
            details=_details(model, exc.status_code),
        )
    elif isinstance(exc, openai.InternalServerError):
        error = LLMUnavailable("LLM server error", details=_details(model, exc.status_code))
    elif isinstance(exc, openai.NotFoundError) and exc.code == "model_not_found":
        error = LLMBadRequest(f"model not found: {model}", details=_details(model, 404))
    elif isinstance(exc, openai.APIStatusError):
        if _HTTP_BAD_REQUEST_MIN <= exc.status_code < _HTTP_BAD_REQUEST_MAX:
            text = safe_message(error_text(exc))
            message = f"LLM bad request: {text}" if text else "LLM bad request"
            error = LLMBadRequest(message, details=_details(model, exc.status_code))
        else:
            error = LLMUnavailable("LLM server error", details=_details(model, exc.status_code))
    else:
        # każdy inny błąd SDK (np. APIResponseValidationError) — nieprawidłowa odpowiedź bramki
        error = LLMUnavailable("LLM invalid response", details=_details(model, None))
    return error


def map_http_error(exc: httpx2.HTTPError, model: str) -> LLMError:
    """Wyjątek httpx2 (rerank bez SDK) → błąd LLM; kolejność sprawdzania wg C3."""
    if isinstance(exc, httpx2.TimeoutException):
        return LLMUnavailable("LLM timeout", details=_details(model, None))
    if isinstance(exc, httpx2.HTTPStatusError):
        status = exc.response.status_code
        if status == _HTTP_TOO_MANY_REQUESTS:
            return LLMRateLimited("LLM rate limited", details=_details(model, status))
        if status in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
            return LLMAuthError(
                f"Please set LLM API-Key (model: {model})",
                details=_details(model, status),
            )
        if _HTTP_BAD_REQUEST_MIN <= status < _HTTP_BAD_REQUEST_MAX:
            text = safe_message(exc.response.text)
            message = f"LLM bad request: {text}" if text else "LLM bad request"
            return LLMBadRequest(message, details=_details(model, status))
        return LLMUnavailable("LLM server error", details=_details(model, status))
    return LLMUnavailable("LLM connection error", details=_details(model, None))
