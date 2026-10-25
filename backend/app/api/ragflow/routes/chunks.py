"""Trasy /api/v1/datasets/{id}/documents/{id}/chunks (kontrakt E1-9a C3.5)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import ok_result
from app.api.ragflow.normalize.chunks import (
    create_chunk,
    delete_chunks,
    duplicate_chunk_ids,
    list_chunks,
    switch_chunks,
    update_chunk,
)
from app.api.ragflow.present.chunks import chunk_created, chunk_page, chunk_source
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.chunks import (
    ChunkCreated,
    ChunkPage,
    ChunkSource,
    CreateChunkRequest,
    DeleteChunksRequest,
    SwitchChunksRequest,
    UpdateChunkRequest,
)
from app.api.ragflow.schemas.common import RagflowOk, RagflowOkEmpty, extra_doc, query_param
from app.core.errors import NotFound, PermissionDenied
from app.services.chunks import ChunkService

router = APIRouter(prefix="/api/v1", tags=["chunks"])


def _svc(request: Request) -> ChunkService:
    """Usługa chunków per żądanie (C0 p. 2)."""
    return ChunkService(container_of(request))


@router.get(
    "/datasets/{dataset_id}/documents/{document_id}/chunks",
    operation_id="chunks_list",
    responses={200: {"model": RagflowOk[ChunkPage]}},
    openapi_extra=extra_doc(
        query=[
            query_param("page", {"type": "integer"}, "Numer strony (od 1)"),
            query_param("page_size", {"type": "integer"}, "Liczba chunków na stronie"),
            query_param("keywords", {"type": "string"}, "Filtr pełnotekstowy po treści"),
            query_param("id", {"type": "string"}, "Filtr: identyfikator chunka"),
            query_param(
                "available",
                {"type": "string"},
                "Filtr: 'true' → tylko włączone; każda inna wartość → tylko wyłączone;"
                " brak → wszystkie",
            ),
        ]
    ),
)
async def list_chunks_route(
    dataset_id: str, document_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET …/chunks — strona listy chunków z total i dokumentem (C3.5)."""
    q = list_chunks(
        request.query_params, profile, max_size=container_of(request).settings.max_page_size
    )
    try:
        p = await _svc(request).list(
            principal,
            dataset_id,
            document_id,
            page=q.page,
            page_size=q.page_size,
            keywords=q.keywords,
            chunk_id=q.chunk_id,
            available=q.available,
        )
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "chunks_list", err, compat=profile)
    return ok_result(chunk_page(p, profile))


@router.post(
    "/datasets/{dataset_id}/documents/{document_id}/chunks",
    operation_id="chunks_create",
    responses={200: {"model": RagflowOk[ChunkCreated]}},
    openapi_extra=extra_doc(CreateChunkRequest, required=False),
)
async def create_chunk_route(
    dataset_id: str, document_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST …/chunks — ręczny chunk z FULLTEXT i wektorem (C3.5)."""
    cmd = create_chunk(await json_body(request), profile)
    try:
        c = await _svc(request).create(
            principal,
            dataset_id,
            document_id,
            content=cmd.content,
            important_keywords=cmd.important_keywords,
            questions=cmd.questions,
            tag_kwd=cmd.tag_kwd,
        )
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "chunks_create", err, compat=profile)
    return ok_result(chunk_created(c, profile, with_tags=cmd.tag_kwd_given))


@router.get(
    "/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}",
    operation_id="chunks_get",
    responses={200: {"model": RagflowOk[ChunkSource]}},
)
async def get_chunk_route(  # noqa: PLR0913, PLR0917 — ścieżka i zależności z kontraktu C3.5
    dataset_id: str,
    document_id: str,
    chunk_id: str,
    request: Request,
    principal: PrincipalDep,
    profile: CompatDep,
) -> JSONResponse:
    """GET …/chunks/{id} — surowy dokument magazynu (chunk_api.py:639-656, C3.5)."""
    c = await _svc(request).get(principal, dataset_id, document_id, chunk_id)
    return ok_result(chunk_source(c, profile))


@router.patch(
    "/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}",
    operation_id="chunks_update",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(UpdateChunkRequest, required=False),
)
@router.put(
    "/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}",
    operation_id="chunks_update_legacy",
    deprecated=True,
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(UpdateChunkRequest, required=False),
)
async def update_chunk_route(  # noqa: PLR0913, PLR0917 — ścieżka i zależności z kontraktu C3.5
    dataset_id: str,
    document_id: str,
    chunk_id: str,
    request: Request,
    principal: PrincipalDep,
    profile: CompatDep,
) -> JSONResponse:
    """PATCH i PUT …/chunks/{id} — aktualizacja; odpowiedź bez data (C3.5)."""
    fields = update_chunk(await json_body(request), profile)
    await _svc(request).update(principal, dataset_id, document_id, chunk_id, fields)
    return ok_result()


@router.patch(
    "/datasets/{dataset_id}/documents/{document_id}/chunks",
    operation_id="chunks_switch",
    responses={200: {"model": RagflowOk[bool]}},
    openapi_extra=extra_doc(SwitchChunksRequest),
)
async def switch_chunks_route(
    dataset_id: str, document_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """PATCH …/chunks — przełączenie available; data = true (CHK:1357, C3.5)."""
    ids, available = switch_chunks(await json_body(request), profile)
    await _svc(request).switch(principal, dataset_id, document_id, ids, available)
    return ok_result(True)


@router.delete(
    "/datasets/{dataset_id}/documents/{document_id}/chunks",
    operation_id="chunks_delete",
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(DeleteChunksRequest, required=False),
)
async def delete_chunks_route(
    dataset_id: str, document_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """DELETE …/chunks — usunięcie wg ids albo delete_all; odpowiedź bez data (C3.5)."""
    cmd = delete_chunks(await json_body(request), profile)
    try:
        deleted = await _svc(request).delete(
            principal, dataset_id, document_id, cmd.chunk_ids, cmd.delete_all
        )
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "chunks_delete", err, compat=profile)
    duplicates = duplicate_chunk_ids(cmd.chunk_ids)
    if duplicates:
        # CHK:1223-1226: powtórzone id w żądaniu → data z liczbą usuniętych i komunikatami.
        return ok_result({"success_count": deleted, "errors": duplicates})
    return ok_result()
