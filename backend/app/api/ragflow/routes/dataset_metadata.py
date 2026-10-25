"""Trasy metadanych datasetu (zadanie DS3, E2-1): v0.27.2, złoto --11, --12, --15..--18."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import ok_result
from app.api.ragflow.normalize.common import json_object_body
from app.api.ragflow.normalize.dataset_metadata import (
    config_payload,
    metadata_config,
    metadata_dataset_ids,
    metadata_doc_ids,
    metadata_update,
)
from app.api.ragflow.present.dataset_metadata import (
    config_data,
    flattened_data,
    summary_data,
    update_data,
)
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.dataset_metadata import (
    MetadataConfigData,
    MetadataConfigRequest,
    MetadataSummaryData,
    MetadataUpdateData,
    MetadataUpdateRequest,
)
from app.core.errors import NotFound, PermissionDenied
from app.services.dataset_metadata import BUILT_IN_KEY, METADATA_KEY, DatasetMetadataService

router = APIRouter(prefix="/api/v1", tags=["datasets"])


def _svc(request: Request) -> DatasetMetadataService:
    """Usługa metadanych per żądanie (C0 p. 2)."""
    return DatasetMetadataService(container_of(request))


# ``/datasets/metadata/flattened`` (3 segmenty) nie koliduje z trasami
# ``/datasets/{dataset_id}/…`` (4 segmenty) — brak zależności od kolejności rejestracji.
@router.get(
    "/datasets/metadata/flattened",
    operation_id="datasets_metadata_flattened",
    responses={200: {"model": RagflowOk[dict[str, dict[str, list[str]]]]}},
    openapi_extra=extra_doc(
        query=[
            query_param(
                "dataset_ids",
                {"type": "string"},
                "Identyfikatory datasetów po przecinku (wymagane)",
            )
        ]
    ),
)
async def metadata_flattened_route(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET /datasets/metadata/flattened — {pole: {wartość: [document_id]}} (--18).

    ``dataset_ids`` z query; brak albo same puste → code 102 „Lack of dataset_ids in
    query parameters" (upstream ``dataset_api.py:59``).
    """
    dataset_ids = metadata_dataset_ids(request.query_params)
    flattened = await _svc(request).flattened(principal, dataset_ids)
    return ok_result(flattened_data(flattened))


@router.get(
    "/datasets/{dataset_id}/metadata/config",
    operation_id="datasets_metadata_config_get",
    responses={200: {"model": RagflowOk[MetadataConfigData]}},
)
async def metadata_config_get(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET …/metadata/config — konfiguracja metadanych datasetu, pusta gdy nieustawiona (--11)."""
    config = await _svc(request).get_config(principal, dataset_id)
    return ok_result(config_data(config))


@router.put(
    "/datasets/{dataset_id}/metadata/config",
    operation_id="datasets_metadata_config_update",
    responses={200: {"model": RagflowOk[MetadataConfigData]}},
    openapi_extra=extra_doc(MetadataConfigRequest),
)
async def metadata_config_update(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """PUT …/metadata/config — zapis obu list pól do ``parser_config``; echo walidacji (--12)."""
    # Ciało ostrą ścieżką upstream ``validate_and_parse_json_request`` (101): brak ciała albo inny
    # ``Content-Type`` to błąd argumentu, nie pusty zapis (E2-3a1 DEC-087 p. 1). Opis trasy
    # w ``backend/openapi.json`` powstaje z docstringa, więc uzasadnienie trzymamy w komentarzu.
    cmd = metadata_config(await json_object_body(request), profile)
    payload = config_payload(cmd)
    saved = await _svc(request).put_config(
        principal,
        dataset_id,
        metadata=payload[METADATA_KEY],
        built_in_metadata=payload[BUILT_IN_KEY],
    )
    return ok_result(config_data(saved))


@router.get(
    "/datasets/{dataset_id}/metadata/summary",
    operation_id="datasets_metadata_summary",
    responses={200: {"model": RagflowOk[MetadataSummaryData]}},
    openapi_extra=extra_doc(
        query=[query_param("doc_ids", {"type": "string"}, "Identyfikatory dokumentów po przecinku")]
    ),
)
async def metadata_summary_route(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET …/metadata/summary — agregacja wartości ``meta_fields`` dokumentów (--15/--17)."""
    # Cudzy/nieistniejący dataset → 102 „You don't own the dataset <id>. " (upstream
    # ``document_api.py:337``); komunikat bierze profil ``datasets_metadata_summary``
    # (docstring trafia do opisu trasy w ``backend/openapi.json``, stąd komentarz).
    doc_ids = metadata_doc_ids(request.query_params)
    try:
        summary = await _svc(request).summary(principal, dataset_id, doc_ids)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "datasets_metadata_summary", err, compat=profile)
    return ok_result(summary_data(summary))


@router.post(
    "/datasets/{dataset_id}/metadata/update",
    operation_id="datasets_metadata_update",
    responses={200: {"model": RagflowOk[MetadataUpdateData]}},
    openapi_extra=extra_doc(MetadataUpdateRequest),
)
async def metadata_update_route(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST …/metadata/update — masowa zmiana metadanych wg ``selector`` (--16)."""
    cmd = metadata_update(await json_body(request), profile)
    result = await _svc(request).update(
        principal,
        dataset_id,
        document_ids=cmd.document_ids,
        condition=cmd.condition,
        updates=cmd.updates,
        deletes=cmd.deletes,
    )
    return ok_result(update_data(result))
