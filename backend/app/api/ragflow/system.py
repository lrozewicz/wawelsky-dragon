"""Trasy system RAGFlow: config i klucze API /system/tokens (kontrakt C9, 07 §5.2)."""

from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.system import ApiToken, CreatedApiToken, SystemConfig
from app.api.ragflow.user_view import fmt_date
from app.core.errors import ValidationFailed
from app.services.api_keys import ApiKeyService, ApiKeyView

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Długość pola beta (upstream: losowy ciąg 32 znaków z generate_confirmation_token).
BETA_LEN = 32

# Limit nazwy klucza API (K21 §5 p. 1): po strip() najwyżej 128 znaków.
MAX_TOKEN_NAME_LEN = 128
MSG_TOKEN_NAME_TOO_LONG = "Token name must be at most 128 characters."  # noqa: S105 — komunikat, nie sekret


def token_dict(view: ApiKeyView) -> dict[str, object]:
    """Widok klucza z listy → słownik C9; tenant_id = id właściciela (złoto system--07.json).

    ``name`` (K20 §1) to nazwa zapisana przy tworzeniu albo ``None``.
    """
    return {
        "token": view.token,
        "tenant_id": view.user_id,
        "name": view.name,
        "dialog_id": view.dialog_id,
        "source": view.source,
        "beta": view.token[-BETA_LEN:],
        "create_time": view.create_time,
        "create_date": fmt_date(view.create_time),
        "update_time": view.update_time,
        "update_date": fmt_date(view.update_time),
    }


def created_token_dict(view: ApiKeyView) -> dict[str, object]:
    """Świeżo utworzony klucz → słownik C9 (złoto system--08.json).

    Upstream ``system_api.py:new_token`` buduje słownik ręcznie: bez ``dialog_id``/``source``
    i bez znaczników UPDATE (null) — inaczej niż lista, która oddaje wiersz z bazy.
    ``name`` (K20 §1) odbija nazwę przy tworzeniu albo ``None``.
    """
    return {
        "token": view.token,
        "tenant_id": view.user_id,
        "name": view.name,
        "beta": view.token[-BETA_LEN:],
        "create_time": view.create_time,
        "create_date": fmt_date(view.create_time),
        "update_time": None,
        "update_date": None,
    }


@router.get(
    "/config",
    operation_id="system_config",
    responses={200: {"model": RagflowOk[SystemConfig]}},
)
async def config(request: Request) -> JSONResponse:
    """Flagi publiczne instancji: rejestracja i login hasłem (C9, 07 §3.4, złoto system--03).

    Dwa klucze jak w upstreamie (system_api.py:get_config) i 07 §3.4; brak OIDC w tym miejscu —
    o dostępnych kanałach logowania mówi GET /auth/login/channels (C9).
    registerEnabled jako liczba (upstream REGISTER_ENABLED = 1/0), nie bool.
    """
    settings = container_of(request).settings
    return JSONResponse(
        {
            "code": 0,
            "message": "success",
            "data": {
                "registerEnabled": int(settings.register_enabled),
                "disablePasswordLogin": not settings.password_login_enabled,
            },
        }
    )


@router.get(
    "/tokens",
    operation_id="system_tokens_list",
    responses={200: {"model": RagflowOk[list[ApiToken]]}},
)
async def list_tokens(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Aktywne klucze API właściciela z pełnym tokenem (C9, 07 §5.2)."""
    keys = cast(ApiKeyService, container_of(request).api_keys)
    views = await keys.list_full(principal)
    return JSONResponse(
        {"code": 0, "message": "success", "data": [token_dict(view) for view in views]}
    )


@router.post(
    "/tokens",
    operation_id="system_tokens_create",
    responses={200: {"model": RagflowOk[CreatedApiToken]}},
    openapi_extra=extra_doc(
        query=[query_param("name", {"type": "string"}, "Nazwa nowego klucza API (C9)")]
    ),
)
async def create_token(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Nowy klucz API; opcjonalna nazwa z query (C9, 07 §5.2).

    Nazwa przycinana z odstępów (K20 §1); pusta/bez nazwy → ``None``.
    """
    keys = cast(ApiKeyService, container_of(request).api_keys)
    name = (request.query_params.get("name") or "").strip() or None
    if name is not None and len(name) > MAX_TOKEN_NAME_LEN:
        raise ValidationFailed(MSG_TOKEN_NAME_TOO_LONG)
    view = await keys.create(principal, name=name)
    return JSONResponse({"code": 0, "message": "success", "data": created_token_dict(view)})


@router.delete(
    "/tokens/{token:path}",
    operation_id="system_tokens_delete",
    responses={200: {"model": RagflowOk[bool]}},
)
async def delete_token(token: str, request: Request, principal: PrincipalDep) -> JSONResponse:
    """Unieważnienie po tokenie/id/prefixu; wynik ignorowany, zawsze data true (C9, upstream)."""
    keys = cast(ApiKeyService, container_of(request).api_keys)
    await keys.delete(principal, token)
    return JSONResponse({"code": 0, "message": "success", "data": True})
