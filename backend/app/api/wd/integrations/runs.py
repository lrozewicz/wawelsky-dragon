"""Trasy sterowania przebiegami, historii (kursory) i linku do źródła WD (kontrakt E4-3b §4).

Ten sam serwis co SVC (`integration_service`), ta sama koperta i te same DTO
(`app.api.hub_compat.sharepoint.dto`) — walidujemy odpowiedź modelem, żeby klucze były 1:1
z kontraktem i żadne pole spoza modelu nie wyciekło (kontrakt §0 p. 1, p. 7).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse

from app.api.hub_compat.sharepoint.dto import drive_dto, event_dto, run_dto, status_dto
from app.api.hub_compat.sharepoint.setup import integration_service
from app.api.wd.integrations.deps import actor_dep, require_admin, wd_responses
from app.api.wd.integrations.errors import SourceLinkNotFound
from app.api.wd.integrations.schemas import (
    CancelResult,
    CursorPage,
    DriveList,
    Envelope,
    IntegrationDrive,
    IntegrationEvent,
    IntegrationRun,
    IntegrationStatus,
    SourceLink,
    SyncQueued,
)
from app.services.integration_links import DocumentLink, LinkNotFound
from app.services.integrations import Actor, EventRow, IntegrationService, RunRow

router = APIRouter(
    prefix="/api/wd/v1",
    tags=["integrations"],
    dependencies=[Depends(require_admin)],
)

ServiceDep = Annotated[IntegrationService, Depends(integration_service)]
ActorDep = Annotated[Actor, Depends(actor_dep)]
IntegrationIdPath = Annotated[int, Path(ge=1)]

_OK = 200
_ACCEPTED = 202
RUNS_LIMIT_DEFAULT = 50
RUNS_LIMIT_MAX = 200
EVENTS_LIMIT_DEFAULT = 500
EVENTS_LIMIT_MAX = 2000


@router.post(
    "/integrations/{integration_id}/sync",
    operation_id="integrations_sync",
    summary="Zleca przebieg synchronizacji integracji",
    status_code=_ACCEPTED,
    response_model=None,
    responses={
        _OK: {"model": Envelope[IntegrationRun], "description": "Przebieg zakończony (wait=true)"},
        _ACCEPTED: {"model": Envelope[SyncQueued], "description": "Zadanie zakolejkowane"},
        **wd_responses(400, 401, 403, 404, 409),
    },
)
async def integrations_sync(
    integration_id: IntegrationIdPath,
    service: ServiceDep,
    actor: ActorDep,
    full: Annotated[bool, Query(description="Pełna synchronizacja bez kursora delty")] = False,
    wait: Annotated[bool, Query(description="Czekaj na zakończenie przebiegu")] = False,
) -> JSONResponse:
    """Zleca przebieg; ``wait=true`` zwraca gotowy ``IntegrationRun``, inaczej 202 z ``queued``."""
    outcome = await service.sync(integration_id, full=full, wait=wait, actor=actor)
    if outcome.run is None:
        return JSONResponse({"data": SyncQueued(queued=True).model_dump()}, status_code=_ACCEPTED)
    return JSONResponse({"data": _run_model(outcome.run).model_dump()}, status_code=_OK)


@router.post(
    "/integrations/{integration_id}/cancel",
    operation_id="integrations_cancel",
    summary="Anuluje przebieg synchronizacji integracji",
    responses=wd_responses(400, 401, 403, 404),
)
async def integrations_cancel(
    integration_id: IntegrationIdPath, service: ServiceDep, actor: ActorDep
) -> Envelope[CancelResult]:
    """Anuluje przebieg; ``cancelled`` prawdziwe, gdy cokolwiek zatrzymano (kontrakt §4)."""
    result = await service.cancel(integration_id, actor)
    cancelled = (
        result.was_running_in_process or result.lock_cleared or result.runs_marked_cancelled > 0
    )
    return Envelope[CancelResult](data=CancelResult(cancelled=cancelled))


@router.get(
    "/integrations/{integration_id}/status",
    operation_id="integrations_status",
    summary="Stan integracji i ostatni przebieg",
    responses=wd_responses(400, 401, 403, 404),
)
async def integrations_status(
    integration_id: IntegrationIdPath, service: ServiceDep
) -> Envelope[IntegrationStatus]:
    """Stan integracji z ostatnim przebiegiem (``null``, gdy jeszcze nie było)."""
    view = await service.status(integration_id)
    return Envelope[IntegrationStatus](data=IntegrationStatus.model_validate(status_dto(view)))


@router.get(
    "/integrations/{integration_id}/drives",
    operation_id="integrations_drives",
    summary="Lista bibliotek dokumentów integracji",
    responses=wd_responses(400, 401, 403, 404),
)
async def integrations_drives(
    integration_id: IntegrationIdPath, service: ServiceDep
) -> Envelope[DriveList]:
    """Biblioteki integracji rosnąco po nazwie (jak SVC ``drive_dto``)."""
    containers = await service.drives(integration_id)
    items = [IntegrationDrive.model_validate(drive_dto(container)) for container in containers]
    return Envelope[DriveList](data=DriveList(items=items))


@router.get(
    "/integrations/{integration_id}/runs",
    operation_id="integrations_runs_list",
    summary="Historia przebiegów integracji (kursor malejąco po id)",
    responses=wd_responses(400, 401, 403, 404),
)
async def integrations_runs_list(
    integration_id: IntegrationIdPath,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=RUNS_LIMIT_MAX, description="Rozmiar strony")] = (
        RUNS_LIMIT_DEFAULT
    ),
    after_id: Annotated[
        int | None, Query(ge=1, description="Zwróć przebiegi o id mniejszym niż ta wartość")
    ] = None,
) -> Envelope[CursorPage[IntegrationRun]]:
    """Przebiegi malejąco po ``id``; najpierw ``service.get`` (404), potem strona kursorowa."""
    await service.get(integration_id)
    runs = await service.list_runs(
        integration_type=None,
        integration_id=integration_id,
        limit=limit + 1,
        before_id=after_id,
    )
    items = [_run_model(run) for run in runs[:limit]]
    next_after_id = items[-1].id if len(runs) > limit else None
    return Envelope[CursorPage[IntegrationRun]](
        data=CursorPage[IntegrationRun](items=items, next_after_id=next_after_id)
    )


@router.get(
    "/runs/{run_id}/events",
    operation_id="integration_run_events",
    summary="Zdarzenia przebiegu (kursor rosnąco po id)",
    responses=wd_responses(400, 401, 403),
)
async def integration_run_events(
    run_id: Annotated[int, Path(ge=1)],
    service: ServiceDep,
    level: Annotated[
        Literal["info", "warn", "error"] | None, Query(description="Filtr poziomu zdarzenia")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=EVENTS_LIMIT_MAX, description="Rozmiar strony")
    ] = EVENTS_LIMIT_DEFAULT,
    after_id: Annotated[
        int, Query(ge=0, description="Zwróć zdarzenia o id większym niż ta wartość")
    ] = 0,
) -> Envelope[CursorPage[IntegrationEvent]]:
    """Zdarzenia przebiegu rosnąco po ``id``; brak przebiegu to pusta lista, nie 404 (§0 p. 8)."""
    events = await service.list_events(run_id, after_id=after_id, level=level, limit=limit + 1)
    items = [_event_model(event) for event in events[:limit]]
    next_after_id = items[-1].id if len(events) > limit else None
    return Envelope[CursorPage[IntegrationEvent]](
        data=CursorPage[IntegrationEvent](items=items, next_after_id=next_after_id)
    )


@router.get(
    "/documents/{document_id}/source-link",
    operation_id="documents_source_link",
    summary="Link do dokumentu źródłowego w SharePoint",
    responses=wd_responses(400, 401, 403, 404, 502),
)
async def documents_source_link(document_id: str, service: ServiceDep) -> Envelope[SourceLink]:
    """Link do elementu źródłowego; brak mapowania/pliku → 404 ze slugiem przyczyny (§0 p. 9)."""
    try:
        link = await service.document_link(document_id)
    except LinkNotFound as exc:
        raise SourceLinkNotFound(exc.message, exc.reason) from exc
    return Envelope[SourceLink](data=_source_link(link))


def _run_model(run: RunRow) -> IntegrationRun:
    """Przebieg z wiersza repozytorium w modelu kontraktu (klucze 1:1 z DTO SVC)."""
    return IntegrationRun.model_validate(run_dto(run))


def _event_model(event: EventRow) -> IntegrationEvent:
    """Zdarzenie z wiersza repozytorium w modelu kontraktu (klucze 1:1 z DTO SVC)."""
    return IntegrationEvent.model_validate(event_dto(event))


def _source_link(link: DocumentLink) -> SourceLink:
    """Link z usługi w modelu kontraktu (te same cztery klucze)."""
    return SourceLink(
        web_url=link.web_url, name=link.name, path=link.path, drive_name=link.drive_name
    )
