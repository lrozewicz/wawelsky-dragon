"""Trasy użytkowników RAGFlow: rejestracja, profil /users/me (kontrakt C9, 07 §3.4 i §6.3)."""

from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, client_ip, container_of, json_body
from app.api.ragflow.auth import session_response
from app.api.ragflow.envelope import ok
from app.api.ragflow.schemas.auth import SessionUser, User
from app.api.ragflow.schemas.common import RagflowOk, extra_doc
from app.api.ragflow.schemas.users import (
    DefaultModels,
    RegisterRequest,
    UpdateDefaultModelsRequest,
    UpdateMeRequest,
)
from app.api.ragflow.user_view import user_safe_dict
from app.core.errors import ValidationFailed
from app.services.auth import AuthService
from app.services.default_models import DefaultModelsService
from app.services.users import UserService

router = APIRouter(prefix="/api/v1/users", tags=["users"])

# Kolejność brakujących pól jak upstream user_api.py (komunikat kodu 101).
_REQUIRED_FIELDS = ("nickname", "email", "password")


@router.post(
    "",
    operation_id="users_register",
    description=(
        "Błąd logowania/rejestracji: HTTP 200, code 109/403 (login) albo 103 "
        "(rejestracja wyłączona), `data: false`."
    ),
    responses={200: {"model": RagflowOk[SessionUser]}},
    openapi_extra=extra_doc(RegisterRequest),
)
async def register(request: Request) -> JSONResponse:
    """Rejestracja lokalna; po rejestracji od razu sesja jak po loginie (C9, rozstrzygnięcie R9)."""
    body = await json_body(request)
    container = container_of(request)
    missing = [field for field in _REQUIRED_FIELDS if not body.get(field)]
    if missing:
        raise ValidationFailed(f"required argument are missing: {','.join(missing)}; ")
    if not container.settings.register_enabled:
        return JSONResponse(
            {"code": 103, "message": "User registration is disabled!", "data": False}
        )
    user = await cast(UserService, container.users).register(
        email=cast(str, body["email"]),
        nickname=cast(str, body["nickname"]),
        password=cast(str, body["password"]),
    )
    tokens = await cast(AuthService, container.auth).start_session(
        user.id, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return session_response(tokens, f"{user.nickname}, welcome aboard!", request)


@router.get(
    "/me",
    operation_id="users_me_get",
    responses={200: {"model": RagflowOk[User]}},
)
async def get_me(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Profil bieżącego użytkownika jako user_safe_dict (C9, 07 §6.3)."""
    user = await cast(UserService, container_of(request).users).get(principal.user_id)
    return JSONResponse({"code": 0, "message": "success", "data": user_safe_dict(user)})


@router.patch(
    "/me",
    operation_id="users_me_update",
    responses={200: {"model": RagflowOk[bool]}},
    openapi_extra=extra_doc(UpdateMeRequest, required=False),
)
async def patch_me(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Zmiana profilu; niepuste hasła w body → zmiana hasła przed profilem (C9, 07 §6.3)."""
    body = await json_body(request)
    users = cast(UserService, container_of(request).users)
    password = body.get("password")
    new_password = body.get("new_password")
    if password or new_password:
        await users.change_password(
            principal, cast("str | None", password), cast(str, new_password or "")
        )
    await users.update_profile(principal, body)
    return JSONResponse({"code": 0, "message": "success", "data": True})


@router.get(
    "/me/models",
    operation_id="users_me_models_get",
    responses={200: {"model": RagflowOk[DefaultModels]}},
)
async def get_my_models(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Domyślne modele instancji (C10)."""
    return ok(await DefaultModelsService(container_of(request)).get())


@router.patch(
    "/me/models",
    operation_id="users_me_models_update",
    responses={200: {"model": RagflowOk[DefaultModels]}},
    openapi_extra=extra_doc(UpdateDefaultModelsRequest, required=False),
)
async def patch_my_models(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Ustawienie globalnego modelu domyślnego; tylko superuser przez policy (C10)."""
    body = await json_body(request)
    return ok(await DefaultModelsService(container_of(request)).set(principal, body))
