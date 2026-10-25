"""Trasy /api/v1/datasets (kontrakt E1-9a C1.5): CRUD w kształcie v0.27.2."""

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import argument_error, ok_result
from app.api.ragflow.normalize.common import json_object_body
from app.api.ragflow.normalize.datasets import (
    create_dataset,
    delete_datasets,
    list_datasets,
    update_dataset,
)
from app.api.ragflow.present.datasets import (
    dataset,
    dataset_detail,
    dataset_listed,
    dataset_updated,
    delete_noop_v024,
    delete_ok_v024,
)
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.datasets import (
    CreateDatasetRequest,
    Dataset,
    DatasetDetail,
    DatasetListOk,
    DeleteDatasetsRequest,
    SuccessCount,
    UpdateDatasetRequest,
)
from app.core.errors import NotFound, PermissionDenied
from app.services.datasets import DatasetService

router = APIRouter(prefix="/api/v1", tags=["datasets"])

# Upstream v0.24.0 waliduje ``dataset_id`` w SDK jako UUID1, zanim sprawdzi właściciela
# (api/apps/sdk/dataset.py:331 → api/utils/validation_utils.py:316); złoto v0.24.0
# ``datasets__000…0/errors_access--43.json`` to 101 dokładnie z tym komunikatem (K11 §10c p. 9).
_MSG_INVALID_UUID1 = "Field: <dataset_id> - Message: <Invalid UUID1 format> - Value: <{dataset_id}>"
# Upstream v0.27.2 ``UpdateDatasetReq.validate_dataset_id`` → ``validate_uuid1_hex`` (VU:337)
# przyjmuje DOWOLNĄ wersję UUID, ale odrzuca wszystko inne tym komunikatem (gold errors_access--10
# używa poprawnego id, więc go nie dotyczy).
_MSG_INVALID_UUID = "Field: <dataset_id> - Message: <Invalid UUID format> - Value: <{dataset_id}>"
# WD nie zakłada wersji UUID (ADR-04): przepuszcza własne UUIDv7 i zmigrowane UUID1, resztę
# (m.in. nil UUID kroku ``dataset_put_missing``) odrzuca jak upstream.
_UUID_VERSIONS = frozenset({1, 7})


def _is_uuid1_like(value: str) -> bool:
    """True dla UUID parsowalnego o wersji 1 (zmigrowany) albo 7 (własny WD)."""
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version in _UUID_VERSIONS


def _is_uuid(value: str) -> bool:
    """True dla dowolnego poprawnie sformatowanego UUID (v0.27.2 ``validate_uuid1_hex``)."""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _svc(request: Request) -> DatasetService:
    """Usługa datasetów per żądanie (C0 p. 2)."""
    return DatasetService(container_of(request))


@router.post(
    "/datasets",
    operation_id="datasets_create",
    responses={200: {"model": RagflowOk[Dataset]}},
    openapi_extra=extra_doc(CreateDatasetRequest),
)
async def create(request: Request, principal: PrincipalDep, profile: CompatDep) -> JSONResponse:
    """POST /datasets — utworzenie datasetu (C1.5)."""
    cmd = create_dataset(await json_object_body(request), profile)
    rec = await _svc(request).create(principal, **cmd.model_dump())
    return ok_result(dataset(rec, profile))


@router.get(
    "/datasets",
    operation_id="datasets_list",
    responses={200: {"model": DatasetListOk}},
    openapi_extra=extra_doc(
        query=[
            query_param("page", {"type": "integer"}, "Numer strony (od 1)"),
            query_param("page_size", {"type": "integer"}, "Liczba elementów na stronie"),
            query_param(
                "orderby", {"type": "string"}, "Pole sortowania: create_time albo update_time"
            ),
            query_param("desc", {"type": "boolean"}, "Sortowanie malejące (domyślnie true)"),
            query_param("id", {"type": "string"}, "Filtr: identyfikator datasetu"),
            query_param("name", {"type": "string"}, "Filtr: nazwa datasetu"),
            query_param("keywords", {"type": "string"}, "Filtr pełnotekstowy po nazwie"),
        ]
    ),
)
async def list_datasets_route(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET /datasets — strona listy z total_datasets (C1.5)."""
    q = list_datasets(
        request.query_params, profile, max_size=container_of(request).settings.max_page_size
    )
    try:
        rows, total = await _svc(request).list(principal, q)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "datasets_list", err, compat=profile)
    return ok_result([dataset_listed(rec, profile) for rec in rows], total=total)


@router.get(
    "/datasets/{dataset_id}",
    operation_id="datasets_get",
    responses={200: {"model": RagflowOk[DatasetDetail]}},
)
async def get_dataset(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET /datasets/{id} — szczegóły z connectors [] i size (C1.5, DAS:272-276)."""
    try:
        rec, size = await _svc(request).get_detail(principal, dataset_id)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "datasets_get", err, compat=profile)
    return ok_result(dataset_detail(rec, profile, size))


@router.put(
    "/datasets/{dataset_id}",
    operation_id="datasets_update",
    responses={200: {"model": RagflowOk[DatasetDetail]}},
    openapi_extra=extra_doc(UpdateDatasetRequest, required=False),
)
async def update(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """PUT /datasets/{id} — aktualizacja pól obecnych w body (C1.5).

    Profil 0.24.0: nieparsowalny ``dataset_id`` (albo o wersji UUID nieużywanej przez WD)
    to 101 jeszcze przed sprawdzeniem właściciela — jak walidator SDK v0.24.
    """
    if profile == "ragflow_0_24":
        if not _is_uuid1_like(dataset_id):
            return argument_error(_MSG_INVALID_UUID1.format(dataset_id=dataset_id))
    elif not _is_uuid(dataset_id):
        return argument_error(_MSG_INVALID_UUID.format(dataset_id=dataset_id))
    fields = update_dataset(await json_object_body(request), profile)
    try:
        rec = await _svc(request).update(principal, dataset_id, fields)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "datasets_update", err, compat=profile)
    return ok_result(dataset_updated(rec, profile))


@router.delete(
    "/datasets",
    operation_id="datasets_delete",
    responses={200: {"model": RagflowOk[SuccessCount]}},
    openapi_extra=extra_doc(DeleteDatasetsRequest, required=False),
)
async def delete_datasets_route(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """DELETE /datasets — usunięcie wg ids albo delete_all (C1.5).

    Profil 0.24.0: koperta bez ``data`` (złoto --05), a puste ``ids`` bez ``delete_all``
    to no-op z ostrzeżeniem (02-api §7.3, Q14). Profil 0.27.2 bez zmian.
    """
    cmd = delete_datasets(await json_object_body(request), profile)
    try:
        removed = await _svc(request).delete(principal, cmd.ids, cmd.delete_all)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "datasets_delete", err, ids=cmd.ids or (), compat=profile)
    if profile == "ragflow_0_24":
        if not cmd.ids and not cmd.delete_all:
            return JSONResponse(delete_noop_v024())
        return JSONResponse(delete_ok_v024())
    return ok_result({"success_count": removed})
