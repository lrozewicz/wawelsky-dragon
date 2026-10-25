"""Trasy ingestii i sprawdzenia embeddingu (zadanie DS2): v0.27.2, złoto --07..--10."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import ok_result
from app.api.ragflow.normalize.dataset_ingestions import (
    embedding_check_command,
    list_ingestions,
)
from app.api.ragflow.present.dataset_ingestions import (
    embedding_check,
    ingestion_log,
    ingestion_logs_list,
    ingestion_summary,
)
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.dataset_ingestions import (
    EmbeddingCheckData,
    EmbeddingCheckRequest,
    IngestionLog,
    IngestionsList,
    IngestionSummary,
)
from app.core.error_codes import RetCode
from app.services.dataset_ingestions import (
    MSG_NOT_EFFECTIVE,
    DatasetIngestionsService,
)

router = APIRouter(prefix="/api/v1", tags=["datasets"])


def _svc(request: Request) -> DatasetIngestionsService:
    """Usługa logów/embeddingu per żądanie (C0 p. 2)."""
    return DatasetIngestionsService(container_of(request))


# Kolejność: ``ingestions/summary`` PRZED ``ingestions/{log_id}`` — inaczej ``summary``
# zostałoby dopasowane jako identyfikator logu (FastAPI rozstrzyga po kolejności rejestracji).
@router.get(
    "/datasets/{dataset_id}/ingestions/summary",
    operation_id="datasets_ingestions_summary",
    responses={200: {"model": RagflowOk[IngestionSummary]}},
)
async def ingestions_summary(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET …/ingestions/summary — liczby i statusy dokumentów datasetu (--07)."""
    summary = await _svc(request).summary(principal, dataset_id)
    return ok_result(ingestion_summary(summary, profile))


@router.get(
    "/datasets/{dataset_id}/ingestions",
    operation_id="datasets_ingestions_list",
    responses={200: {"model": RagflowOk[IngestionsList]}},
    openapi_extra=extra_doc(
        query=[
            query_param("page", {"type": "integer"}, "Numer strony (od 1)"),
            query_param("page_size", {"type": "integer"}, "Liczba logów na stronie"),
            query_param(
                "orderby",
                {"type": "string"},
                "Pole sortowania: create_time albo update_time",
            ),
            query_param("desc", {"type": "boolean"}, "Sortowanie malejące (domyślnie true)"),
            query_param(
                "log_type",
                {"type": "string"},
                "Rodzaj logów: dataset (domyślnie) albo file",
            ),
            query_param(
                "operation_status",
                {"type": "array", "items": {"type": "string"}},
                "Filtr stanu operacji (kody run 0-5)",
            ),
            query_param("keywords", {"type": "string"}, "Filtr nazwy pliku"),
            query_param("create_date_from", {"type": "string"}, "Początek zakresu create_date"),
            query_param("create_date_to", {"type": "string"}, "Koniec zakresu create_date"),
        ]
    ),
)
async def list_ingestions_route(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET …/ingestions — logi plików; ``log_type=dataset`` → pusta lista (--08)."""
    query = list_ingestions(
        request.query_params, profile, max_size=container_of(request).settings.max_page_size
    )
    logs, total = await _svc(request).list_logs(principal, dataset_id, query)
    return ok_result(ingestion_logs_list(logs, total, profile))


@router.get(
    "/datasets/{dataset_id}/ingestions/{log_id}",
    operation_id="datasets_ingestions_get",
    responses={200: {"model": RagflowOk[IngestionLog]}},
)
async def get_ingestion(
    dataset_id: str, log_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET …/ingestions/{log_id} — jeden log pliku; brak → code 102 „Log not found" (--09)."""
    log = await _svc(request).get_log(principal, dataset_id, log_id)
    return ok_result(ingestion_log(log, profile))


@router.post(
    "/datasets/{dataset_id}/embedding/check",
    operation_id="datasets_embedding_check",
    responses={200: {"model": RagflowOk[EmbeddingCheckData]}},
    openapi_extra=extra_doc(EmbeddingCheckRequest),
)
async def embedding_check_route(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST …/embedding/check — re-embedding próbki chunków i cosinus z zapisanym (--10).

    Poniżej progu 0,9 upstream zwraca HTTP 200 z ``code`` 10 (RetCode.NOT_EFFECTIVE)
    i komunikatem ostrzegawczym, dane w ``data`` (nie koperta sukcesu).
    """
    cmd = embedding_check_command(await json_body(request), profile)
    check = await _svc(request).check_embedding(
        principal, dataset_id, embd_id=cmd.embd_id, check_num=cmd.check_num
    )
    data = embedding_check(check, profile)
    if not check.effective:
        return JSONResponse(
            {"code": RetCode.NOT_EFFECTIVE, "message": MSG_NOT_EFFECTIVE, "data": data}
        )
    return ok_result(data)
