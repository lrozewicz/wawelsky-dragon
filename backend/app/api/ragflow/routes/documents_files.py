"""Trasy plikowe dokumentów bez datasetu w ścieżce (scenariusz documents_extras, E2-1 DOC2).

Kroki 19-33 złota: ``POST /documents/ingest`` (19, 21, 23), ``POST /documents/upload`` (25),
``GET /documents/{id}`` (27), ``GET /documents/{id}/preview`` (29), ``GET /thumbnails`` (31)
i ``GET /documents/images/{id}`` (33).

Router dołączany PRZED ``documents_extra``/``documents``: ``/documents/images/{image_id}``
i ``/thumbnails`` muszą trafić przed ``/documents/{document_id}`` (FastAPI dopasowuje trasy
po kolejności rejestracji).
"""

import json
import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile
from starlette.responses import Response

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.envelope import ok_result, ok_true
from app.api.ragflow.file_safety import ensure_file_count
from app.api.ragflow.normalize.common import parse_model
from app.api.ragflow.present.documents_files import uploaded_file
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.documents_files import IngestRequest, UploadedFileInfo, UploadFileForm
from app.core.error_codes import RetCode
from app.core.errors import ValidationFailed
from app.services.documents_files import MSG_IMAGE_NOT_FOUND, DocumentFilesService, UploadedFile

router = APIRouter(prefix="/api/v1", tags=["documents"])

# Upstream DOC:161 (``upload_info``): brak części multipart i brak ?url=.
MSG_MISSING_INPUT = "Missing input: provide multipart file(s) or url"
# Upstream DOC:1311 (``/thumbnails``): pusta lista doc_ids.
MSG_LACK_OF_DOC_ID = 'Lack of "Document ID"'


def _svc(request: Request) -> DocumentFilesService:
    """Usługa tras plikowych per żądanie (C0 p. 2)."""
    return DocumentFilesService(container_of(request))


def _missing_image() -> Response:
    """Złoto --33: HTTP 200, ``application/json`` i kompaktowa koperta błędu z newline.

    Bajty są porównywane z złotem dokładnie (krok ``binary``), więc newline i brak spacji
    po ``:``/``,`` są wymagane — tak serializuje ``jsonify`` Quarta w v0.27.2.
    """
    body = json.dumps(
        {"code": int(RetCode.DATA_ERROR), "message": MSG_IMAGE_NOT_FOUND},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return Response(content=body + "\n", media_type="application/json")


@router.post(
    "/documents/ingest",
    operation_id="documents_ingest",
    responses={200: {"model": RagflowOk[bool]}},
    openapi_extra=extra_doc(IngestRequest),
)
async def ingest_documents(request: Request, principal: PrincipalDep) -> JSONResponse:
    """POST /documents/ingest — start (run='1') albo anulowanie (run='2') parsowania."""
    cmd = parse_model(IngestRequest, await json_body(request))
    await _svc(request).ingest(principal, cmd.doc_ids, run=cmd.run, delete=cmd.delete)
    return ok_true()


@router.post(
    "/documents/upload",
    operation_id="documents_upload_info",
    responses={200: {"model": RagflowOk[UploadedFileInfo | list[UploadedFileInfo]]}},
    openapi_extra=extra_doc(UploadFileForm, media_type="multipart/form-data"),
)
async def upload_file_info(request: Request, principal: PrincipalDep) -> JSONResponse:
    """POST /documents/upload — pliki bez datasetu; 1 plik → obiekt, wiele → lista (DOC:121)."""
    form = await request.form()
    files = [part for part in form.getlist("file") if isinstance(part, UploadFile)]
    ensure_file_count(files)
    if not files:
        raise ValidationFailed(MSG_MISSING_INPUT)
    infos: list[UploadedFile] = []
    for part in files:
        filename = part.filename
        if not filename:
            raise ValidationFailed(MSG_MISSING_INPUT)
        mime = part.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        infos.append(await _svc(request).upload(principal, filename, mime, await part.read()))
    # DOC:174-178: ``len(file_objs) == 1`` → obiekt, w przeciwnym razie lista opisów.
    if len(infos) == 1:
        return ok_result(uploaded_file(infos[0]))
    return ok_result([uploaded_file(info) for info in infos])


@router.get(
    "/thumbnails",
    operation_id="thumbnails_list",
    responses={200: {"model": RagflowOk[dict[str, str]]}},
    openapi_extra=extra_doc(
        query=[
            query_param(
                "doc_ids",
                {"type": "array", "items": {"type": "string"}},
                "Identyfikatory dokumentów (można powtarzać)",
            )
        ]
    ),
)
async def list_thumbnails(request: Request, principal: PrincipalDep) -> JSONResponse:
    """GET /thumbnails?doc_ids= — mapa doc_id → thumbnail (pusta dla plików tekstowych)."""
    doc_ids = request.query_params.getlist("doc_ids")
    if not doc_ids:
        raise ValidationFailed(MSG_LACK_OF_DOC_ID)
    return ok_result(await _svc(request).thumbnails(principal, doc_ids))


@router.get(
    "/documents/images/{image_id}",
    operation_id="documents_image_get",
    response_class=Response,
    responses={
        200: {
            "description": "Treść obrazu dokumentu; brak obiektu → koperta JSON (złoto --33)",
            "content": {
                "application/json": {"schema": {"type": "object"}},
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def document_image(image_id: str, request: Request, principal: PrincipalDep) -> Response:
    """GET /documents/images/{id} — obraz dokumentu; id to ``{dataset_id}-{object_key}``."""
    data = await _svc(request).image(principal, image_id)
    if data is None:
        return _missing_image()
    return Response(
        content=data, media_type=mimetypes.guess_type(image_id)[0] or "application/octet-stream"
    )


@router.get(
    "/documents/{document_id}",
    operation_id="documents_file_download",
    response_class=Response,
    responses={
        200: {
            "description": "Treść pliku (Content-Disposition: attachment); brak → koperta błędu",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def download_document_file(
    document_id: str, request: Request, principal: PrincipalDep
) -> StreamingResponse:
    """GET /documents/{id} — strumień pliku dokumentu (DOC:2200)."""
    row, iterator = await _svc(request).open(principal, document_id)
    return StreamingResponse(
        iterator,
        media_type=mimetypes.guess_type(row.name)[0] or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.name)}"},
    )


@router.get(
    "/documents/{document_id}/preview",
    operation_id="documents_file_preview",
    response_class=Response,
    responses={
        200: {
            "description": "Treść pliku do podglądu (inline); brak → koperta błędu",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def preview_document_file(
    document_id: str, request: Request, principal: PrincipalDep
) -> StreamingResponse:
    """GET /documents/{id}/preview — treść pliku bez wymuszania pobrania (DOC:2094)."""
    row, iterator = await _svc(request).open(principal, document_id)
    return StreamingResponse(
        iterator,
        media_type=mimetypes.guess_type(row.name)[0] or "application/octet-stream",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(row.name)}"},
    )
