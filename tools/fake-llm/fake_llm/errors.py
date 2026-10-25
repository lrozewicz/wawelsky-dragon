"""Błędy w formacie OpenAI (`{"error": {...}}`) i handler FastAPI (C2)."""

from typing import cast

from fastapi import Request
from fastapi.responses import JSONResponse


class OpenAIError(Exception):
    """Błąd zwracany klientowi w formacie OpenAI: status, treść `error` i opcjonalne nagłówki."""

    def __init__(
        self,
        status: int,
        error: dict[str, object],
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(str(error.get("message", "")))
        self.status = status
        self.error = error
        self.headers = headers


def model_not_found(model: str) -> OpenAIError:
    """404 dla nieznanego modelu (K10 §2)."""
    return OpenAIError(
        404,
        {
            "message": f"The model '{model}' does not exist",
            "type": "invalid_request_error",
            "param": "model",
            "code": "model_not_found",
        },
    )


def unsupported_params_error(model: str, params: list[str]) -> OpenAIError:
    """400 dla modelu strict: komunikat LiteLLM o parametrach (K10, poprawka 2026-10-04)."""
    listing = ", ".join(f"'{param}'" for param in params)
    message = (
        f"litellm.UnsupportedParamsError: openai does not support parameters: [{listing}], "
        f"for model={model}. To drop these, set `litellm.drop_params=True` or for proxy:"
        "\n\n`litellm_settings:\n drop_params: true`\n"
    )
    return OpenAIError(
        400,
        {
            "message": message,
            "type": "invalid_request_error",
            "param": None,
            "code": "400",
        },
    )


async def openai_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Zamienia OpenAIError na odpowiedź JSON w formacie OpenAI."""
    err = cast(OpenAIError, exc)
    return JSONResponse(
        status_code=err.status,
        content={"error": err.error},
        headers=err.headers,
    )
