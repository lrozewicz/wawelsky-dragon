"""Trasy `/api/access` powierzchni hub-compat (kontrakt C7 i C8; AG-12…AG-17)."""

from typing import cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import client_ip, container_of
from app.api.hub_compat.envelope import MethodNotAllowed, data
from app.api.hub_compat.parsing import actor_of, body_of, require_str
from app.api.hub_compat.route import SvcRoute
from app.api.hub_compat.security import require_secret
from app.core.errors import ValidationFailed
from app.services.access import AccessService
from app.services.audit import AuditService

router = APIRouter(
    route_class=SvcRoute,
    include_in_schema=False,
    dependencies=[Depends(require_secret)],
)

_REPLACE_FIELDS_MESSAGE = "email and dialog_ids (array) are required"
_GRANT_FIELDS_MESSAGE = "email and dialog_id are required"
_CREATED = 201


def _access(request: Request) -> AccessService:
    """Usługa grantów z kontenera żądania (C7)."""
    return cast(AccessService, container_of(request).access)


async def _record(
    request: Request, *, action: str, email: str, actor: str, details: dict[str, object]
) -> None:
    """Wpis audytu po udanej mutacji — aktor z body albo `X-API-Secret`, ip klienta (C8)."""
    await cast(AuditService, container_of(request).audit).record(
        actor_label=actor,
        action=action,
        target_type="access",
        target_id=email,
        details=details,
        ip=client_ip(request),
    )


@router.get("/api/access")
async def list_access(request: Request, email: str | None = None) -> JSONResponse:
    """Granty e-maila: `dialog_ids` oraz `access[{dialog_id, created_by}]` (C8, AG-12)."""
    if not email:
        raise ValidationFailed("email is required")
    entries = await _access(request).get(email)
    return data(
        {
            "dialog_ids": [entry.dialog_id for entry in entries],
            "access": [
                {"dialog_id": entry.dialog_id, "created_by": entry.created_by} for entry in entries
            ],
        }
    )


@router.put("/api/access")
async def replace_access(request: Request) -> JSONResponse:
    """Zastępuje cały zbiór grantów e-maila (`access_replaced`); zły `dialog_ids` → 400."""
    body = await body_of(request)
    email = require_str(body, "email", _REPLACE_FIELDS_MESSAGE).strip().lower()
    dialog_ids = body.get("dialog_ids")
    if not isinstance(dialog_ids, list) or any(
        not isinstance(item, str) or not item for item in dialog_ids
    ):
        raise ValidationFailed(_REPLACE_FIELDS_MESSAGE)
    actor = actor_of(body)
    count = await _access(request).replace(email, dialog_ids, actor)
    await _record(
        request,
        action="access_replaced",
        email=email,
        actor=actor,
        details={"email": email, "count": count, "dialog_ids": dialog_ids},
    )
    return data({"email": email, "count": count})


@router.post("/api/access")
async def grant_access(request: Request) -> JSONResponse:
    """Nadaje grant (idempotentnie, zawsze 201 przy poprawnym wejściu; C8, AG-14)."""
    body = await body_of(request)
    email = require_str(body, "email", _GRANT_FIELDS_MESSAGE).strip().lower()
    dialog_id = require_str(body, "dialog_id", _GRANT_FIELDS_MESSAGE)
    actor = actor_of(body)
    await _access(request).grant(email, dialog_id, actor)
    await _record(
        request,
        action="access_granted",
        email=email,
        actor=actor,
        details={"email": email, "dialog_id": dialog_id},
    )
    return data({"ok": True}, status=_CREATED)


@router.api_route("/api/access", methods=["DELETE"])
async def revoke_access(request: Request) -> JSONResponse:
    """Odbiera grant; JSON body czytany przez `Request.body()` (C8, K7 §1.10)."""
    body = await body_of(request)
    email = require_str(body, "email", _GRANT_FIELDS_MESSAGE).strip().lower()
    dialog_id = require_str(body, "dialog_id", _GRANT_FIELDS_MESSAGE)
    actor = actor_of(body)
    await _access(request).revoke(email, dialog_id)
    await _record(
        request,
        action="access_revoked",
        email=email,
        actor=actor,
        details={"email": email, "dialog_id": dialog_id},
    )
    return data({"ok": True})


@router.api_route("/api/access", methods=["PATCH", "HEAD", "OPTIONS", "TRACE"])
async def access_method_not_allowed() -> JSONResponse:
    """Zła metoda na `/api/access` → 405 `{"error": "Method not allowed"}` (C8)."""
    raise MethodNotAllowed("Method not allowed")
