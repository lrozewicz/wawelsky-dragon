"""Trasy dokumentów poza ``/datasets/{id}/documents`` (scenariusz documents_extras, E2-1 DOC).

Osobny plik od ``routes/documents.py`` (limit 400 linii). Router jest dołączany PRZED
``routes.documents``, bo ``PATCH …/documents/metadatas`` musi trafić przed trasą
``PATCH …/documents/{document_id}`` (FastAPI dopasowuje trasy po kolejności rejestracji).

Zakres fragmentu: ``PATCH …/documents/metadatas`` (kroki 13-14 złota) oraz
``POST …/documents/batch-update-status`` (kroki 15-16 złota).
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import ok_result
from app.api.ragflow.normalize.documents import batch_status, metadatas
from app.api.ragflow.schemas.common import RagflowOk, extra_doc
from app.api.ragflow.schemas.documents import (
    BatchUpdateStatusRequest,
    DocumentStatus,
    MetadatasResult,
    MetadataUpdatesRequest,
)
from app.core.error_codes import RetCode
from app.services.documents_extra import MSG_STATUS_PARTIAL, DocumentExtraService

router = APIRouter(prefix="/api/v1", tags=["documents"])


def _svc(request: Request) -> DocumentExtraService:
    """Usługa dodatkowych tras dokumentów per żądanie (C0 p. 2)."""
    return DocumentExtraService(container_of(request))


@router.patch(
    "/datasets/{dataset_id}/documents/metadatas",
    operation_id="documents_metadatas",
    responses={200: {"model": RagflowOk[MetadatasResult]}},
    openapi_extra=extra_doc(MetadataUpdatesRequest),
)
async def update_metadatas(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """PATCH …/documents/metadatas — zbiorcza zmiana meta_fields (DOC:1337)."""
    cmd = metadatas(await json_body(request), profile)
    updated, matched = await _svc(request).metadatas(
        principal,
        dataset_id,
        document_ids=cmd.document_ids,
        updates=cmd.updates,
        deletes=cmd.deletes,
        condition=cmd.condition,
    )
    return ok_result({"updated": updated, "matched_docs": matched})


@router.post(
    "/datasets/{dataset_id}/documents/batch-update-status",
    operation_id="documents_batch_update_status",
    responses={200: {"model": RagflowOk[dict[str, DocumentStatus]]}},
    openapi_extra=extra_doc(BatchUpdateStatusRequest),
)
async def batch_update_status(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST …/documents/batch-update-status — zbiorcza zmiana statusu (DOC:1973)."""
    cmd = batch_status(await json_body(request), profile)
    result = await _svc(request).set_status(principal, dataset_id, cmd.doc_ids, cmd.status)
    if result.has_error:  # DOC:2064 — częściowy błąd: kod 500 i „Partial failure"
        return JSONResponse(
            {
                "code": int(RetCode.SERVER_ERROR),
                "message": MSG_STATUS_PARTIAL,
                "data": result.entries,
            }
        )
    return ok_result(result.entries)
