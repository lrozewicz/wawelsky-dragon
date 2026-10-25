"""Trasy legacy ``/api/v1/file/*`` w profilu ``ragflow_0_24`` (CONTRACT E4-5b §D4).

Siedem tras odczytu/tworzenia SDK v0.24.0 (``api/apps/sdk/files.py``): ``create``, ``upload``,
``list``, ``root_folder``, ``get/{file_id}``, ``parent_folder``, ``all_parent_folder``.
Koperta ``sdk_*`` (HTTP zawsze 200, klucze ``code``/``data``/``message``) i prezentery
``present/files.py`` (E4-5a). Zasada DEC-201: cudzy zasób (``PermissionDenied``) dostaje tę
samą odpowiedź co nieistniejący („nie znaleziono"). Sygnatury zgodne ze stubami T1; usługi
bez zmian. Sesja wyłącznie przez ``FilesService`` (kontrakt ``api-no-db``: ``app.api`` nie
importuje ``app.db``).
"""

import re
from typing import Final

from fastapi import Request
from starlette.datastructures import UploadFile
from starlette.responses import Response, StreamingResponse

from app.api.auth.principal import container_of
from app.api.ragflow.file_safety import ensure_file_count
from app.api.ragflow.normalize.common import json_object_body
from app.api.ragflow.present.file_legacy import sdk_error, sdk_exception, sdk_ok
from app.api.ragflow.present.files import (
    file_ancestors,
    file_created,
    file_list,
    file_parent,
    file_parent_result,
)
from app.core.errors import PermissionDenied, ValidationFailed
from app.domain.policy import Principal
from app.services.files import (
    MSG_CANT_FIND_FOLDER,
    MSG_DOCUMENT_NOT_FOUND,
    MSG_DUPLICATED_FOLDER_NAME,
    MSG_FOLDER_NOT_FOUND,
    MSG_PARENT_NOT_EXIST,
    FileListPage,
    FilesService,
)

# Komunikaty multipart upstream ``sdk/files.py`` (``RetCode.BAD_REQUEST``).
_MSG_NO_FILE_PART: Final = "No file part!"
_MSG_NO_FILE_SELECTED: Final = "No selected file!"
# Komunikat pobrania w kopercie v0.24 (złoto ``--20``) — wersja wielką literą, nie usługowa.
_MSG_DOCUMENT_NOT_FOUND: Final = "Document not found!"
# Artefakt upstream dla folderu/braku bloba w ``get`` (złoto ``--32``) — treść AssertionError.
_MSG_SPECIFY_DOC_ID: Final = "please specify doc_id"
_DEFAULT_MEDIA: Final = "application/octet-stream"
_DEFAULT_PAGE: Final = 1
_DEFAULT_PAGE_SIZE: Final = 15
_DEFAULT_ORDERBY: Final = "create_time"


def _svc(request: Request) -> FilesService:
    """Usługa menedżera plików per żądanie (wzór ``routes/files.py``)."""
    return FilesService(container_of(request))


def _parent_id(raw: object) -> str | None:
    """``parent_id`` z ciała/formularza: niepusty łańcuch albo ``None`` (upstream ``or None``)."""
    return raw if isinstance(raw, str) and raw else None


def _media_type(name: str, type_: str) -> str:
    """Typ MIME pobrania wg D4: ``image/<ext>`` dla ``visual``, inaczej ``application/<ext>``.

    Rozszerzenie bierzemy bez zmiany wielkości liter (upstream ``sdk/files.py``); bez
    rozszerzenia zostaje ``application/octet-stream``.
    """
    match = re.search(r"\.([^.]+)$", name)
    if match is None:
        return _DEFAULT_MEDIA
    prefix = "image" if type_ == "visual" else "application"
    return f"{prefix}/{match.group(1)}"


async def create(request: Request, principal: Principal) -> Response:
    """POST /file/create w v0.24 — ``name`` (KeyError), ``parent_id`` opcjonalny (§D4).

    Zawsze powstaje folder (upstream dla ``type``≠folder tworzy ``virtual`` — ograniczenie
    lokalnej usługi; złoto ``--02`` pokrywa folder). Duplikat nazwy → 409 (złoto ``--27``),
    zły/cudzy rodzic → 400.
    """
    body = await json_object_body(request)
    try:
        name = str(body["name"])
    except KeyError as err:
        return sdk_exception(err)
    try:
        row = await _svc(request).create_folder(
            principal, name=name, parent_id=_parent_id(body.get("parent_id"))
        )
    except PermissionDenied:
        return sdk_error(400, MSG_PARENT_NOT_EXIST, False)
    except ValidationFailed as err:
        message = str(err)
        if message == MSG_PARENT_NOT_EXIST:
            return sdk_error(400, MSG_PARENT_NOT_EXIST, False)
        if message == MSG_DUPLICATED_FOLDER_NAME:
            return sdk_error(409, MSG_DUPLICATED_FOLDER_NAME, False)
        return sdk_error(102, message)
    return sdk_ok(file_created(row))


async def upload(request: Request, principal: Principal) -> Response:
    """POST /file/upload w v0.24 — multipart ``file`` + pole ``parent_id`` (§D4).

    Brak części ``file`` i pusta nazwa → 400; brak/cudzy folder docelowy → 404; inny błąd
    usługi (np. przekroczony limit rozmiaru) → 102 z komunikatem; sukces to lista
    ``file_created`` (złoto ``--04``).
    """
    form = await request.form()
    parts = [part for part in form.getlist("file") if isinstance(part, UploadFile)]
    ensure_file_count(parts)
    if not parts:
        return sdk_error(400, _MSG_NO_FILE_PART, False)
    if any(not part.filename for part in parts):
        return sdk_error(400, _MSG_NO_FILE_SELECTED, False)
    parent_id = _parent_id(form.get("parent_id"))
    created: list[dict[str, object]] = []
    try:
        for part in parts:
            row = await _svc(request).upload(
                principal,
                filename=part.filename or "",
                content=await part.read(),
                parent_id=parent_id,
            )
            created.append(file_created(row))
    except PermissionDenied:
        return sdk_error(404, MSG_CANT_FIND_FOLDER, False)
    except ValidationFailed as err:
        message = str(err)
        if message != MSG_CANT_FIND_FOLDER:
            return sdk_error(102, message)
        return sdk_error(404, MSG_CANT_FIND_FOLDER, False)
    return sdk_ok(created)


async def list_files(request: Request, principal: Principal) -> Response:
    """GET /file/list w v0.24 — listing z ``parent_id``/``keywords``/stroną i sortowaniem (§D4).

    ``page``/``page_size`` z ``int()`` w ``try/except ValueError`` → ``sdk_exception``; wartości
    < 1 podnosimy do 1. ``desc``: brak → ``True``, obecny → ``bool(łańcucha)`` (upstream
    ``request.args.get("desc", True)``; złoto ``--06``). Brak/cudzy folder → 404.

    ``keywords`` w v0.24 filtruje **tylko bezpośrednie dzieci** listowanego folderu (upstream
    ``get_by_pf_id`` z ``parent_id``), inaczej niż profil 0.27 (całe poddrzewo, złoto ``--07``):
    usługa ``FilesService.list`` szuka w poddrzewie, więc zawężamy wynik w trasie po ``parent_id``
    i stronicujemy tutaj (złoto ``--07``: podfolder pasujący do słowa kluczowego nie występuje).
    """
    query = request.query_params
    try:
        page = int(query.get("page", _DEFAULT_PAGE))
    except ValueError as err:
        return sdk_exception(err)
    try:
        page_size = int(query.get("page_size", _DEFAULT_PAGE_SIZE))
    except ValueError as err:
        return sdk_exception(err)
    page = max(page, 1)
    page_size = max(page_size, 1)
    parent_id = query.get("parent_id") or None
    keywords = query.get("keywords") or None
    svc = _svc(request)
    try:
        if keywords is None:
            page_data = await svc.list(
                principal,
                parent_id=parent_id,
                keywords=None,
                orderby=query.get("orderby", _DEFAULT_ORDERBY),
                desc=bool(query.get("desc", True)),
                page=page,
                page_size=page_size,
            )
        else:
            # Bez LIMIT: potrzebujemy całego zbioru trafień, by zawęzić do bezpośrednich dzieci.
            full = await svc.list(
                principal,
                parent_id=parent_id,
                keywords=keywords,
                orderby=query.get("orderby", _DEFAULT_ORDERBY),
                desc=bool(query.get("desc", True)),
                page=0,
                page_size=0,
            )
            listed_id = parent_id if parent_id is not None else full.parent.id
            matched = [view for view in full.files if view.row.parent_id == listed_id]
            start = (page - 1) * page_size
            page_data = FileListPage(
                parent=full.parent,
                files=matched[start : start + page_size],
                total=len(matched),
            )
    except (PermissionDenied, ValidationFailed):
        return sdk_error(404, MSG_FOLDER_NOT_FOUND)
    return sdk_ok(file_list(page_data))


async def root_folder(request: Request, principal: Principal) -> Response:
    """GET /file/root_folder w v0.24 — root w kluczu ``root_folder`` (złoto ``--09``)."""
    row = await _svc(request).root(principal)
    return sdk_ok({"root_folder": file_parent(row)})


async def get_file(file_id: str, request: Request, principal: Principal) -> Response:
    """GET /file/get/{file_id} w v0.24 — strumień bloba (§D4; złoto ``--10``).

    Brak/cudzy → 404 „Document not found!" (DEC-201); folder lub brak bloba własnego →
    100 ``AssertionError('please specify doc_id')`` (artefakt upstream, złoto ``--32``).
    Nagłówek odpowiedzi tylko ``Content-Type`` (bez ``Content-Disposition``).
    """
    try:
        row, iterator = await _svc(request).open(principal, file_id)
    except PermissionDenied:
        return sdk_error(404, _MSG_DOCUMENT_NOT_FOUND)
    except ValidationFailed as err:
        if str(err) == MSG_DOCUMENT_NOT_FOUND:
            return sdk_error(404, _MSG_DOCUMENT_NOT_FOUND)
        return sdk_exception(AssertionError(_MSG_SPECIFY_DOC_ID))
    return StreamingResponse(iterator, media_type=_media_type(row.name, row.type))


async def parent_folder(request: Request, principal: Principal) -> Response:
    """GET /file/parent_folder w v0.24 — ``file_id`` z query (§D4).

    Brak ``file_id`` bez wywołania usługi → 404; brak/cudzy → 404 „Folder not found!";
    sukces to kształt v0.27 ``{"parent_folder": …}`` (odchyłka (b), DEC-202).
    """
    file_id = request.query_params.get("file_id")
    if not file_id:
        return sdk_error(404, MSG_FOLDER_NOT_FOUND)
    try:
        row = await _svc(request).parent(principal, file_id)
    except (PermissionDenied, ValidationFailed):
        return sdk_error(404, MSG_FOLDER_NOT_FOUND)
    return sdk_ok(file_parent_result(row))


async def all_parent_folder(request: Request, principal: Principal) -> Response:
    """GET /file/all_parent_folder w v0.24 — ``file_id`` z query (§D4; złoto ``--14/--22``).

    Brak ``file_id`` bez wywołania usługi → 404; brak/cudzy → 404 „Folder not found!";
    sukces to ``{"parent_folders": [plik, …, root]}``.
    """
    file_id = request.query_params.get("file_id")
    if not file_id:
        return sdk_error(404, MSG_FOLDER_NOT_FOUND)
    try:
        rows = await _svc(request).ancestors(principal, file_id)
    except (PermissionDenied, ValidationFailed):
        return sdk_error(404, MSG_FOLDER_NOT_FOUND)
    return sdk_ok(file_ancestors(rows))
