"""Trasy legacy ``/api/v1/file/*`` (CONTRACT E4-5b §D0, §D3).

Jedna ścieżka = jedna trasa FastAPI, która po ``profile: CompatDep`` rozgałęzia:
``ragflow_0_27`` → funkcje tras ``routes/files.py`` (E4-5a) wołane wprost; ``ragflow_0_24`` →
stuby ``routes/file_legacy_v024*.py`` (treść: T2/T3). Router ``include_in_schema=False``
(poza schematem OpenAPI) i rejestrowany w ``routes/__init__.py`` zaraz po ``files``. Kolejność
tras jest wymuszona jak w ``files.py``: statyczne ścieżki przed ``/file/get/{file_id}``.
"""

from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.auth.principal import PrincipalDep, container_of
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import data_error
from app.api.ragflow.normalize.common import json_object_body
from app.api.ragflow.refusals import refuse
from app.api.ragflow.routes import documents_files as documents_files_routes
from app.api.ragflow.routes import file_legacy_v024 as v024
from app.api.ragflow.routes import file_legacy_v024_ops as v024_ops
from app.api.ragflow.routes import files as files_routes
from app.core.errors import PermissionDenied, ValidationFailed
from app.services.files import FilesService

router = APIRouter(prefix="/api/v1", tags=["file_legacy"], include_in_schema=False)

# Upstream ``backward_compat.py:344`` (``deprecated_file_parent_folder``/``all_parent_folder``).
_MSG_FILE_ID_REQUIRED: Final = "`file_id` query parameter is required"


def _svc(request: Request) -> FilesService:
    """Usługa menedżera plików per żądanie (wzór ``routes/files.py``)."""
    return FilesService(container_of(request))


@router.post("/file/create", operation_id="file_legacy_create")
async def file_create(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /file/create (§D3): JSON → nowy folder; duplikat nazwy → 102 (złoto ``--02/--27``)."""
    if profile == "ragflow_0_24":
        return await v024.create(request, principal)
    return await files_routes.create_or_upload(request, principal, profile)


@router.post("/file/upload", operation_id="file_legacy_upload")
async def file_upload(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /file/upload (§D3): ``multipart/form-data`` → lista plików (złoto ``--04``)."""
    if profile == "ragflow_0_24":
        return await v024.upload(request, principal)
    return await files_routes.create_or_upload(request, principal, profile)


@router.get("/file/list", operation_id="file_legacy_list")
async def file_list(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """GET /file/list (§D3): listing folderu — te same query co ``GET /files`` (złoto ``--05…``)."""
    if profile == "ragflow_0_24":
        return await v024.list_files(request, principal)
    return await files_routes.list_files(request, principal, profile)


@router.get("/file/root_folder", operation_id="file_legacy_root_folder")
async def file_root_folder(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /file/root_folder (§D3): w 0.27 forwarding do listingu roota (złoto ``--09``)."""
    if profile == "ragflow_0_24":
        return await v024.root_folder(request, principal)
    return await files_routes.list_files(request, principal, profile)


@router.post("/file/mv", operation_id="file_legacy_mv")
async def file_legacy_mv(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /file/mv (§D3): ``{src_file_ids, dest_file_id}`` → move (złoto ``--11``)."""
    if profile == "ragflow_0_24":
        return await v024_ops.move(request, principal)
    return await files_routes.move_files(request, principal, profile)


@router.post("/file/rename", operation_id="file_legacy_rename")
async def file_rename(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /file/rename (§D3): ``{file_id, name}`` → ``move`` w miejscu (złoto ``--15/--34``)."""
    if profile == "ragflow_0_24":
        return await v024_ops.rename(request, principal)
    body = await json_object_body(request)
    raw_id = body.get("file_id")
    raw_name = body.get("name")
    # Upstream ``backward_compat.py:487``: ``[req.get("file_id")]``; brak id kończy w usłudze
    # komunikatem „Source files not found!" (bo żaden wiersz nie pasuje).
    file_id = raw_id if isinstance(raw_id, str) else ""
    new_name = raw_name if isinstance(raw_name, str) else None
    try:
        await _svc(request).move(principal, [file_id], dest_id=None, new_name=new_name)
    except PermissionDenied as err:
        return refuse(request, principal, "files_move", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    # Złoto file_legacy--15: ``code``, ``data``, ``message`` (upstream ``get_json_result``).
    return JSONResponse({"code": 0, "data": True, "message": "success"})


@router.post("/file/rm", operation_id="file_legacy_rm")
async def file_remove(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /file/rm (§D3): ``{ids}`` → ``delete``; błędy per id w ``errors`` (złoto ``--25…``)."""
    if profile == "ragflow_0_24":
        return await v024_ops.remove(request, principal)
    return await files_routes.delete_files(request, principal)


@router.post("/file/convert", operation_id="file_legacy_convert")
async def file_convert(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /file/convert (§D3): ``{file_ids, kb_ids}`` → linkowanie (złoto ``--17/--26``)."""
    if profile == "ragflow_0_24":
        return await v024_ops.convert(request, principal)
    return await files_routes.link_to_datasets(request, principal, profile)


@router.get("/file/get/{file_id}", operation_id="file_legacy_get")
async def file_get(
    file_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /file/get/{file_id} (§D3): strumień bloba; brak/cudzy → 102 (``--10/20/32``)."""
    if profile == "ragflow_0_24":
        return await v024.get_file(file_id, request, principal)
    return await files_routes.download_file(file_id, request, principal, profile)


@router.get("/file/parent_folder", operation_id="file_legacy_parent_folder")
async def file_parent_folder(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /file/parent_folder (§D3): ``?file_id=``; brak parametru → 102 (``--12/21/33``)."""
    if profile == "ragflow_0_24":
        return await v024.parent_folder(request, principal)
    file_id = request.query_params.get("file_id")
    if not file_id:
        return data_error(_MSG_FILE_ID_REQUIRED)
    return await files_routes.get_parent(file_id, request, principal, profile)


@router.get("/file/all_parent_folder", operation_id="file_legacy_all_parent_folder")
async def file_all_parent_folder(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /file/all_parent_folder (§D3): ``?file_id=``; brak → 102 (``--14/22``)."""
    if profile == "ragflow_0_24":
        return await v024.all_parent_folder(request, principal)
    file_id = request.query_params.get("file_id")
    if not file_id:
        return data_error(_MSG_FILE_ID_REQUIRED)
    return await files_routes.get_ancestors(file_id, request, principal, profile)


@router.post("/file/upload_info", operation_id="file_legacy_upload_info")
async def file_upload_info(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /file/upload_info (§D3): opis pliku bez datasetu (złoto ``--19``; tylko v0.27)."""
    if profile == "ragflow_0_24":
        # Trasy 0.24 nie znają ``upload_info``; brak klucza w ``PROFILES_V024`` → 108 (K11 §10d).
        return refuse(request, principal, "file_upload_info", compat=profile)
    return await documents_files_routes.upload_file_info(request, principal)
