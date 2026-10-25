"""Trasy SVC integracji SharePoint `/api/integrations*` (03 §5, kontrakt E4-3a §4).

Kolejność deklaracji: trasy stałe, potem `{id}` (parametr jako `str` i ręczny parse), żeby
„runs” nigdy nie trafił do `{id}` (T4b montuje `runs.router` przed tym routerem).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import client_ip
from app.api.hub_compat.envelope import data
from app.api.hub_compat.parsing import actor_of, body_of
from app.api.hub_compat.route import SvcRoute
from app.api.hub_compat.security import require_secret
from app.api.hub_compat.sharepoint.dto import (
    drive_dto,
    integration_dto,
    run_dto,
    status_dto,
)
from app.api.hub_compat.sharepoint.setup import integration_service
from app.core.errors import ValidationFailed
from app.services.integration_input import (
    parse_create,
    parse_test_connection,
    parse_update,
)
from app.services.integration_ops import Actor

router = APIRouter(
    route_class=SvcRoute,
    include_in_schema=False,
    dependencies=[Depends(require_secret)],
)

INVALID_ID = "Invalid integration id"
_TRUE_FLAGS = frozenset({"1", "true"})
_CREATED = 201
_ACCEPTED = 202


def _integration_id(raw: str) -> int:
    """`{id}` jako liczba całkowita > 0, inaczej 400 „Invalid integration id” (§4)."""
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValidationFailed(INVALID_ID) from exc
    if parsed <= 0:
        raise ValidationFailed(INVALID_ID)
    return parsed


def _actor(request: Request, body: dict[str, object]) -> Actor:
    """Aktor mutacji: `body.actor` albo „X-API-Secret”, plus IP klienta (§4)."""
    return Actor(label=actor_of(body), ip=client_ip(request))


def _flag(value: str | None) -> bool:
    """`?full`/`?wait`: dokładnie `1` albo `true` (`integrations.ts:601-604`)."""
    return value in _TRUE_FLAGS


@router.get("/api/integrations")
async def list_integrations(request: Request) -> JSONResponse:
    """Wszystkie integracje malejąco po `id` (§4)."""
    views = await integration_service(request).list()
    return data([integration_dto(view) for view in views])


@router.post("/api/integrations")
async def create_integration(request: Request) -> JSONResponse:
    """Zakłada integrację; `parse_create` waliduje pola i zwraca 400 z komunikatem (§4)."""
    body = await body_of(request)
    created = await integration_service(request).create(parse_create(body), _actor(request, body))
    return data(integration_dto(created), _CREATED)


@router.post("/api/integrations/test-connection")
async def test_connection(request: Request) -> JSONResponse:
    """Test połączenia bez zapisu integracji (§4)."""
    body = await body_of(request)
    report = await integration_service(request).test_connection(parse_test_connection(body))
    return data(report)


@router.get("/api/integrations/{id}")
async def get_integration(request: Request, id: str) -> JSONResponse:
    """Integracja po `id`; brak → 404, zły `id` → 400 (§4)."""
    view = await integration_service(request).get(_integration_id(id))
    return data(integration_dto(view))


@router.put("/api/integrations/{id}")
async def update_integration(request: Request, id: str) -> JSONResponse:
    """Zmienia integrację (`None` = bez zmiany; sekret tylko gdy nadesłany) (§4)."""
    body = await body_of(request)
    updated = await integration_service(request).update(
        _integration_id(id), parse_update(body), _actor(request, body)
    )
    return data(integration_dto(updated))


@router.delete("/api/integrations/{id}")
async def delete_integration(request: Request, id: str) -> JSONResponse:
    """Usuwa integrację i dane zależne; dokumenty i przebiegi zostają (§4)."""
    body = await body_of(request)
    integration_id = _integration_id(id)
    await integration_service(request).delete(integration_id, _actor(request, body))
    return data({"id": integration_id, "deleted": True})


@router.post("/api/integrations/{id}/sync")
async def sync_integration(request: Request, id: str) -> JSONResponse:
    """Zleca przebieg; `?wait=1` zwraca gotowy `run_dto`, inaczej 202 (§4)."""
    body = await body_of(request)
    full = _flag(request.query_params.get("full"))
    wait = _flag(request.query_params.get("wait"))
    outcome = await integration_service(request).sync(
        _integration_id(id), full=full, wait=wait, actor=_actor(request, body)
    )
    if outcome.run is None:
        return data({"started": True, "full": full}, _ACCEPTED)
    return data(run_dto(outcome.run))


@router.post("/api/integrations/{id}/cancel")
async def cancel_integration(request: Request, id: str) -> JSONResponse:
    """Anuluje przebieg integracji (§4)."""
    body = await body_of(request)
    result = await integration_service(request).cancel(_integration_id(id), _actor(request, body))
    return data(
        {
            "was_running_in_process": result.was_running_in_process,
            "lock_cleared": result.lock_cleared,
            "runs_marked_cancelled": result.runs_marked_cancelled,
        }
    )


@router.get("/api/integrations/{id}/status")
async def integration_status(request: Request, id: str) -> JSONResponse:
    """Stan integracji i ostatni przebieg (§4)."""
    view = await integration_service(request).status(_integration_id(id))
    return data(status_dto(view))


@router.get("/api/integrations/{id}/drives")
async def integration_drives(request: Request, id: str) -> JSONResponse:
    """Kontenery (biblioteki) integracji rosnąco po nazwie (§4)."""
    containers = await integration_service(request).drives(_integration_id(id))
    return data([drive_dto(container) for container in containers])
