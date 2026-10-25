"""Trasy grantów asystentów WD ``/api/wd/v1/access/assistants`` (brief T4, kontrakt §2, §4).

Cztery trasy administratora na usłudze tej samej co SVC (``AccessService``): lista grantów,
zastąpienie całego zbioru (``PUT``), nadanie (``POST``) i odebranie (``DELETE`` z ciałem JSON).
E-maile normalizujemy (``strip().lower()``), mutacje zostawiają wpisy audytu ``access_*``
z ``target_type="access"`` i ``target_id`` = e-mail (kontrakt §4). Wyjątki usługi (nieznany
``chat_id`` → ``ValidationFailed``) mapuje wyłącznie handler K3 (``app/api/errors.py``),
więc trasy ich nie łapią.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.auth.principal import container_of
from app.api.hub_compat.sharepoint.dto import iso_ms
from app.api.wd.access.schemas import (
    AccessGrantRequest,
    AccessReplaced,
    AccessReplaceRequest,
    AssistantGrant,
    AssistantGrantRef,
)
from app.api.wd.common import Envelope, Items, actor_dep, require_admin, wd_responses
from app.services.access import AccessEntry, AccessService
from app.services.audit import AuditService
from app.services.integrations import Actor

router = APIRouter(
    prefix="/api/wd/v1",
    tags=["access"],
    dependencies=[Depends(require_admin)],
)

ActorDep = Annotated[Actor, Depends(actor_dep)]
EmailQuery = Annotated[str, Query(min_length=1, description="E-mail użytkownika")]


def _access(request: Request) -> AccessService:
    """Usługa grantów z kontenera żądania (C7)."""
    return cast(AccessService, container_of(request).access)


def _audit(request: Request) -> AuditService:
    """Usługa audytu z kontenera żądania (C8)."""
    return cast(AuditService, container_of(request).audit)


def _grant(entry: AccessEntry) -> AssistantGrant:
    """Widok usługi → model ``AssistantGrant`` (kontrakt §2)."""
    return AssistantGrant(
        chat_id=entry.dialog_id,
        created_by=entry.created_by,
        created_at=iso_ms(entry.created_at),
    )


async def _record(
    request: Request, actor: Actor, *, action: str, email: str, details: dict[str, object]
) -> None:
    """Wpis audytu mutacji grantów: ``target_type="access"``, ``target_id`` = e-mail (§4)."""
    await _audit(request).record(
        actor_label=actor.label,
        action=action,
        target_type="access",
        target_id=email,
        details=details,
        actor_id=actor.id,
        ip=actor.ip,
    )


@router.get(
    "/access/assistants",
    operation_id="access_assistants_list",
    summary="Lista grantów asystentów użytkownika",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[Items[AssistantGrant]],
    responses=wd_responses(400, 401, 403),
)
async def list_assistant_grants(
    request: Request, email: EmailQuery
) -> Envelope[Items[AssistantGrant]]:
    """Granty e-maila; e-mail bez grantów → pusta lista (kontrakt §2)."""
    entries = await _access(request).get(email.strip().lower())
    return Envelope[Items[AssistantGrant]](
        data=Items[AssistantGrant](items=[_grant(entry) for entry in entries])
    )


@router.put(
    "/access/assistants",
    operation_id="access_assistants_replace",
    summary="Zastępuje zbiór grantów asystentów",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[AccessReplaced],
    responses=wd_responses(400, 401, 403),
)
async def replace_assistant_grants(
    request: Request, body: AccessReplaceRequest, actor: ActorDep
) -> Envelope[AccessReplaced]:
    """Cały nowy zbiór grantów (``access_replaced``); nieznany ``chat_id`` → 400 (kontrakt §4)."""
    email = body.email.strip().lower()
    count = await _access(request).replace(email, body.chat_ids, actor.label)
    await _record(
        request,
        actor,
        action="access_replaced",
        email=email,
        details={"email": email, "count": count, "dialog_ids": body.chat_ids},
    )
    return Envelope[AccessReplaced](data=AccessReplaced(email=email, count=count))


@router.post(
    "/access/assistants",
    operation_id="access_assistants_grant",
    summary="Nadaje grant asystenta",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[AssistantGrantRef],
    responses=wd_responses(400, 401, 403),
)
async def grant_assistant(
    request: Request, body: AccessGrantRequest, actor: ActorDep
) -> Envelope[AssistantGrantRef]:
    """Nadaje grant (idempotentnie, zawsze 201); nieznany ``chat_id`` → 400 (kontrakt §4)."""
    email = body.email.strip().lower()
    await _access(request).grant(email, body.chat_id, actor.label)
    await _record(
        request,
        actor,
        action="access_granted",
        email=email,
        details={"email": email, "dialog_id": body.chat_id},
    )
    return Envelope[AssistantGrantRef](data=AssistantGrantRef(email=email, chat_id=body.chat_id))


@router.delete(
    "/access/assistants",
    operation_id="access_assistants_revoke",
    summary="Odbiera grant asystenta",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=wd_responses(400, 401, 403),
)
async def revoke_assistant(request: Request, body: AccessGrantRequest, actor: ActorDep) -> Response:
    """Odbiera grant (idempotentnie, zawsze 204) i zapisuje ``access_revoked`` (kontrakt §4)."""
    email = body.email.strip().lower()
    await _access(request).revoke(email, body.chat_id)
    await _record(
        request,
        actor,
        action="access_revoked",
        email=email,
        details={"email": email, "dialog_id": body.chat_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
