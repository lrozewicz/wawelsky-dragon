"""Trasy menedżera plików /api/v1/files* (K16 §2, CONTRACT E4-5a §D1.8, §D5).

Port ``api/apps/restful_apis/file_api.py`` + ``file2document_api.py`` v0.27.2. Kolejność tras
w pliku jest wymuszona kontraktem: statyczne ``/files/move`` i ``/files/link-to-datasets`` przed
``/files/{file_id}`` (FastAPI dopasowuje trasy po kolejności rejestracji, a ``move`` pasuje do
wzorca ``{file_id}``). Koperta sukcesu to ``ok``/``ok_result``/``ok_true``: upstream ``get_result``
przy ``code 0`` nie dokłada ``message``, a komparator złota toleruje ten dodatkowy klucz (Q2,
K11 §5 p. 4). Nagłówki pobrania portują ``apply_download_file_response_headers`` i
``CONTENT_TYPE_MAP`` z ``api/utils/file_response.py``.
"""

import re
from typing import Final
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile
from starlette.responses import Response

from app.api.auth.principal import PrincipalDep, container_of
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import argument_error, data_error, ok, ok_result, ok_true
from app.api.ragflow.file_safety import ensure_file_count
from app.api.ragflow.normalize.common import json_object_body
from app.api.ragflow.normalize.files import (
    parse_file_create,
    parse_file_delete,
    parse_file_link,
    parse_file_list,
    parse_file_move,
)
from app.api.ragflow.present.files import (
    file_ancestors,
    file_created,
    file_list,
    file_parent_result,
)
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.files import (
    FileAncestors,
    FileCreated,
    FileDeleteRequest,
    FileDeleteResult,
    FileLinkRequest,
    FileList,
    FileMoveRequest,
    FileParentResult,
    FileUploadForm,
    FolderCreateBody,
)
from app.core.error_codes import RetCode
from app.core.errors import PermissionDenied, ValidationFailed
from app.domain.policy import Principal
from app.services.files import (
    MSG_DELETE_FAILED,
    MSG_MODE_INVALID,
    MSG_PARTIALLY_DELETED,
    FileRow,
    FilesService,
)

router = APIRouter(prefix="/api/v1", tags=["files"])

# Komunikaty multipart upstream ``file_api.py`` (101): brak części ``file`` i pusta nazwa pliku.
_MSG_NO_FILE_PART: Final = "No file part!"
_MSG_NO_FILE_SELECTED: Final = "No file selected!"

# Port ``CONTENT_TYPE_MAP`` (upstream ``api/utils/file_response.py``): rozszerzenie → typ MIME.
_CONTENT_TYPES: Final[dict[str, str]] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "pdf": "application/pdf",
    "csv": "text/csv",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain",
    "py": "text/plain",
    "js": "text/plain",
    "java": "text/plain",
    "c": "text/plain",
    "cpp": "text/plain",
    "h": "text/plain",
    "php": "text/plain",
    "go": "text/plain",
    "ts": "text/plain",
    "sh": "text/plain",
    "cs": "text/plain",
    "kt": "text/plain",
    "sql": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "mdx": "text/markdown",
    "htm": "text/html",
    "html": "text/html",
    "json": "application/json",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "avif": "image/avif",
    "heic": "image/heic",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
# Rozszerzenia/typy, dla których upstream wymusza pobranie z ``nosniff`` (file_response.py).
_FORCE_ATTACHMENT_EXTENSIONS: Final = frozenset(
    {"htm", "html", "shtml", "xht", "xhtml", "xml", "mhtml", "svg"}
)
_FORCE_ATTACHMENT_TYPES: Final = frozenset(
    {
        "text/html",
        "image/svg+xml",
        "application/xhtml+xml",
        "text/xml",
        "application/xml",
        "multipart/related",
    }
)


def _svc(request: Request) -> FilesService:
    """Usługa menedżera plików per żądanie (wzór ``routes/searches.py``)."""
    return FilesService(container_of(request))


def _base_name(filename: str) -> str:
    """Ostatni segment nazwy (upstream ``format_content_disposition``)."""
    return filename.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1]


def _download_headers(row: FileRow) -> tuple[str, dict[str, str]]:
    """Typ MIME i ``Content-Disposition`` pobrania.

    Port upstream ``apply_download_file_response_headers`` (``api/utils/file_response.py``).

    Nieznane rozszerzenie dostaje prefiks ``image/`` dla plików ``visual``, inaczej
    ``application/``; bez rozszerzenia zostaje ``application/octet-stream``.
    """
    match = re.search(r"\.([^.]+)$", row.name.lower())
    ext = match.group(1) if match else None
    prefix = "image" if row.type == "visual" else "application"
    media = _CONTENT_TYPES.get(ext, f"{prefix}/{ext}") if ext else "application/octet-stream"
    base = _base_name(row.name)
    ascii_only = re.sub(r"[^\w.\-]", "_", base.encode("ascii", "ignore").decode("ascii"))
    ascii_fallback = ascii_only.strip("._") or "file"
    encoded = quote(base, safe="")
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
    headers = {"Content-Disposition": disposition}
    if (ext or "") in _FORCE_ATTACHMENT_EXTENSIONS or media in _FORCE_ATTACHMENT_TYPES:
        headers["X-Content-Type-Options"] = "nosniff"
    return media, headers


@router.post(
    "/files/move",
    operation_id="files_move",
    responses={200: {"model": RagflowOk[bool]}},
    openapi_extra=extra_doc(FileMoveRequest),
)
async def move_files(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /files/move (§D5): przeniesienie/zmiana nazwy; cudzy plik → 102 ``no authorization``."""
    inp = parse_file_move(await json_object_body(request))
    try:
        await _svc(request).move(
            principal, inp.src_file_ids, dest_id=inp.dest_file_id, new_name=inp.new_name
        )
    except PermissionDenied as err:
        return refuse(request, principal, "files_move", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    return ok_true()


@router.post(
    "/files/link-to-datasets",
    operation_id="files_link_to_datasets",
    responses={200: {"model": RagflowOk[bool]}},
    openapi_extra=extra_doc(
        FileLinkRequest,
        query=[query_param("mode", {"type": "string"}, "Tryb wiązania: replace|add")],
    ),
)
async def link_to_datasets(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /files/link-to-datasets (§D5): wiązanie plików z datasetami; zły ``mode`` → 101."""
    inp = parse_file_link(await json_object_body(request))
    mode = (request.query_params.get("mode", "replace") or "replace").lower()
    if mode not in {"replace", "add"}:
        return argument_error(MSG_MODE_INVALID)
    try:
        await _svc(request).link_to_datasets(principal, inp.file_ids, inp.kb_ids, mode=mode)
    except PermissionDenied as err:
        return refuse(request, principal, "files_link_to_datasets", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    # Złoto files--15: ``code``, ``data``, ``message`` (upstream ``get_json_result``).
    return JSONResponse({"code": int(RetCode.SUCCESS), "data": True, "message": "success"})


@router.get(
    "/files/{file_id}/parent",
    operation_id="files_parent",
    responses={200: {"model": RagflowOk[FileParentResult]}},
)
async def get_parent(
    file_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /files/{file_id}/parent (§D5): folder-rodzic pliku."""
    try:
        row = await _svc(request).parent(principal, file_id)
    except PermissionDenied as err:
        return refuse(request, principal, "files_parent", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    return ok(file_parent_result(row))


@router.get(
    "/files/{file_id}/ancestors",
    operation_id="files_ancestors",
    responses={200: {"model": RagflowOk[FileAncestors]}},
)
async def get_ancestors(
    file_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /files/{file_id}/ancestors (§D5): ścieżka ``[plik, …, root]``."""
    try:
        rows = await _svc(request).ancestors(principal, file_id)
    except PermissionDenied as err:
        return refuse(request, principal, "files_ancestors", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    return ok(file_ancestors(rows))


@router.get(
    "/files/{file_id}",
    operation_id="files_download",
    response_class=Response,
    responses={
        200: {
            "description": "Treść pliku (Content-Disposition: attachment); brak → koperta JSON",
            "content": {
                "application/json": {"schema": {"type": "object"}},
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def download_file(
    file_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /files/{file_id} (§D5): strumień bloba pliku z nagłówkami upstream."""
    try:
        row, iterator = await _svc(request).open(principal, file_id)
    except PermissionDenied as err:
        return refuse(request, principal, "files_download", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    media, headers = _download_headers(row)
    return StreamingResponse(iterator, media_type=media, headers=headers)


@router.get(
    "/files",
    operation_id="files_list",
    responses={200: {"model": RagflowOk[FileList]}},
    openapi_extra=extra_doc(
        query=[
            query_param("parent_id", {"type": "string"}, "Identyfikator folderu (brak → root)"),
            query_param("keywords", {"type": "string"}, "Filtr po fragmencie nazwy"),
            query_param("page", {"type": "integer"}, "Numer strony (od 1)"),
            query_param("page_size", {"type": "integer"}, "Liczba elementów na stronie"),
            query_param(
                "orderby",
                {"type": "string"},
                "Sortowanie: create_time|update_time|name|size|type",
            ),
            query_param("desc", {"type": "boolean"}, "Kolejność malejąca"),
        ]
    ),
)
async def list_files(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """GET /files (§D5): stronicowany listing folderu z ``parent_folder`` i ``total``."""
    query = parse_file_list(
        dict(request.query_params), max_size=container_of(request).settings.max_page_size
    )
    try:
        page = await _svc(request).list(
            principal,
            parent_id=query.parent_id,
            keywords=query.keywords,
            orderby=query.orderby,
            desc=query.desc,
            page=query.page,
            page_size=query.page_size,
        )
    except PermissionDenied as err:
        return refuse(request, principal, "files_list", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    return ok(file_list(page))


@router.post(
    "/files",
    operation_id="files_create",
    responses={200: {"model": RagflowOk[FileCreated | list[FileCreated]]}},
    openapi_extra=extra_doc(
        FileUploadForm,
        media_type="multipart/form-data",
        also={"application/json": FolderCreateBody},
    ),
)
async def create_or_upload(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /files (§D5): ``multipart/form-data`` → upload plików, JSON → nowy folder."""
    if "multipart/form-data" in request.headers.get("content-type", ""):
        return await _upload(request, principal, profile)
    inp = parse_file_create(await json_object_body(request))
    try:
        row = await _svc(request).create_folder(principal, name=inp.name, parent_id=inp.parent_id)
    except PermissionDenied as err:
        return refuse(request, principal, "files_create", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    return ok_result(file_created(row))


async def _upload(request: Request, principal: Principal, profile: CompatDep) -> Response:
    """Wariant uploadu ``POST /files`` (upstream ``create_or_upload``) — odpowiedź to lista."""
    form = await request.form()
    parts = [part for part in form.getlist("file") if isinstance(part, UploadFile)]
    ensure_file_count(parts)
    if not parts:
        return argument_error(_MSG_NO_FILE_PART)
    if any(not part.filename for part in parts):
        return argument_error(_MSG_NO_FILE_SELECTED)
    parent_id = form.get("parent_id")
    created: list[dict[str, object]] = []
    try:
        for part in parts:
            row = await _svc(request).upload(
                principal,
                filename=part.filename or "",
                content=await part.read(),
                parent_id=parent_id if isinstance(parent_id, str) else None,
            )
            created.append(file_created(row))
    except PermissionDenied as err:
        return refuse(request, principal, "files_create", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    return ok_result(created)


@router.delete(
    "/files",
    operation_id="files_delete",
    responses={200: {"model": RagflowOk[FileDeleteResult]}},
    openapi_extra=extra_doc(FileDeleteRequest),
)
async def delete_files(request: Request, principal: PrincipalDep) -> Response:
    """DELETE /files (§D5): twarde usunięcie; błędy częściowe wracają kodem 102 (D1.8)."""
    inp = parse_file_delete(await json_object_body(request))
    outcome = await _svc(request).delete(principal, inp.ids)
    if not outcome.errors:
        return ok({"success_count": outcome.success_count})
    template = MSG_PARTIALLY_DELETED if outcome.success_count > 0 else MSG_DELETE_FAILED
    # Złoto files--21/--31: ``code``, ``data`` (``errors`` przed ``success_count``), ``message``.
    return JSONResponse(
        {
            "code": int(RetCode.DATA_ERROR),
            "data": {"errors": outcome.errors, "success_count": outcome.success_count},
            "message": template.format(count=outcome.success_count, errors=len(outcome.errors)),
        }
    )
