"""Trasy `/api/users*` powierzchni hub-compat z audytem (kontrakt C7 i C8; AG-01…AG-07)."""

from collections.abc import Mapping
from typing import cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import client_ip, container_of
from app.api.hub_compat.envelope import data
from app.api.hub_compat.parsing import actor_of, body_of, email_of_path, require_str
from app.api.hub_compat.route import SvcRoute
from app.api.hub_compat.security import require_secret
from app.api.hub_compat.views import changes_message, user_detail, user_item
from app.core.errors import NotFound, ValidationFailed
from app.services.audit import AuditService
from app.services.users import UserService

router = APIRouter(
    route_class=SvcRoute,
    include_in_schema=False,
    dependencies=[Depends(require_secret)],
)

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]
_CREATED = 201
_CREATE_FIELDS_MESSAGE = "email and password are required"
_ROLE_MESSAGE = 'role must be "user" or "admin"'
_PASSWORD_MESSAGE = "new_password is required"  # noqa: S105 — to komunikat, nie sekret
_NOT_FOUND_MESSAGE = "Not found"


def _users(request: Request) -> UserService:
    """Usługa użytkowników z kontenera żądania (C7)."""
    return cast(UserService, container_of(request).users)


async def _record(
    request: Request,
    body: Mapping[str, object],
    *,
    action: str,
    target_id: str,
    details: dict[str, object] | None = None,
) -> None:
    """Wpis audytu po udanej mutacji; aktor z body albo `X-API-Secret`, ip klienta (C8)."""
    await cast(AuditService, container_of(request).audit).record(
        actor_label=actor_of(body),
        action=action,
        target_type="user",
        target_id=target_id,
        details=details,
        ip=client_ip(request),
    )


def _bool_field(body: Mapping[str, object], name: str) -> bool | None:
    """Opcjonalna flaga bool: brak pola → None, jawne `null`/inny typ → 400 (C8).

    Pole **nieobecne** znaczy „brak zmiany"; jawne `null` jest wartością żądania i musi
    zostać odrzucone komunikatem, a nie po cichu zignorowane (poprawka T5b(b)).
    """
    if name not in body:
        return None
    value = body[name]
    if not isinstance(value, bool):
        raise ValidationFailed(f"{name} must be a boolean")
    return value


def _nickname_field(body: Mapping[str, object]) -> str | None:
    """Opcjonalny `nickname`: brak pola → None, nie-string (także `null`) → 400 (C8)."""
    if "nickname" not in body:
        return None
    value = body["nickname"]
    if not isinstance(value, str):
        raise ValidationFailed("nickname must be a string")
    return value


@router.get("/api/users")
async def list_users(request: Request) -> JSONResponse:
    """Lista kont jako `user_item` (C8; AG-01)."""
    rows = await _users(request).list_all()
    return data([user_item(row) for row in rows])


@router.post("/api/users")
async def create_user(request: Request) -> JSONResponse:
    """Zakłada konto (`user_created`); brak e-maila/hasła → 400, kolizja → 409 (C8)."""
    body = await body_of(request)
    email = require_str(body, "email", _CREATE_FIELDS_MESSAGE)
    password = require_str(body, "password", _CREATE_FIELDS_MESSAGE)
    role = body.get("role")
    if role is not None and role not in ("user", "admin"):
        raise ValidationFailed(_ROLE_MESSAGE)
    super_flag = role == "admin"
    user = await _users(request).create_managed(
        email=email,
        password=password,
        nickname=_nickname_field(body),
        is_superuser=super_flag,
    )
    await _record(request, body, action="user_created", target_id=user.id)
    return data(user_detail(user), status=_CREATED)


@router.get("/api/users/{email}")
async def get_user(request: Request, email: str) -> JSONResponse:
    """Konto po e-mailu ze ścieżki; brak → 404 `User not found` (C8; AG-02)."""
    row = await _users(request).require_by_email(email_of_path(email))
    return data(user_detail(row))


@router.put("/api/users/{email}/password")
async def set_password(request: Request, email: str) -> JSONResponse:
    """Ustawia hasło (`user_password_set`); brak `new_password` → 400 (C8)."""
    body = await body_of(request)
    new_password = require_str(body, "new_password", _PASSWORD_MESSAGE)
    target = email_of_path(email)
    await _users(request).set_password_by_email(target, new_password)
    await _record(
        request,
        body,
        action="user_password_set",
        target_id=target,
        details={"email": target},
    )
    return data({"message": "Password changed"})


@router.put("/api/users/{email}/activate")
async def activate_user(request: Request, email: str) -> JSONResponse:
    """Aktywuje konto (`user_activated`); trasa bez ciała → aktor `X-API-Secret` (C8)."""
    target = email_of_path(email)
    await _users(request).set_active_by_email(target, True)
    await _record(request, {}, action="user_activated", target_id=target)
    return data({"message": "User activated"})


@router.put("/api/users/{email}/deactivate")
async def deactivate_user(request: Request, email: str) -> JSONResponse:
    """Dezaktywuje konto (`user_deactivated`); ochrona ostatniego admina w usłudze (C8)."""
    target = email_of_path(email)
    await _users(request).set_active_by_email(target, False)
    await _record(request, {}, action="user_deactivated", target_id=target)
    return data({"message": "User deactivated"})


@router.put("/api/users/{email}")
async def update_user(request: Request, email: str) -> JSONResponse:
    """Zmienia nickname/flagi (`user_updated` przy zmianach); złe typy → 400 (C8)."""
    body = await body_of(request)
    nickname = _nickname_field(body)
    active = _bool_field(body, "is_active")
    super_value = _bool_field(body, "is_superuser")
    target = email_of_path(email)
    changes = await _users(request).update_managed(
        target,
        nickname=nickname,
        is_active=active,
        is_superuser=super_value,
    )
    if changes:
        await _record(
            request,
            body,
            action="user_updated",
            target_id=target,
            details={"email": target, "changes": changes},
        )
    message = changes_message(changes, active=active, super_value=super_value)
    return data({"message": message})


@router.delete("/api/users/{email}")
async def delete_user(request: Request, email: str) -> JSONResponse:
    """Usuwa konto (`user_deleted` z licznikami zasobów); ostatni admin → 400 (C8)."""
    body = await body_of(request)
    result = await _users(request).delete_managed(email_of_path(email))
    await _record(
        request,
        body,
        action="user_deleted",
        target_id=result.user_id,
        details={
            "email": result.email,
            "mode": result.mode,
            "transferred_to": result.transferred_to,
            "moved": result.moved,
            "deleted": result.deleted,
        },
    )
    return data({"message": "User deleted"})


@router.api_route("/api/users/{rest:path}", methods=_METHODS)
async def users_fallback(rest: str) -> JSONResponse:
    """Nieznana podtrasa users → 404 `{"error": "Not found"}` (C7).

    Zdefiniowana **po** trasach konkretnych — dopasowanie idzie po kolejności deklaracji.
    """
    raise NotFound(_NOT_FOUND_MESSAGE)
