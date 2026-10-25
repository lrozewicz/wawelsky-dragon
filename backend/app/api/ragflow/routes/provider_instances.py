"""Trasy instancji dostawców: CRUD, sonda połączenia (K13 §3 p. 1-6, CONTRACT E3-6b §T2).

Odczyt (GET) dla każdego zalogowanego; zapis i ``/connection`` rozstrzyga strażnik
superusera w metodzie usługi (``require_superuser`` na jej początku). Trasy nie dotykają
bazy bezpośrednio (import-linter ``api-no-db``) — wołają usługi.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.envelope import ok, ok_result
from app.api.ragflow.routes.models import INSTANCE_NAME, instance_id
from app.api.ragflow.schemas.common import RagflowOk, RagflowOkEmpty, extra_doc
from app.api.ragflow.schemas.models import ProviderInstance
from app.api.ragflow.schemas.provider_instances import (
    ProviderConnectionRequest,
    ProviderInstanceCreateRequest,
    ProviderInstanceDetail,
    ProviderInstancesDeleteRequest,
    ProviderInstanceUpdateRequest,
)
from app.services.model_catalog import ModelCatalogService
from app.services.provider_common import API_KEY_MASK, provider_id, resolve_provider
from app.services.provider_instances import InstanceView, ProviderInstanceService

router = APIRouter(prefix="/api/v1", tags=["providers"])

# Region i status instancji: wartości ze złota (system--15.json); WD nie ma ich odpowiednika.
INSTANCE_REGION = "default"
INSTANCE_STATUS = "active"


def _svc(request: Request) -> ProviderInstanceService:
    """Usługa instancji per żądanie (C0 p. 2)."""
    return ProviderInstanceService(container_of(request))


async def _default_id(request: Request, column: str) -> str:
    """Id syntetycznej instancji ``default`` — jak grupa modeli bez instancji (K13 §3 p. 1)."""
    group = await ModelCatalogService(container_of(request)).provider(column)
    return instance_id(column, group.base_url if group is not None else None)


def _instance_entry(view: InstanceView, column: str) -> dict[str, object]:
    """Element ``data`` GET /providers/{name}/instances (K13 §3 p. 1)."""
    return {
        "id": view.id,
        "instance_name": view.name,
        "provider_id": provider_id(column),
        "region": INSTANCE_REGION,
        "status": INSTANCE_STATUS,
    }


@router.get(
    "/providers/{name}/instances",
    operation_id="provider_instances_list",
    responses={200: {"model": RagflowOk[list[ProviderInstance]]}},
)
async def list_instances(name: str, request: Request, principal: PrincipalDep) -> JSONResponse:
    """Instancje dostawcy: ``default`` pierwsza, potem wiersze tabeli (K13 §3 p. 1)."""
    column = resolve_provider(name)
    rows = [_instance_entry(view, column) for view in await _svc(request).list(column)]
    default = {
        "id": await _default_id(request, column),
        "instance_name": INSTANCE_NAME,
        "provider_id": provider_id(column),
        "region": INSTANCE_REGION,
        "status": INSTANCE_STATUS,
    }
    return ok([default, *rows])


@router.get(
    "/providers/{name}/instances/{instance}",
    operation_id="provider_instance_get",
    responses={200: {"model": RagflowOk[ProviderInstanceDetail]}},
)
async def get_instance(
    name: str, instance: str, request: Request, principal: PrincipalDep
) -> JSONResponse:
    """Instancja po id albo nazwie; ``default`` z konfiguracji środowiska (K13 §3 p. 3)."""
    column = resolve_provider(name)
    view = await _svc(request).get(name, instance)
    identifier = view.id if view.id is not None else await _default_id(request, column)
    return ok(
        {
            "id": identifier,
            "instance_name": view.name,
            "provider_id": provider_id(column),
            "region": INSTANCE_REGION,
            "base_url": view.base_url,
            "api_key": API_KEY_MASK if view.has_api_key else "",
            "status": INSTANCE_STATUS,
            "wd_managed": view.managed,
        }
    )


@router.post(
    "/providers/{name}/instances",
    operation_id="provider_instance_create",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(ProviderInstanceCreateRequest),
)
async def create_instance(name: str, request: Request, principal: PrincipalDep) -> JSONResponse:
    """Zakłada instancję dostawcy; tylko superuser (K13 §3 p. 2)."""
    await _svc(request).create(principal, name, await json_body(request))
    return ok_result()


@router.put(
    "/providers/{name}/instances/{instance}",
    operation_id="provider_instance_update",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(ProviderInstanceUpdateRequest),
)
async def update_instance(
    name: str, instance: str, request: Request, principal: PrincipalDep
) -> JSONResponse:
    """Zmienia instancję tabeli; ``default`` jest tylko do odczytu (K13 §3 p. 4)."""
    await _svc(request).update(principal, name, instance, await json_body(request))
    return ok_result()


@router.delete(
    "/providers/{name}/instances",
    operation_id="provider_instances_delete",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(ProviderInstancesDeleteRequest),
)
async def delete_instances(name: str, request: Request, principal: PrincipalDep) -> JSONResponse:
    """Usuwa instancje razem z ich modelami — wszystko albo nic (K13 §3 p. 5)."""
    await _svc(request).delete(principal, name, await json_body(request))
    return ok_result()


@router.post(
    "/providers/{name}/connection",
    operation_id="provider_connection_verify",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(ProviderConnectionRequest),
)
async def verify_connection(name: str, request: Request, principal: PrincipalDep) -> JSONResponse:
    """Sonda ``GET {base_url}/models``; niczego nie zapisuje (K13 §3 p. 6, §4 p. 4)."""
    await _svc(request).verify(principal, name, await json_body(request))
    return ok_result()


# Jawny re-eksport stałych odpowiedzi dla testów jednostkowych (DEC-075).
__all__ = ["INSTANCE_REGION", "INSTANCE_STATUS", "router"]
