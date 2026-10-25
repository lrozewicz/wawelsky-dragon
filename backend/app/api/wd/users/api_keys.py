"""Trasy kluczy API użytkowników WD ``/api/wd/v1/users/{id}/api-keys*`` (brief T3, kontrakt §4, §7).

Trzy trasy administratora: lista kluczy **bez tokenu** (``ApiKey`` nie ma pola ``token`` — pełny
token nigdy nie opuszcza odpowiedzi ``POST``), utworzenie z tokenem jawnym raz oraz unieważnienie.
Ciało ``POST`` przyjmuje nazwę i opcjonalny termin wygaśnięcia ``expires_at`` (K14 §3 p. 1:
ISO 8601 ze strefą, w przyszłości; inaczej 400 ``validation_failed``). Lista oddaje ``expires_at``
także dla kluczy wygasłych — decyzję o odrzuceniu klucza podejmuje uwierzytelnianie (K14 §2).
Mutacje zostawiają wpisy audytu ``api_key_created``/``api_key_deleted`` z ``target_type="api_key"``
i ``target_id`` = **id klucza** (K7 §5 p. 2; bez tokenu w ``details``). Wyjątki usługi mapuje
wyłącznie handler K3 (``app/api/errors.py``), więc trasy ich nie łapią. Nieznany ``user_id``
każdej trasy → ``NotFound`` z ``users.get`` (404).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Path, Request, Response, status
from pydantic import BaseModel, Field

from app.api.auth.principal import container_of
from app.api.hub_compat.sharepoint.dto import iso_ms
from app.api.wd.common import Envelope, Items, actor_dep, require_admin, wd_responses
from app.core.errors import NotFound, ValidationFailed
from app.services.api_keys import ApiKeyService, ApiKeyView
from app.services.audit import AuditService
from app.services.integrations import Actor
from app.services.users import UserService

router = APIRouter(
    prefix="/api/wd/v1",
    tags=["api-keys"],
    dependencies=[Depends(require_admin)],
)

ActorDep = Annotated[Actor, Depends(actor_dep)]
UserIdPath = Annotated[str, Path(min_length=1, description="Identyfikator użytkownika")]
KeyIdPath = Annotated[str, Path(min_length=1, description="Identyfikator klucza API")]

# Komunikaty 400 pola `expires_at` (K14 §3 p. 1; ten sam kod co inne błędy walidacji ciała).
_EXPIRES_AT_MESSAGE = "expires_at must be an ISO 8601 timestamp with a time zone"
_EXPIRES_AT_PAST_MESSAGE = "expires_at must be in the future"
_MS_PER_SECOND = 1000


class ApiKey(BaseModel):
    """Klucz API w odpowiedzi WD — **bez** tokenu (kontrakt §3)."""

    id: str = Field(description="Identyfikator klucza")
    name: str | None = Field(description="Nazwa nadana kluczowi")
    prefix: str = Field(description="Prefiks tokenu (pierwsze 16 znaków)")
    created_at: str | None = Field(description="Czas utworzenia (ISO 8601)")
    last_used_at: str | None = Field(description="Czas ostatniego użycia (ISO 8601)")
    expires_at: str | None = Field(
        description="Czas wygaśnięcia (ISO 8601 UTC; null — klucz bezterminowy)"
    )


class ApiKeyCreated(ApiKey):
    """Klucz API z jawnym tokenem — wyłącznie odpowiedź ``POST`` (kontrakt §3)."""

    token: str = Field(description="Pełny token klucza (pokazywany tylko raz)")


class ApiKeyCreateRequest(BaseModel):
    """Ciało ``POST /users/{id}/api-keys`` — nazwa i opcjonalny termin wygaśnięcia (§3)."""

    name: str | None = Field(None, max_length=255, description="Nazwa klucza (opcjonalna)")
    expires_at: str | None = Field(
        None,
        description=(
            "Czas wygaśnięcia klucza w ISO 8601 ze strefą (np. 2026-12-31T23:59:59Z); "
            "brak albo null — klucz bezterminowy"
        ),
    )


def _expires_at_ms(raw: str, now: int) -> int:
    """ISO 8601 ze strefą → ms UTC; bez strefy, nieparsowalne albo ``<= now`` → 400 (§3 p. 1)."""
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as err:
        raise ValidationFailed(_EXPIRES_AT_MESSAGE) from err
    if moment.tzinfo is None:
        raise ValidationFailed(_EXPIRES_AT_MESSAGE)
    value = int(moment.timestamp() * _MS_PER_SECOND)
    if value <= now:
        raise ValidationFailed(_EXPIRES_AT_PAST_MESSAGE)
    return value


def _users(request: Request) -> UserService:
    """Usługa użytkowników z kontenera żądania (C9)."""
    return cast(UserService, container_of(request).users)


def _keys(request: Request) -> ApiKeyService:
    """Usługa kluczy API z kontenera żądania (C9)."""
    return cast(ApiKeyService, container_of(request).api_keys)


def _audit(request: Request) -> AuditService:
    """Usługa audytu z kontenera żądania (C8)."""
    return cast(AuditService, container_of(request).audit)


def _api_key(view: ApiKeyView) -> ApiKey:
    """Widok usługi → model ``ApiKey`` (kontrakt §3)."""
    return ApiKey(
        id=view.id,
        name=view.name,
        prefix=view.prefix,
        created_at=iso_ms(view.create_time),
        last_used_at=iso_ms(view.last_used_at),
        expires_at=iso_ms(view.expires_at),
    )


@router.get(
    "/users/{user_id}/api-keys",
    operation_id="user_api_keys_list",
    summary="Lista kluczy API użytkownika",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[Items[ApiKey]],
    responses=wd_responses(400, 401, 403, 404),
)
async def list_user_api_keys(request: Request, user_id: UserIdPath) -> Envelope[Items[ApiKey]]:
    """Aktywne klucze użytkownika bez tokenu; nieznany ``user_id`` → 404 (kontrakt §4)."""
    row = await _users(request).get(user_id)
    views = await _keys(request).list_for_user(row.id)
    return Envelope[Items[ApiKey]](data=Items[ApiKey](items=[_api_key(view) for view in views]))


@router.post(
    "/users/{user_id}/api-keys",
    operation_id="user_api_keys_create",
    summary="Tworzy klucz API użytkownika",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[ApiKeyCreated],
    responses=wd_responses(400, 401, 403, 404),
)
async def create_user_api_key(
    request: Request,
    user_id: UserIdPath,
    actor: ActorDep,
    body: ApiKeyCreateRequest | None = None,
) -> Envelope[ApiKeyCreated]:
    """Nowy klucz użytkownika (``api_key_created``); token jawny tylko w tej odpowiedzi (§4).

    ``expires_at`` z ciała (K14 §3 p. 1) walidujemy **przed** odczytem użytkownika — tak samo
    jak pozostałe błędy walidacji ciała, które FastAPI zgłasza przed handlerem.
    """
    requested = None if body is None else body.expires_at
    expires_at = (
        None
        if requested is None
        else _expires_at_ms(requested, container_of(request).clock.now_ms())
    )
    users = _users(request)
    row = await users.get(user_id)
    view = await _keys(request).create(
        users.principal_of(row),
        name=None if body is None else body.name,
        expires_at=expires_at,
    )
    await _audit(request).record(
        actor_label=actor.label,
        action="api_key_created",
        target_type="api_key",
        target_id=view.id,
        details={"user_id": row.id, "prefix": view.prefix, "expires_at": requested},
        actor_id=actor.id,
        ip=actor.ip,
    )
    return Envelope[ApiKeyCreated](
        data=ApiKeyCreated(**_api_key(view).model_dump(), token=view.token)
    )


@router.delete(
    "/users/{user_id}/api-keys/{key_id}",
    operation_id="user_api_keys_delete",
    summary="Unieważnia klucz API użytkownika",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=wd_responses(400, 401, 403, 404),
)
async def delete_user_api_key(
    request: Request, user_id: UserIdPath, key_id: KeyIdPath, actor: ActorDep
) -> Response:
    """Unieważnia klucz użytkownika (``api_key_deleted``); brak/cudzy → 404 (kontrakt §4)."""
    row = await _users(request).get(user_id)
    revoked = await _keys(request).revoke_for_user(row.id, key_id)
    if revoked is None:
        raise NotFound("Key not found")
    await _audit(request).record(
        actor_label=actor.label,
        action="api_key_deleted",
        target_type="api_key",
        target_id=revoked,
        details={"user_id": row.id},
        actor_id=actor.id,
        ip=actor.ip,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
