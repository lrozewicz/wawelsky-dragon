"""Trasy Dify external knowledge API (brief OD p. 1; K3 §3 przestrzeń ``ragflow-dify``).

Kopertę błędu skleja ``app/api/errors.py`` (kod RAGFlow → prawdziwy status HTTP wg K3 §3):
brak bazy wiedzy to ``ResourceNotFound`` (kod 404 → HTTP 404), baza cudza —
``AuthenticationFailed`` (kod 109 → HTTP 403), złe argumenty — ``ValidationFailed``
(kod 101 → HTTP 400).
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep, CompatProfile
from app.api.ragflow.envelope import ok_true
from app.api.ragflow.normalize.dify import parse_dify_body, parse_dify_query
from app.api.ragflow.present.dify import dify_records
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.dify import DifyRecords, DifyRetrievalRequest
from app.domain.policy import Principal
from app.services.dify import DifyQuery, DifyService

router = APIRouter(prefix="/api/v1", tags=["dify"])

_RECORDS_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {
        "model": DifyRecords,
        "description": "Rekordy retrievalu — odpowiedź surowa Dify, bez koperty code",
    }
}

_GET_PARAMS = (
    query_param("knowledge_id", {"type": "string"}, "Id bazy wiedzy (dataset)"),
    query_param("query", {"type": "string"}, "Treść zapytania"),
    query_param("use_kg", {"type": "boolean"}, "Ignorowane: WD nie ma grafu wiedzy"),
    query_param("top_k", {"type": "integer"}, "Liczba wyników (domyślnie 1024)"),
    query_param("score_threshold", {"type": "number"}, "Próg podobieństwa (domyślnie 0.0)"),
)


async def _retrieve(
    request: Request, principal: Principal, q: DifyQuery, profile: CompatProfile
) -> JSONResponse:
    """Wspólny przepływ POST/GET: usługa Dify → rekordy (bez koperty ``code``)."""
    result = await DifyService(container_of(request)).retrieve(principal, q)
    return JSONResponse(dify_records(result, profile))


@router.post(
    "/dify/retrieval",
    operation_id="dify_retrieval_post",
    responses=_RECORDS_RESPONSES,
    openapi_extra=extra_doc(DifyRetrievalRequest),
)
async def dify_retrieval_post(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST /dify/retrieval (upstream :111-290)."""
    return await _retrieve(request, principal, parse_dify_body(await json_body(request)), profile)


@router.get(
    "/dify/retrieval",
    operation_id="dify_retrieval_get",
    responses=_RECORDS_RESPONSES,
    openapi_extra=extra_doc(query=_GET_PARAMS),
)
async def dify_retrieval_get(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET /dify/retrieval?knowledge_id=&query= (upstream :111, v0.27.2)."""
    return await _retrieve(
        request, principal, parse_dify_query(dict(request.query_params)), profile
    )


@router.get(
    "/dify/retrieval/health",
    operation_id="dify_retrieval_health",
    responses={200: {"model": RagflowOk[bool]}},
)
async def dify_retrieval_health() -> JSONResponse:
    """GET /dify/retrieval/health (upstream :315) — bez uwierzytelniania."""
    return ok_true()
