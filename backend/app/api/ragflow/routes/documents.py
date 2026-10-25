"""Trasy /api/v1/datasets/{id}/documents + legacy /datasets/{id}/chunks (kontrakt E1-9a C2.5)."""

import mimetypes
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile
from starlette.responses import Response

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import argument_error, data_error, ok, ok_result, server_error
from app.api.ragflow.file_safety import ensure_file_count
from app.api.ragflow.normalize.common import json_object_body
from app.api.ragflow.normalize.documents import (
    BadMetadataCondition,
    delete_documents,
    document_ids,
    document_metadata_config_body,
    list_documents,
    update_document,
)
from app.api.ragflow.present.documents import (
    document_full,
    document_listed,
    document_metadata_config,
    document_uploaded,
)
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.common import RagflowOk, RagflowOkEmpty, extra_doc, query_param
from app.api.ragflow.schemas.datasets import SuccessCount
from app.api.ragflow.schemas.documents import (
    DeletedCount,
    DeleteDocumentsRequest,
    DocumentFull,
    DocumentIdsRequest,
    DocumentList,
    DocumentMetadataConfig,
    DocumentMetadataConfigRequest,
    DocumentUploaded,
    StopResult,
    UpdateDocumentRequest,
    UploadDocumentsForm,
)
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.services.dataset_metadata import MSG_DOCUMENT_NOT_IN_DATASET, DatasetMetadataService
from app.services.documents import (
    MSG_DOCUMENT_NOT_OWNED,
    MSG_DOCUMENT_NOT_OWNED_V024,
    DocumentNotOwned,
    DocumentService,
    UnsupportedFileType,
)
from app.services.ingest import UploadSource

router = APIRouter(prefix="/api/v1", tags=["documents"])


def _svc(request: Request) -> DocumentService:
    """Usługa dokumentów per żądanie (C0 p. 2)."""
    return DocumentService(container_of(request))


def _meta_svc(request: Request) -> DatasetMetadataService:
    """Usługa metadanych per żądanie (C0 p. 2) — trasa S-320 ``…/metadata/config``."""
    return DatasetMetadataService(container_of(request))


async def _read_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    """Strumień pliku partiami 1 MiB (C2.5)."""
    while data := await file.read(1 << 20):
        yield data


async def _upload_sources(request: Request) -> list[UploadSource]:
    """Pliki z pola multipart „file" → źródła; komunikaty upstream (DOC:655, :661)."""
    form = await request.form()
    files = [f for f in form.getlist("file") if isinstance(f, UploadFile)]
    ensure_file_count(files)
    if not files:
        raise ValidationFailed("No file part!")
    sources: list[UploadSource] = []
    for file in files:
        name = file.filename
        if not name:
            raise ValidationFailed("No file selected!")
        sources.append(UploadSource(stream=_read_chunks(file), filename=name))
    return sources


@router.post(
    "/datasets/{dataset_id}/documents",
    operation_id="documents_upload",
    responses={200: {"model": RagflowOk[list[DocumentUploaded]]}},
    openapi_extra=extra_doc(UploadDocumentsForm, media_type="multipart/form-data"),
)
async def upload(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST …/documents — upload multipart (C2.5)."""
    sources = await _upload_sources(request)
    try:
        rows = await _svc(request).upload(principal, dataset_id, sources)
    except UnsupportedFileType as err:
        # Upstream DOC:571/705: nieobsługiwane rozszerzenie → kod 500 z nazwą pliku
        # (nie 101 z `file_suffix` — `file_suffix` zostaje bez zmian, DEC-088 p. 4).
        return server_error(err.message)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_upload", err, compat=profile)
    return ok_result([document_uploaded(row, profile) for row in rows])


@router.get(
    "/datasets/{dataset_id}/documents",
    operation_id="documents_list",
    responses={200: {"model": RagflowOk[DocumentList]}},
    openapi_extra=extra_doc(
        query=[
            query_param("page", {"type": "integer"}, "Numer strony (od 1)"),
            query_param("page_size", {"type": "integer"}, "Liczba dokumentów na stronie"),
            query_param(
                "orderby", {"type": "string"}, "Pole sortowania: create_time, update_time albo name"
            ),
            query_param("desc", {"type": "boolean"}, "Sortowanie malejące (domyślnie true)"),
            query_param("id", {"type": "string"}, "Filtr: identyfikator dokumentu"),
            query_param("name", {"type": "string"}, "Filtr: nazwa dokumentu"),
            query_param("keywords", {"type": "string"}, "Filtr pełnotekstowy po nazwie"),
            query_param(
                "ids", {"type": "array", "items": {"type": "string"}}, "Filtr: identyfikatory"
            ),
            query_param(
                "run",
                {"type": "array", "items": {"type": "string"}},
                "Filtr statusu parsowania (UNSTART…SCHEDULE albo kod 0-5)",
            ),
            query_param(
                "suffix", {"type": "array", "items": {"type": "string"}}, "Filtr: rozszerzenia"
            ),
            query_param(
                "metadata_condition",
                {"type": "string"},
                'Filtr metadanych: JSON ``{"logic": "and"|"or", conditions: '
                "[{name, comparison_operator, value}]}``",
            ),
        ]
    ),
)
async def list_documents_route(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """GET …/documents — strona listy z total (złoto ma „message"; C2.5)."""
    # ``metadata_condition`` bez poprawnego JSON-a → 102 kopertą BEZ ``data`` (upstream
    # ``get_data_error_result``, złoto ``metadata_e6--34``); przez handler WDError byłoby
    # ``data: null``. Sprawdzenie orderby idzie pierwsze (mieszka w ``list_documents``).
    try:
        q = list_documents(
            request.query_params, profile, max_size=container_of(request).settings.max_page_size
        )
    except BadMetadataCondition as err:
        return data_error(err.message)
    try:
        rows, total = await _svc(request).list(principal, dataset_id, q)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_list", err, compat=profile)
    docs = [document_listed(row, nickname, profile) for row, nickname in rows]
    return ok({"docs": docs, "total": total})


@router.post(
    "/datasets/{dataset_id}/documents/parse",
    operation_id="documents_parse",
    responses={200: {"model": RagflowOk[SuccessCount]}},
    openapi_extra=extra_doc(DocumentIdsRequest),
)
async def parse_documents(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST …/documents/parse — zlecenie parsowania (C2.5)."""
    ids = document_ids(await json_body(request), profile)
    try:
        count, errors = await _svc(request).parse(principal, dataset_id, ids)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_parse", err, compat=profile)
    data: dict[str, Any] = {"success_count": count}
    if errors:  # upstream: powtórzone id → komunikaty w data (document_api.py:1640-1643)
        data["errors"] = errors
    return ok_result(data)


@router.post(
    "/datasets/{dataset_id}/documents/stop",
    operation_id="documents_stop",
    responses={200: {"model": RagflowOk[StopResult]}},
    openapi_extra=extra_doc(DocumentIdsRequest),
)
async def stop_documents(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST …/documents/stop — anulowanie; „errors" tylko gdy niepuste (C2.5)."""
    ids = document_ids(await json_body(request), profile)
    try:
        stopped, errors = await _svc(request).stop(principal, dataset_id, ids)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_stop", err, compat=profile)
    data: dict[str, Any] = {"success_count": stopped}
    if errors:
        data["errors"] = errors
    return ok_result(data)


@router.get(
    "/datasets/{dataset_id}/documents/{document_id}",
    operation_id="documents_download",
    response_class=Response,
    responses={
        200: {
            "description": "Treść pliku (Content-Disposition: attachment)",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def download_document(
    dataset_id: str,
    document_id: str,
    request: Request,
    principal: PrincipalDep,
    profile: CompatDep,
) -> Response:
    """GET …/documents/{id} — strumień pliku z nagłówkiem attachment (C2.5).

    Profil 0.24.0: ``application/octet-stream`` zawsze (złoto documents_parse--07,
    upstream v0.24 ``doc.py`` ustawia ten mimetype dla pobrania). 0.27.2: z rozszerzenia.
    """
    try:
        row, iterator = await _svc(request).open_file(principal, dataset_id, document_id)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_download", err, compat=profile)
    media_type = mimetypes.guess_type(row.name)[0] or "application/octet-stream"
    if profile == "ragflow_0_24":
        media_type = "application/octet-stream"
    return StreamingResponse(
        iterator,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.name)}"},
    )


@router.patch(
    "/datasets/{dataset_id}/documents/{document_id}",
    operation_id="documents_update",
    responses={200: {"model": RagflowOk[DocumentFull]}},
    openapi_extra=extra_doc(UpdateDocumentRequest, required=False),
)
@router.put(
    "/datasets/{dataset_id}/documents/{document_id}",
    operation_id="documents_update_legacy",
    deprecated=True,
    responses={200: {"model": RagflowOk[DocumentFull]}},
    openapi_extra=extra_doc(UpdateDocumentRequest, required=False),
)
async def update_document_route(
    dataset_id: str, document_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """PATCH i PUT …/documents/{id} — aktualizacja metadanych (C2.5)."""
    fields = update_document(await json_body(request), profile)
    try:
        row = await _svc(request).update(principal, dataset_id, document_id, fields)
    except DocumentNotOwned:
        # Dokument nie należy do datasetu: własny komunikat trasy, zależny od profilu
        # (v0.27.2 „the dataset doesn't own the document", DOC:223; v0.24.0 z kropką,
        # sdk/doc.py:244) — nie przez profil odmowy, ten obsługuje brak dostępu do datasetu.
        message = (
            MSG_DOCUMENT_NOT_OWNED_V024 if profile == "ragflow_0_24" else MSG_DOCUMENT_NOT_OWNED
        )
        return data_error(message)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_update", err, compat=profile)
    return ok_result(document_full(row, profile))


@router.put(
    "/datasets/{dataset_id}/documents/{document_id}/metadata/config",
    operation_id="documents_metadata_config",
    responses={200: {"model": RagflowOk[DocumentMetadataConfig]}},
    openapi_extra=extra_doc(DocumentMetadataConfigRequest),
)
async def document_metadata_config_route(
    dataset_id: str,
    document_id: str,
    request: Request,
    principal: PrincipalDep,
    profile: CompatDep,
) -> JSONResponse:
    """PUT …/documents/{id}/metadata/config — JSON-Schema metadanych dokumentu (S-320)."""
    # Kolejność i koperty wg upstream ``document_api.py:1262-1288``: brak pola ``metadata``
    # → 101 „metadata is required" bez klucza ``data``; dokument spoza datasetu → 102
    # „document <id> not found in dataset <id>" bez klucza ``data``; dostęp do datasetu idzie
    # profilem odmowy trasy (``documents_update``: 102 „you don't own the dataset").
    try:
        metadata = document_metadata_config_body(await json_object_body(request), profile)
    except ValidationFailed as err:
        return argument_error(err.message)
    try:
        row = await _meta_svc(request).put_document_metadata_config(
            principal, dataset_id, document_id, metadata
        )
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_update", err, compat=profile)
    if row is None:
        return data_error(
            MSG_DOCUMENT_NOT_IN_DATASET.format(document_id=document_id, dataset_id=dataset_id)
        )
    return ok_result(document_metadata_config(row, profile))


@router.delete(
    "/datasets/{dataset_id}/documents",
    operation_id="documents_delete",
    responses={200: {"model": RagflowOk[DeletedCount]}},
    openapi_extra=extra_doc(DeleteDocumentsRequest, required=False),
)
async def delete_documents_route(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """DELETE …/documents — usunięcie wg ids albo delete_all (DOC:1213)."""
    # Ciało czytamy ostrą ścieżką upstream (``validate_and_parse_json_request``, 101);
    # ``json_body`` (C9) przyjmie nie-obiekt i zamieni go na puste ciało (E2-3a1 DEC-087 p. 1).
    # Uzasadnienie w komentarzu, nie w docstringu — docstring trafia do ``backend/openapi.json``.
    cmd = delete_documents(await json_object_body(request), profile)
    try:
        removed = await _svc(request).delete(principal, dataset_id, cmd.ids, cmd.delete_all)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_delete", err, compat=profile)
    return ok_result({"deleted": removed})


@router.post(
    "/datasets/{dataset_id}/chunks",
    operation_id="documents_parse_legacy",
    deprecated=True,
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(DocumentIdsRequest),
)
async def legacy_parse(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """POST /datasets/{id}/chunks — legacy parse (CHK:275, odpowiedź bez data).

    Odmowa idzie tą samą trasą co ``documents_parse`` (złoto v0.24.0 ``errors_access--18``:
    102 „You don't own the dataset <id>."); sukces bez zmian (CRUD v0.24).
    """
    ids = document_ids(await json_body(request), profile)
    try:
        await _svc(request).parse(principal, dataset_id, ids)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_parse", err, compat=profile)
    return ok_result()


@router.delete(
    "/datasets/{dataset_id}/chunks",
    operation_id="documents_stop_legacy",
    deprecated=True,
    responses={200: {"model": RagflowOkEmpty}},
    openapi_extra=extra_doc(DocumentIdsRequest),
)
async def legacy_stop(
    dataset_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> JSONResponse:
    """DELETE /datasets/{id}/chunks — legacy stop (CHK:330, odpowiedź bez data).

    Odmowa jak ``documents_stop`` (złoto v0.24.0 ``errors_access--20``: 102
    „You don't own the dataset <id>."); sukces bez zmian.
    """
    ids = document_ids(await json_body(request), profile)
    try:
        await _svc(request).stop(principal, dataset_id, ids)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "documents_stop", err, compat=profile)
    return ok_result()
