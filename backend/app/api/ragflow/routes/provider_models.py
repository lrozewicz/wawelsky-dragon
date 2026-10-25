"""Trasy modeli instancji ``/api/v1/providers/{name}/instances/{instance}/models`` (K13 §3 p. 7-10).

Router zakłada T1; trasy, schematy i reguły K13 §4 p. 5-8 dokłada T3. Trasy są cienkie:
ciało przez ``json_body`` (kontrakt C9), walidacja i zapis w ``InstanceModelService``.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.envelope import ok, ok_result
from app.api.ragflow.schemas.common import RagflowOk, RagflowOkEmpty, extra_doc, query_param
from app.api.ragflow.schemas.provider_models import (
    InstanceModel,
    InstanceModelAddRequest,
    InstanceModelsDeleteRequest,
    InstanceModelUpdateRequest,
    SupportedModel,
)
from app.services.instance_models import (
    InstanceModelService,
    InstanceModelView,
    SupportedModelView,
)

router = APIRouter(prefix="/api/v1", tags=["providers"])

# Opis parametru `supported` (K13 §3 p. 7): lista bramki zamiast rejestru.
SUPPORTED_DOC = "Lista modeli wystawionych przez bramkę instancji (tylko superuser)."

# Wartości `supported` traktowane jak prawda (nagłówek zapytania, bez walidacji typów).
SUPPORTED_TRUE = frozenset({"true", "1"})


def _svc(request: Request) -> InstanceModelService:
    """Usługa modeli instancji per żądanie (C0 p. 2)."""
    return InstanceModelService(container_of(request))


def _model_body(view: InstanceModelView) -> dict[str, Any]:
    """Element ``data`` listy modeli instancji (K13 §3, schemat ``InstanceModel``)."""
    return {
        "name": view.name,
        "model_type": view.model_type,
        "max_tokens": view.max_tokens,
        "status": view.status,
        "rank": view.rank,
        "extra": view.extra,
        "wd_model_id": view.wd_model_id,
        "wd_dimension": view.wd_dimension,
        "wd_is_default": view.wd_is_default,
    }


def _supported_body(view: SupportedModelView) -> dict[str, Any]:
    """Element ``data`` listy modeli bramki (K13 §3, schemat ``SupportedModel``)."""
    return {"name": view.name, "rank": view.rank}


def _wants_supported(request: Request) -> bool:
    """Czy żądanie niesie ``supported=true`` (K13 §3 p. 7)."""
    return request.query_params.get("supported", "").casefold() in SUPPORTED_TRUE


@router.get(
    "/providers/{name}/instances/{instance}/models",
    operation_id="provider_instance_models_list",
    responses={200: {"model": RagflowOk[list[InstanceModel] | list[SupportedModel]]}},
    openapi_extra=extra_doc(
        query=[query_param("supported", {"type": "boolean", "default": False}, SUPPORTED_DOC)]
    ),
)
async def list_instance_models(
    name: str, instance: str, request: Request, principal: PrincipalDep
) -> JSONResponse:
    """Modele instancji z rejestru albo lista bramki dla ``supported=true`` (K13 §3 p. 7)."""
    svc = _svc(request)
    if _wants_supported(request):
        supported = await svc.supported(principal, name, instance)
        return ok([_supported_body(view) for view in supported])
    return ok([_model_body(view) for view in await svc.list(name, instance)])


@router.post(
    "/providers/{name}/instances/{instance}/models",
    operation_id="provider_instance_model_add",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(InstanceModelAddRequest),
)
async def add_instance_model(
    name: str, instance: str, request: Request, principal: PrincipalDep
) -> JSONResponse:
    """Dodaje model do instancji; tylko superuser (K13 §3 p. 8, §4 p. 6)."""
    body: Mapping[str, object] = await json_body(request)
    await _svc(request).add(principal, name, instance, body)
    return ok_result()


@router.patch(
    "/providers/{name}/instances/{instance}/models/{model_name:path}",
    operation_id="provider_instance_model_update",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(InstanceModelUpdateRequest),
)
async def update_instance_model(
    name: str, instance: str, model_name: str, request: Request, principal: PrincipalDep
) -> JSONResponse:
    """Zmienia status, `max_tokens` albo `extra` modelu instancji (K13 §3 p. 9, §4 p. 7)."""
    body: Mapping[str, object] = await json_body(request)
    await _svc(request).update(principal, name, instance, model_name, body)
    return ok_result()


@router.delete(
    "/providers/{name}/instances/{instance}/models",
    operation_id="provider_instance_models_delete",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(InstanceModelsDeleteRequest),
)
async def delete_instance_models(
    name: str, instance: str, request: Request, principal: PrincipalDep
) -> JSONResponse:
    """Usuwa modele instancji — wszystko albo nic; tylko superuser (K13 §3 p. 10, §4 p. 8)."""
    body: Mapping[str, object] = await json_body(request)
    await _svc(request).delete(principal, name, instance, body)
    return ok_result()
