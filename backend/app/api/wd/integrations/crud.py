"""Trasy CRUD integracji WD ``/api/wd/v1/integrations*`` (brief T3, kontrakt E4-3b §4).

Usługa jest ta sama co w SVC (``integration_service`` z ``app.api.hub_compat.sharepoint.setup``),
a odpowiedzi walidujemy modelami z ``schemas.py``: ``integration_dto`` plus ``"type"`` — dzięki
temu zbiór kluczy jest dokładnie ten z kontraktu i żadne pole spoza modelu nie wycieka
(kontrakt §0 p. 1). Wyjątki usługi mapuje wyłącznie handler K3 (``app/api/errors.py``),
więc trasy ich nie łapią. Kolejność deklaracji: trasy stałe, potem ``/{id}`` (kontrakt §4).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.api.hub_compat.sharepoint.dto import integration_dto
from app.api.hub_compat.sharepoint.setup import integration_service
from app.api.wd.integrations.deps import actor_dep, require_admin, wd_responses
from app.api.wd.integrations.schemas import (
    ConnectionTest,
    ConnectionTestRequest,
    Envelope,
    Integration,
    IntegrationCreateRequest,
    IntegrationUpdateRequest,
    Page,
    SavedConnectionTestRequest,
)
from app.services.integration_input import (
    IntegrationCreate,
    IntegrationUpdate,
    TestConnectionInput,
    TestOverrides,
)
from app.services.integrations import Actor, IntegrationView

router = APIRouter(
    prefix="/api/wd/v1",
    tags=["integrations"],
    dependencies=[Depends(require_admin)],
)

ActorDep = Annotated[Actor, Depends(actor_dep)]
IdPath = Annotated[int, Path(ge=1, description="Identyfikator integracji")]
PageQuery = Annotated[int, Query(ge=1, description="Numer strony (od 1)")]
PageSizeQuery = Annotated[int, Query(ge=1, le=100, description="Rozmiar strony (1-100)")]


def _integration(view: IntegrationView) -> Integration:
    """Integracja WD: klucze ``integration_dto`` plus ``type`` (kontrakt §0 p. 1)."""
    return Integration.model_validate({**integration_dto(view), "type": "sharepoint"})


def _integration_envelope(view: IntegrationView) -> Envelope[Integration]:
    """Koperta sukcesu ``{"data": Integration}`` (kontrakt §0 p. 1)."""
    return Envelope[Integration](data=_integration(view))


def _connection_test(report: dict[str, object]) -> Envelope[ConnectionTest]:
    """Koperta raportu testu połączenia (``response_model_exclude_none`` usuwa ``None``)."""
    return Envelope[ConnectionTest](data=ConnectionTest.model_validate(report))


@router.get(
    "/integrations",
    operation_id="integrations_list",
    summary="Lista integracji",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[Page[Integration]],
    responses=wd_responses(400, 401, 403),
)
async def list_integrations(
    request: Request, page: PageQuery = 1, page_size: PageSizeQuery = 20
) -> Envelope[Page[Integration]]:
    """Strona listy integracji malejąco po ``id``; strona poza zakresem → 400 (kontrakt §0 p. 4)."""
    views = await integration_service(request).list()
    start = (page - 1) * page_size
    return Envelope[Page[Integration]](
        data=Page[Integration](
            items=[_integration(view) for view in views[start : start + page_size]],
            total=len(views),
            page=page,
            page_size=page_size,
        )
    )


@router.post(
    "/integrations",
    operation_id="integrations_create",
    summary="Zakłada integrację",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[Integration],
    responses=wd_responses(400, 401, 403, 409, 502),
)
async def create_integration(
    request: Request, body: IntegrationCreateRequest, actor: ActorDep
) -> Envelope[Integration]:
    """Zakłada integrację SharePoint; 409, gdy dataset ma już integrację (kontrakt §4)."""
    data = IntegrationCreate(**body.model_dump(exclude={"type"}))
    return _integration_envelope(await integration_service(request).create(data, actor))


@router.post(
    "/integrations/test",
    operation_id="integrations_test",
    summary="Test połączenia z witryną SharePoint",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[ConnectionTest],
    response_model_exclude_none=True,
    responses=wd_responses(400, 401, 403, 502),
)
async def test_connection(
    request: Request, body: ConnectionTestRequest
) -> Envelope[ConnectionTest]:
    """Test połączenia bez zapisu integracji (kontrakt §4)."""
    report = await integration_service(request).test_connection(
        TestConnectionInput(**body.model_dump(exclude={"type"}))
    )
    return _connection_test(report)


@router.get(
    "/integrations/{id}",
    operation_id="integrations_get",
    summary="Integracja",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[Integration],
    responses=wd_responses(400, 401, 403, 404),
)
async def get_integration(request: Request, id: IdPath) -> Envelope[Integration]:
    """Integracja po ``id``; brak → 404 (kontrakt §4)."""
    return _integration_envelope(await integration_service(request).get(id))


@router.patch(
    "/integrations/{id}",
    operation_id="integrations_update",
    summary="Zmienia integrację",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[Integration],
    responses=wd_responses(400, 401, 403, 404, 409, 502),
)
async def update_integration(
    request: Request, id: IdPath, body: IntegrationUpdateRequest, actor: ActorDep
) -> Envelope[Integration]:
    """Zmienia podane pola integracji; ``type`` jest niezmienialny (kontrakt §4)."""
    data = IntegrationUpdate(**body.model_dump(exclude={"type"}))
    return _integration_envelope(await integration_service(request).update(id, data, actor))


@router.delete(
    "/integrations/{id}",
    operation_id="integrations_delete",
    summary="Usuwa integrację",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=wd_responses(400, 401, 403, 404),
)
async def delete_integration(request: Request, id: IdPath, actor: ActorDep) -> Response:
    """Usuwa integrację i dane zależne; przebiegi zostają (kontrakt §4)."""
    await integration_service(request).delete(id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/integrations/{id}/test",
    operation_id="integrations_test_saved",
    summary="Test połączenia zapisanej integracji",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[ConnectionTest],
    response_model_exclude_none=True,
    responses=wd_responses(400, 401, 403, 404, 502),
)
async def test_saved_integration(
    request: Request, id: IdPath, body: SavedConnectionTestRequest | None = None
) -> Envelope[ConnectionTest]:
    """Test połączenia z zapisanym sekretem; ciało (nadpisania) opcjonalne (kontrakt §4)."""
    overrides = TestOverrides() if body is None else TestOverrides(**body.model_dump())
    report = await integration_service(request).test_saved(id, overrides)
    return _connection_test(report)
