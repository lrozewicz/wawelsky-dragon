"""Trasy /api/v1 retrieval: POST /retrieval, /datasets/search, /datasets/{id}/search (C4.3)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep, CompatProfile
from app.api.ragflow.envelope import ok_result
from app.api.ragflow.normalize.retrieval import retrieval_query
from app.api.ragflow.present.references import retrieval_result
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.common import RagflowOk, extra_doc
from app.api.ragflow.schemas.retrieval import RetrievalRequest, RetrievalResult
from app.core.errors import NotFound, PermissionDenied
from app.domain.policy import Principal

router = APIRouter(prefix="/api/v1", tags=["retrieval"])


async def _search(
    request: Request, principal: Principal, profile: CompatProfile, dataset_id: str | None
) -> JSONResponse:
    """Wspólny przepływ C4.3: retrieval_query → RetrievalService.retrieve → ok_result."""
    q = retrieval_query(
        await json_body(request),
        profile,
        max_size=container_of(request).settings.max_page_size,
        path_dataset_id=dataset_id,
    )
    r = await container_of(request).retrieval.retrieve(principal, q)
    return ok_result(retrieval_result(r, profile))


@router.post(
    "/retrieval",
    operation_id="retrieval_query",
    responses={200: {"model": RagflowOk[RetrievalResult]}},
    openapi_extra=extra_doc(RetrievalRequest),
)
async def retrieval(request: Request, principal: PrincipalDep, profile: CompatDep) -> JSONResponse:
    """POST /retrieval (CHK:333-341)."""
    try:
        return await _search(request, principal, profile, None)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "retrieval_query", err, compat=profile)


@router.post(
    "/datasets/search",
    operation_id="retrieval_search",
    responses={200: {"model": RagflowOk[RetrievalResult]}},
    openapi_extra=extra_doc(RetrievalRequest),
)
async def datasets_search(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST /datasets/search (CHK:335-336) — bez datasetu w ścieżce."""
    try:
        return await _search(request, principal, profile, None)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "retrieval_search", err, compat=profile)


@router.post(
    "/datasets/{dataset_id}/search",
    operation_id="retrieval_search_dataset",
    responses={200: {"model": RagflowOk[RetrievalResult]}},
    openapi_extra=extra_doc(RetrievalRequest),
)
async def dataset_search(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST /datasets/{dataset_id}/search (CHK:334) — dataset z ścieżki."""
    try:
        return await _search(request, principal, profile, dataset_id)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "retrieval_search_dataset", err, compat=profile)
