"""Trasy użytkowników WD ``/api/wd/v1/users*`` (kontrakt WP E3-6a §2, §4).

Trasy tylko mapują wejście na wywołania ``UserService`` i wynik na kopertę ``Envelope[WdUser]``;
wyjątki usług (``NotFound``, ``Conflict``, ``OperationNotAllowed``, ``ValidationFailed``)
zostawia globalnemu handlerowi K3 (``app/api/errors.py``), a każda udana mutacja dopisuje
wpis audytu wzorcem z ``hub_compat/users.py``. Kolejność deklaracji: ``GET/POST ""``,
``GET/PATCH/DELETE /{user_id}``, potem akcje ``/{user_id}/password|activate|deactivate`` (§2).
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.api.auth.principal import container_of
from app.api.hub_compat.sharepoint.dto import iso_ms
from app.api.wd.common import Envelope, Page, actor_dep, require_admin, wd_responses
from app.api.wd.users.schemas import (
    PasswordRequest,
    UserCreateRequest,
    UserUpdateRequest,
    WdUser,
)
from app.core.errors import OperationNotAllowed
from app.services.audit import AuditService
from app.services.integrations import Actor
from app.services.users import UserRow, UserService

router = APIRouter(
    prefix="/api/wd/v1",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)

ActorDep = Annotated[Actor, Depends(actor_dep)]
UserIdPath = Annotated[str, Path(min_length=1, description="Identyfikator użytkownika")]
PageQuery = Annotated[int, Query(ge=1, description="Numer strony (od 1)")]
PageSizeQuery = Annotated[int, Query(ge=1, le=100, description="Rozmiar strony (1-100)")]
SearchQuery = Annotated[
    str | None, Query(description="Szukaj po e-mailu i nazwie; znaki % i _ są dosłowne")
]
EmailQuery = Annotated[
    str | None, Query(description="Dokładny e-mail, bez rozróżniania wielkości liter")
]
DeleteMode = Annotated[
    Literal["transfer", "cascade"], Query(description="Tryb usunięcia konta (transfer, cascade)")
]

_LOCAL_AUTH_SOURCE = "local"


def _users(request: Request) -> UserService:
    """Usługa użytkowników z kontenera żądania (kontrakt §0 p. 9)."""
    return cast(UserService, container_of(request).users)


def _user(row: UserRow) -> WdUser:
    """``UserRow`` → model odpowiedzi: ISO czasy, brak pól wrażliwych (kontrakt §4)."""
    return WdUser(
        id=row.id,
        email=row.email,
        nickname=row.nickname,
        auth_source=row.auth_source,
        is_superuser=row.is_superuser,
        is_active=row.is_active,
        language=row.language,
        timezone=row.timezone,
        avatar=row.avatar,
        last_login_at=iso_ms(row.last_login_time),
        created_at=iso_ms(row.create_time),
        updated_at=iso_ms(row.update_time),
    )


async def _record(
    request: Request,
    actor: Actor,
    *,
    action: str,
    target_id: str,
    details: dict[str, object] | None = None,
) -> None:
    """Wpis audytu po udanej mutacji użytkownika (wzorzec ``hub_compat/users.py``, §0 p. 9)."""
    await cast(AuditService, container_of(request).audit).record(
        actor_label=actor.label,
        action=action,
        target_type="user",
        target_id=target_id,
        details=details,
        actor_id=actor.id,
        ip=actor.ip,
    )


@router.get(
    "/users",
    operation_id="users_list",
    summary="Lista użytkowników",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[Page[WdUser]],
    responses=wd_responses(400, 401, 403),
)
async def list_users(
    request: Request,
    page: PageQuery = 1,
    page_size: PageSizeQuery = 20,
    q: SearchQuery = None,
    email: EmailQuery = None,
) -> Envelope[Page[WdUser]]:
    """Strona kont bez kont serwisowych; ``q``/``email`` filtrują (kontrakt §2)."""
    users = _users(request)
    rows, total = await users.list_page(q=q, email=email, page=page, page_size=page_size)
    return Envelope[Page[WdUser]](
        data=Page[WdUser](
            items=[_user(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post(
    "/users",
    operation_id="users_create",
    summary="Zakłada użytkownika",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[WdUser],
    responses=wd_responses(400, 401, 403, 409),
)
async def create_user(
    request: Request, body: UserCreateRequest, actor: ActorDep
) -> Envelope[WdUser]:
    """Zakłada konto lokalne; duplikat e-maila → 409 (``user_created``, kontrakt §4)."""
    row = await _users(request).create_by_admin(
        email=body.email,
        password=body.password,
        nickname=body.nickname,
        is_superuser=body.is_superuser,
    )
    await _record(
        request, actor, action="user_created", target_id=row.id, details={"email": row.email}
    )
    return Envelope[WdUser](data=_user(row))


@router.get(
    "/users/{user_id}",
    operation_id="users_get",
    summary="Użytkownik",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[WdUser],
    responses=wd_responses(400, 401, 403, 404),
)
async def get_user(request: Request, user_id: UserIdPath) -> Envelope[WdUser]:
    """Konto po ``user_id``; brak → 404 (kontrakt §4)."""
    return Envelope[WdUser](data=_user(await _users(request).get(user_id)))


@router.patch(
    "/users/{user_id}",
    operation_id="users_update",
    summary="Zmienia użytkownika",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[WdUser],
    responses=wd_responses(400, 401, 403, 404, 409),
)
async def update_user(
    request: Request, user_id: UserIdPath, body: UserUpdateRequest, actor: ActorDep
) -> Envelope[WdUser]:
    """Zmienia podane pola konta; puste ciało → 200 bez zmian i bez wpisu audytu (§4)."""
    users = _users(request)
    row = await users.get(user_id)
    changes = await users.update_managed(
        row.email,
        nickname=body.nickname,
        is_active=body.is_active,
        is_superuser=body.is_superuser,
    )
    if changes:
        await _record(
            request,
            actor,
            action="user_updated",
            target_id=row.id,
            details={"email": row.email, "changes": changes},
        )
    return Envelope[WdUser](data=_user(await users.get(user_id)))


@router.delete(
    "/users/{user_id}",
    operation_id="users_delete",
    summary="Usuwa użytkownika",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=wd_responses(400, 401, 403, 404, 409),
)
async def delete_user(
    request: Request, user_id: UserIdPath, actor: ActorDep, mode: DeleteMode = "transfer"
) -> Response:
    """Usuwa konto w trybie ``transfer`` (domyślnie) albo ``cascade`` (kontrakt §0 p. 8)."""
    users = _users(request)
    row = await users.get(user_id)
    result = await users.delete_managed(row.email, mode)
    await _record(
        request,
        actor,
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/users/{user_id}/password",
    operation_id="users_set_password",
    summary="Ustawia hasło użytkownika",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=wd_responses(400, 401, 403, 404, 409),
)
async def set_user_password(
    request: Request, user_id: UserIdPath, body: PasswordRequest, actor: ActorDep
) -> Response:
    """Ustawia hasło konta lokalnego; konto z zewnętrznym źródłem → 409 (kontrakt §4)."""
    users = _users(request)
    row = await users.get(user_id)
    if row.auth_source != _LOCAL_AUTH_SOURCE:
        raise OperationNotAllowed("Password is managed by the identity provider")
    await users.set_password_by_email(row.email, body.new_password)
    await _record(
        request,
        actor,
        action="user_password_set",
        target_id=row.id,
        details={"email": row.email},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/users/{user_id}/activate",
    operation_id="users_activate",
    summary="Aktywuje użytkownika",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[WdUser],
    responses=wd_responses(400, 401, 403, 404, 409),
)
async def activate_user(request: Request, user_id: UserIdPath, actor: ActorDep) -> Envelope[WdUser]:
    """Aktywuje konto (``user_activated``); straż ostatniego admina w usłudze (kontrakt §4)."""
    return await _set_active(request, user_id, actor, True)


@router.post(
    "/users/{user_id}/deactivate",
    operation_id="users_deactivate",
    summary="Dezaktywuje użytkownika",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[WdUser],
    responses=wd_responses(400, 401, 403, 404, 409),
)
async def deactivate_user(
    request: Request, user_id: UserIdPath, actor: ActorDep
) -> Envelope[WdUser]:
    """Dezaktywuje konto (``user_deactivated``); ostatni admin → 409 (kontrakt §4)."""
    return await _set_active(request, user_id, actor, False)


async def _set_active(
    request: Request, user_id: str, actor: Actor, active: bool
) -> Envelope[WdUser]:
    """Wspólny przebieg aktywacji/dezaktywacji: usługa, audyt i świeży wiersz (kontrakt §4)."""
    users = _users(request)
    await users.set_active(user_id, active)
    row = await users.get(user_id)
    action = "user_activated" if active else "user_deactivated"
    await _record(request, actor, action=action, target_id=row.id, details={"email": row.email})
    return Envelope[WdUser](data=_user(row))
