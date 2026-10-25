"""Alias ``/v1`` tras ragflow v0.24 (E2-2a): system, statystyki, katalog modeli, dokumenty.

Trasy upstreamu v0.24 (``api/apps/system_app.py``, ``api/apps/api_app.py``,
``api/apps/llm_app.py``, ``api/apps/document_app.py``) pod krótkim prefiksem ``/v1``,
odrębnym od ``/api/v1``; uwierzytelnienie JWT legacy — nagłówek ``Authorization``
z logowania, jak krok ``auth: jwt`` harnessu. Prefiks poza schematem OpenAPI
(``include_in_schema=False``, K11 §10d p. 17).

Te trasy istnieją wyłącznie w v0.24 i — zgodnie z K11 §10d p. 17 — wywołane w profilu 0.27
działają tak samo, więc kształty są dosłownie v0.24 niezależnie od profilu zgodności
(nie ma tu gałęzi ``CompatProfile``). Kształty systemowe ma ``present/system.py``; mapę profilu
bierze wyłącznie prezenter odmowy: koperty odmów tego aliasu to koperty v0.24 (``refusals_v024``).
"""

import mimetypes
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.datastructures import UploadFile

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.envelope import ok, ok_true
from app.api.ragflow.file_safety import ensure_file_count
from app.api.ragflow.normalize.common import parse_model
from app.api.ragflow.normalize.documents import batch_status
from app.api.ragflow.present.documents_files import uploaded_file
from app.api.ragflow.present.system import (
    legacy_config,
    legacy_created_token,
    legacy_my_llms,
    legacy_token,
    legacy_version,
)
from app.api.ragflow.refusals import refuse
from app.api.ragflow.routes.documents_files import MSG_MISSING_INPUT
from app.api.ragflow.routes.system import stats_body, status_body
from app.api.ragflow.schemas.documents_files import IngestRequest
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.services.api_keys import ApiKeyService
from app.services.documents_extra import DocumentExtraService
from app.services.documents_files import DocumentFilesService
from app.services.model_catalog import ModelCatalogService
from app.services.system_info import SystemInfoService

router = APIRouter(prefix="/v1", include_in_schema=False)

# Profil odmowy tego aliasu (K11 §10d p. 17): trasy /v1 to powierzchnia v0.24.
COMPAT_V024: CompatProfile = "ragflow_0_24"


@router.get("/system/ping", operation_id="system_ping_legacy")
async def ping() -> Response:
    """Sonda życia bez uwierzytelnienia: dosłownie „pong” (złoto system--16.json)."""
    return Response("pong", media_type="text/html")


@router.get("/system/version", operation_id="system_version_legacy")
async def version(principal: PrincipalDep) -> JSONResponse:
    """Wersja v0.24; JWT jak w upstreamie (``@login_required``, złoto system--17.json)."""
    return ok(legacy_version(COMPAT_V024))


@router.get("/system/config", operation_id="system_config_legacy")
async def config(request: Request) -> JSONResponse:
    """Flagi publiczne instancji bez uwierzytelnienia (złoto system--18.json)."""
    return ok(legacy_config(container_of(request).settings, COMPAT_V024))


@router.get("/system/status", operation_id="system_status_legacy")
async def status(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Status komponentów i tętna workerów; JWT (złoto system--20.json)."""
    return ok(status_body(await SystemInfoService(container_of(request)).status()))


@router.get("/system/token_list", operation_id="system_token_list_legacy")
async def list_tokens(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Aktywne klucze API właściciela (złoto system--21.json)."""
    keys = cast(ApiKeyService, container_of(request).api_keys)
    return ok([legacy_token(view, COMPAT_V024) for view in await keys.list_full(principal)])


@router.post("/system/new_token", operation_id="system_new_token_legacy")
async def create_token(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Nowy klucz API właściciela (złoto system--22.json; K9 tworzy ten sam wiersz)."""
    keys = cast(ApiKeyService, container_of(request).api_keys)
    return ok(legacy_created_token(await keys.create(principal), COMPAT_V024))


@router.delete("/system/token/{token:path}", operation_id="system_token_delete_legacy")
async def delete_token(token: str, request: Request, principal: PrincipalDep) -> JSONResponse:
    """Unieważnienie tokenu tylko właściciela; cudzy → odmowa 108 (C0 p. 9).

    Upstream (system_app.rm) kasuje cicho po ``tenant_id`` i zwraca sukces także dla cudzego
    tokenu; WD odmawia zamiast oddawać sukces na cudzym zasobie (CONTRACT C0 p. 9).
    """
    keys = cast(ApiKeyService, container_of(request).api_keys)
    if await keys.delete(principal, token) == 0:
        return refuse(request, principal, "v1_token_delete", compat=COMPAT_V024)
    return ok(True)


@router.get("/api/stats", operation_id="api_stats_legacy")
async def stats(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Puste serie statystyk konwersacji API (złoto system--24.json)."""
    return ok(stats_body())


@router.get("/llm/my_llms", operation_id="llm_my_llms_legacy")
async def my_llms(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Katalog modeli tenanta w kształcie legacy (złoto system--25.json)."""
    catalog = ModelCatalogService(container_of(request))
    return ok(legacy_my_llms(await catalog.models(), COMPAT_V024))


@router.post("/document/change_status", operation_id="document_change_status_legacy")
async def document_change_status(request: Request, principal: PrincipalDep) -> JSONResponse:
    """POST /v1/document/change_status — status dokumentów po id (złoto 17/18).

    Upstream (DOC:501) wymaga ``doc_ids`` i ``status``, po czym zapisuje status per dokument
    (``DocumentService.accessible`` filtruje po tenancie użytkownika). WD deleguje do usługi
    ``batch-update-status`` (C0 p. 5), a cudzy/nieistniejący dokument przerywa całość odmową.
    """
    cmd = batch_status(await json_body(request), COMPAT_V024)
    try:
        entries = await DocumentExtraService(container_of(request)).statuses_by_document(
            principal, cmd.doc_ids, cmd.status
        )
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "v1_document_change_status", err, compat=COMPAT_V024)
    return ok(entries)


@router.post("/document/run", operation_id="document_run_legacy")
async def document_run(request: Request, principal: PrincipalDep) -> JSONResponse:
    """POST /v1/document/run — start (``run='1'``) albo anulowanie (``'2'``) parsowania.

    Złoto 20/22/24: zawsze ``data: true``. Upstream (DOC:592) sprawdza ``accessible`` każdego
    id przed pracą — robi to ta sama usługa co ``POST /documents/ingest`` (C0 p. 5).
    """
    cmd = parse_model(IngestRequest, await json_body(request))
    try:
        await DocumentFilesService(container_of(request)).ingest(
            principal, cmd.doc_ids, run=cmd.run, delete=cmd.delete
        )
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "v1_document_run", err, compat=COMPAT_V024)
    return ok_true()


@router.post("/document/upload_info", operation_id="document_upload_info_legacy")
async def document_upload_info(request: Request, principal: PrincipalDep) -> JSONResponse:
    """POST /v1/document/upload_info — opis pliku bez datasetu (złoto 26).

    Upstream (DOC:927) czyta jedną część ``file`` i oddaje ``FileService.upload_info``
    z ``preview_url: None``; usługa jest ta sama co ``POST /documents/upload`` (C0 p. 5).
    """
    form = await request.form()
    files = [part for part in form.getlist("file") if isinstance(part, UploadFile)]
    ensure_file_count(files)
    if not files:
        raise ValidationFailed(MSG_MISSING_INPUT)
    part = files[0]
    if not part.filename:
        raise ValidationFailed(MSG_MISSING_INPUT)
    mime = part.content_type or mimetypes.guess_type(part.filename)[0] or "application/octet-stream"
    info = await DocumentFilesService(container_of(request)).upload(
        principal, part.filename, mime, await part.read()
    )
    return ok(uploaded_file(info))


@router.get(
    "/document/get/{document_id}", operation_id="document_get_legacy", response_class=Response
)
async def document_get(document_id: str, request: Request, principal: PrincipalDep) -> Response:
    """GET /v1/document/get/{doc_id} — surowe bajty pliku (złoto 30: ``text/plain``).

    Upstream (DOC:707) nie sprawdza właściciela (oddaje plik każdemu, kto zna id); WD odmawia
    na cudzym/nieistniejącym dokumencie (C0 p. 9). Typ odpowiedzi bierze się z rozszerzenia
    nazwy, jak tam (``CONTENT_TYPE_MAP``) — ``mimetypes`` daje ten sam ``text/plain``.
    """
    try:
        row, iterator = await DocumentFilesService(container_of(request)).open(
            principal, document_id
        )
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "v1_document_get", err, compat=COMPAT_V024)
    return StreamingResponse(
        iterator, media_type=mimetypes.guess_type(row.name)[0] or "application/octet-stream"
    )


@router.get("/document/thumbnails", operation_id="document_thumbnails_legacy")
async def document_thumbnails(request: Request, principal: PrincipalDep) -> JSONResponse:
    """GET /v1/document/thumbnails?doc_ids= — mapa doc_id → miniatura (złoto 32: same "")."""
    try:
        thumbnails = await DocumentFilesService(container_of(request)).legacy_thumbnails(
            principal, request.query_params.getlist("doc_ids")
        )
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "v1_document_thumbnails", err, compat=COMPAT_V024)
    return ok(thumbnails)
