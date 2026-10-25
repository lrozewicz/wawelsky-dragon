"""Trasy `/api/keys*` powierzchni hub-compat z audytem (kontrakt C7 i C8; AG-08…AG-11)."""

from collections.abc import Mapping
from typing import cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import client_ip, container_of
from app.api.hub_compat.envelope import data
from app.api.hub_compat.parsing import actor_of, email_of_path
from app.api.hub_compat.route import SvcRoute
from app.api.hub_compat.security import require_secret
from app.api.hub_compat.views import key_record
from app.core.errors import NotFound, ValidationFailed
from app.services.api_keys import ApiKeyService, CompatProfileValue
from app.services.audit import AuditService
from app.services.users import UserService

router = APIRouter(
    route_class=SvcRoute,
    include_in_schema=False,
    dependencies=[Depends(require_secret)],
)

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]
_CREATED = 201
_NO_EMAIL_MESSAGE = "email is required in path"
_NOT_FOUND_MESSAGE = "Not found"
_KEY_NOT_FOUND_MESSAGE = "Key not found"
# Klucze tworzy hub-compat, który mówi v0.24 (K7 §1.12).
_COMPAT_PROFILE: CompatProfileValue = "ragflow_0_24"


def _users(request: Request) -> UserService:
    """Usługa użytkowników z kontenera żądania (C7)."""
    return cast(UserService, container_of(request).users)


def _keys(request: Request) -> ApiKeyService:
    """Usługa kluczy z kontenera żądania (C7)."""
    return cast(ApiKeyService, container_of(request).api_keys)


async def _record(
    request: Request,
    body: Mapping[str, object],
    *,
    action: str,
    target_id: str,
    details: dict[str, object],
) -> None:
    """Wpis audytu po udanej mutacji; aktor z body albo `X-API-Secret`, ip klienta (C8)."""
    await cast(AuditService, container_of(request).audit).record(
        actor_label=actor_of(body),
        action=action,
        target_type="api_key",
        target_id=target_id,
        details=details,
        ip=client_ip(request),
    )


@router.get("/api/keys/{email}")
async def list_keys(request: Request, email: str) -> JSONResponse:
    """Klucze konta z pełnym tokenem; brak konta → 404 `User not found` (C8; AG-08)."""
    users = _users(request)
    user = await users.require_by_email(email_of_path(email))
    views = await _keys(request).list_full(users.principal_of(user))
    return data([key_record(view) for view in views])


@router.post("/api/keys/{email}")
async def create_key(request: Request, email: str) -> JSONResponse:
    """Nowy klucz v0.24 (`api_key_created`); token jawny tylko w wyniku (C8; AG-09)."""
    users = _users(request)
    target = email_of_path(email)
    user = await users.require_by_email(target)
    view = await _keys(request).create(users.principal_of(user), compat_profile=_COMPAT_PROFILE)
    await _record(
        request,
        {},
        action="api_key_created",
        target_id=view.id,
        details={"email": target, "prefix": view.prefix},
    )
    return data(key_record(view), status=_CREATED)


@router.delete("/api/keys/{email}/{token}")
async def delete_key(request: Request, email: str, token: str) -> JSONResponse:
    """Unieważnia klucz (`api_key_deleted`); nieznany/cudzy → 404 `Key not found` (C8).

    Audyt wskazuje **id klucza** (K7 §5 p. 2), nie id użytkownika — stąd ``revoke``.
    """
    users = _users(request)
    target = email_of_path(email)
    user = await users.require_by_email(target)
    revoked = await _keys(request).revoke(users.principal_of(user), token)
    if revoked is None:
        raise NotFound(_KEY_NOT_FOUND_MESSAGE)
    await _record(
        request,
        {},
        action="api_key_deleted",
        target_id=revoked,
        details={"email": target},
    )
    return data({"message": "Key deleted"})


@router.api_route("/api/keys", methods=_METHODS)
async def keys_without_email() -> JSONResponse:
    """`/api/keys` bez e-maila w ścieżce → 400 `email is required in path` (C7)."""
    raise ValidationFailed(_NO_EMAIL_MESSAGE)


@router.api_route("/api/keys/{rest:path}", methods=_METHODS)
async def keys_fallback(rest: str) -> JSONResponse:
    """Nieznana podtrasa keys → 404 `{"error": "Not found"}` (C7).

    Zdefiniowana **po** trasach konkretnych — dopasowanie idzie po kolejności deklaracji.
    """
    raise NotFound(_NOT_FOUND_MESSAGE)
