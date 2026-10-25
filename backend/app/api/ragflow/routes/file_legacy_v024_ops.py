"""Trasy mutujące legacy ``/api/v1/file/*`` w profilu ``ragflow_0_24`` (E4-5b §D1, §D4).

Cztery operacje SDK v0.24.0 (``api/apps/sdk/files.py``): ``mv``, ``rename``, ``rm``
i ``convert``. Każda zwraca kopertę SDK (§D2, HTTP 200) i traktuje cudzy zasób jak
nieistniejący (DEC-201). Sesję do sprawdzeń bierzemy z ``FilesService.sessionmaker``
(kontrakt lint-imports ``api-no-db``: warstwa API nie importuje ``app.db``).
"""

from typing import Final, cast

from fastapi import Request
from starlette.responses import Response

from app.api.auth.principal import container_of
from app.api.ragflow.normalize.common import json_object_body
from app.api.ragflow.present.file_legacy import sdk_error, sdk_exception, sdk_ok
from app.api.ragflow.routes.file_legacy_v024_common import first_unusable
from app.core.error_codes import RetCode
from app.core.errors import PermissionDenied, ValidationFailed
from app.domain.policy import Principal
from app.services.files import (
    MSG_DATASET_NOT_FOUND,
    MSG_FILE_NOT_FOUND,
    MSG_SOURCE_FILES_NOT_FOUND,
    FilesService,
)
from app.services.files_ops import (
    MSG_DUPLICATED_FILE_NAME,
    MSG_EXTENSION_CHANGED,
    MSG_PARENT_FOLDER_NOT_FOUND,
)

# Komunikaty dosłownie upstream v0.24 (CONTRACT §D4); inne niż stałe wewnętrzne E4-5a
# (``MSG_PARENT_FOLDER_NOT_FOUND`` pisze „folder" małą literą, a ``MSG_FILE_OR_FOLDER_NOT_FOUND``
# to szablon z id).
_MSG_PARENT_FOLDER_NOT_FOUND: Final = "Parent Folder not found!"
_MSG_FILE_OR_FOLDER_NOT_FOUND: Final = "File or Folder not found!"


def _key(body: dict[str, object], key: str) -> object:
    """Wartość klucza ciała; brak → ``KeyError(key)`` (upstream ``req[key]``)."""
    return body[key]


def _id_list(body: dict[str, object], key: str) -> list[str]:
    """Lista identyfikatorów z ciała; brak klucza → ``KeyError(key)`` (§D4)."""
    return list(cast("list[str]", _key(body, key)))


def _text(body: dict[str, object], key: str) -> str:
    """Tekst z ciała; brak klucza → ``KeyError(key)`` (§D4)."""
    return str(_key(body, key))


async def move(request: Request, principal: Principal) -> Response:
    """POST /file/mv w v0.24 — ``src_file_ids`` i ``dest_file_id`` (§D4)."""
    body = await json_object_body(request)
    try:
        src_ids = _id_list(body, "src_file_ids")
        dest_id = _text(body, "dest_file_id")
    except KeyError as err:
        return sdk_exception(err)
    svc = FilesService(container_of(request))
    # Nieistniejący/cudzy plik źródłowy → KeyError jak upstream ``files_dict[file_id]`` (DEC-201).
    bad = await first_unusable(svc, principal, src_ids)
    if bad is not None:
        return sdk_exception(KeyError(bad))
    if not dest_id:
        return sdk_error(RetCode.NOT_FOUND, _MSG_PARENT_FOLDER_NOT_FOUND)
    try:
        await svc.move(principal, src_ids, dest_id=dest_id, new_name=None)
    except (PermissionDenied, ValidationFailed) as err:
        # Cudzy/nieistniejący folder docelowy → 404 jak upstream (DEC-201); inny walidacyjny → 102.
        if isinstance(err, PermissionDenied) or str(err) == MSG_PARENT_FOLDER_NOT_FOUND:
            return sdk_error(RetCode.NOT_FOUND, _MSG_PARENT_FOLDER_NOT_FOUND)
        return sdk_error(RetCode.DATA_ERROR, str(err))
    return sdk_ok(True)


async def rename(request: Request, principal: Principal) -> Response:
    """POST /file/rename w v0.24 — ``file_id`` i ``name`` (§D4)."""
    body = await json_object_body(request)
    try:
        file_id = _text(body, "file_id")
        name = _text(body, "name")
    except KeyError as err:
        return sdk_exception(err)
    svc = FilesService(container_of(request))
    try:
        await svc.move(principal, [file_id], dest_id=None, new_name=name)
    except (PermissionDenied, ValidationFailed) as err:
        message = str(err)
        if isinstance(err, PermissionDenied) or message == MSG_SOURCE_FILES_NOT_FOUND:
            return sdk_error(RetCode.NOT_FOUND, MSG_FILE_NOT_FOUND)
        if message == MSG_EXTENSION_CHANGED:
            return sdk_error(RetCode.BAD_REQUEST, message, False)
        if message == MSG_DUPLICATED_FILE_NAME:
            return sdk_error(RetCode.CONFLICT, message, False)
        return sdk_error(RetCode.DATA_ERROR, message)
    return sdk_ok(True)


async def remove(request: Request, principal: Principal) -> Response:
    """POST /file/rm w v0.24 — ``file_ids`` (§D4)."""
    body = await json_object_body(request)
    try:
        file_ids = _id_list(body, "file_ids")
    except KeyError as err:
        return sdk_exception(err)
    svc = FilesService(container_of(request))
    # Każde id osobno: brak/cudze przerywa pętlę, poprzednie usunięcia zostają (jak upstream).
    for file_id in file_ids:
        outcome = await svc.delete(principal, [file_id])
        if outcome.errors:
            return sdk_error(RetCode.NOT_FOUND, _MSG_FILE_OR_FOLDER_NOT_FOUND)
    return sdk_ok(True)


async def convert(request: Request, principal: Principal) -> Response:
    """POST /file/convert w v0.24 — ``kb_ids`` i ``file_ids`` (§D4)."""
    body = await json_object_body(request)
    try:
        kb_ids = _id_list(body, "kb_ids")
        file_ids = _id_list(body, "file_ids")
    except KeyError as err:
        return sdk_exception(err)
    svc = FilesService(container_of(request))
    # Odchyłka (d) DEC-202: brak/cudzy plik → 102 „File not found!" (nie KeyError goldenu).
    if await first_unusable(svc, principal, file_ids) is not None:
        return sdk_error(RetCode.DATA_ERROR, MSG_FILE_NOT_FOUND)
    try:
        links = await svc.link_to_datasets(principal, file_ids, kb_ids, mode="replace")
    except PermissionDenied:
        return sdk_error(RetCode.NOT_FOUND, MSG_DATASET_NOT_FOUND)
    except ValidationFailed as err:
        message = str(err)
        if message == MSG_DATASET_NOT_FOUND:
            return sdk_error(RetCode.NOT_FOUND, message)
        return sdk_error(RetCode.DATA_ERROR, message)
    return sdk_ok(
        [
            {"document_id": link.document_id, "file_id": link.file_id, "id": link.id}
            for link in links
        ]
    )
