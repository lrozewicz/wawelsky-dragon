"""Przenoszenie/zmiana nazwy i usuwanie plików — treść T3 (CONTRACT §D1.6, §D1.8, §D3).

Port ``file_api_service.move_files``/``delete_files`` upstream v0.27.2 na model WD: ``location``
wiersza `files` to klucz bloba ``filemanager/{id}/original{.suffix}`` (nie nazwa), więc
przeniesienie i zmiana nazwy to zapis ``parent_id``/``name`` — bez operacji na storage.
Komunikaty i ich kolejność dosłownie upstream/złoto (``files--20``, ``files--23``, ``files--29``,
``files--21``, ``files--31``, ``files--34``, ``files--35``).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePath
from typing import TYPE_CHECKING, Final

from app.core.errors import PermissionDenied, ValidationFailed
from app.db.repositories import files as files_repo
from app.db.repositories.files import FileRow
from app.db.uow import transaction
from app.domain.files import FOLDER_TYPE
from app.domain.policy import Action, ResourceRef, can
from app.services.files import (
    MSG_FILE_OR_FOLDER_NOT_FOUND,
    MSG_MOVE_INTO_SUBFOLDER,
    MSG_NO_AUTHORIZATION,
    MSG_NO_AUTHORIZATION_FOR_FILE,
    MSG_SOURCE_FILES_NOT_FOUND,
    DeleteOutcome,
)
from app.storage.keys import StorageKey

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.policy.principal import Principal
    from app.services.files import FilesService

__all__ = ["delete_files", "move_files"]

# Komunikaty operacji move, których nie ma w ``services/files.py`` (§D1.8 wymienia je jako
# „dosłownie upstream"); reszta stałych MSG_* wspólna z usługą i trasami.
MSG_NAME_WITH_SLASH: Final = 'Name cannot contain "/"'
MSG_EXTENSION_CHANGED: Final = "The extension of file can't be changed"
MSG_DUPLICATED_FILE_NAME: Final = "Duplicated file name in the same folder."
# Upstream `move_files` przy braku folderu docelowego i `_move_entry_recursive` przy
# przeniesieniu wiersza samego w siebie (kopia upstream `test_file_routes.py:335`/`:340`).
MSG_PARENT_FOLDER_NOT_FOUND: Final = "Parent folder not found!"
MSG_ALREADY_IN_TARGET: Final = (
    "The folder is already in the target location. There is no need to move it."
)


def _ref(row: FileRow) -> ResourceRef:
    """ResourceRef wiersza `files` — decyzja zapada w ``can`` (K5 §7.2, §D3)."""
    return ResourceRef(kind="file", owner_id=row.tenant_id, id=row.id)


def _suffix(name: str) -> str:
    """Rozszerzenie nazwy małymi literami (jak upstream ``Path(name.lower()).suffix``)."""
    return PurePath(name.lower()).suffix


async def move_files(
    svc: FilesService,
    principal: Principal,
    src_ids: Sequence[str],
    dest_id: str | None,
    new_name: str | None,
) -> None:
    """Przenosi/zmienia nazwę plików wg semantyki ``mv`` upstream (T3, §D3).

    ``dest_id`` bez ``new_name`` → przeniesienie pod zachowaną nazwą; ``new_name`` bez
    ``dest_id`` → zmiana nazwy jednego pliku w miejscu; oba → przeniesienie i zmiana nazwy.
    Kolejność sprawdzeń i komunikaty jak upstream ``move_files``.
    """
    async with transaction(svc.sessionmaker()) as session:
        rows = await files_repo.get_many(session, list(src_ids))
        by_id = {row.id: row for row in rows}
        # Brak/ukryty któryś z src_id → 102 „Source files not found!" (złoto files--20).
        if not src_ids or any(src_id not in by_id for src_id in src_ids):
            raise ValidationFailed(MSG_SOURCE_FILES_NOT_FOUND)
        sources = [by_id[src_id] for src_id in src_ids]
        # Cudzy plik → PermissionDenied("no authorization") (złoto files--29).
        for source in sources:
            if not can(principal, Action.READ, _ref(source)):
                raise PermissionDenied(MSG_NO_AUTHORIZATION)
        dest: FileRow | None = None
        if dest_id is not None:
            dest = await svc.visible(session, dest_id)
            # Upstream `move_files`: brakujący/ukryty folder docelowy → "Parent folder not found!"
            # (CONTRACT §D1.8 wymienia ten komunikat; kopia upstream test_file_routes.py:335).
            if dest is None:
                raise ValidationFailed(MSG_PARENT_FOLDER_NOT_FOUND)
            if not can(principal, Action.READ, _ref(dest)):
                raise PermissionDenied(MSG_NO_AUTHORIZATION)
        if new_name is not None:
            await _check_new_name(session, principal, sources[0], new_name, dest)
        if dest is not None:
            await _check_dest_not_inside_sources(svc, session, sources, dest)
            _check_dest_movable_target(sources, dest)
        now = svc.container.clock.now_ms()
        if dest is not None:
            for source in sources:
                await files_repo.set_parent(session, source.id, dest.id, now)
        if new_name is not None:
            await files_repo.set_name(session, sources[0].id, new_name, now)


async def _check_new_name(
    session: AsyncSession,
    principal: Principal,
    source: FileRow,
    new_name: str,
    dest: FileRow | None,
) -> None:
    """Walidacja ``new_name``: separator, zmiana rozszerzenia, zajęta nazwa (upstream)."""
    if "/" in new_name:
        raise ValidationFailed(MSG_NAME_WITH_SLASH)
    if source.type != FOLDER_TYPE and _suffix(new_name) != _suffix(source.name):
        raise ValidationFailed(MSG_EXTENSION_CHANGED)
    target_parent = dest.id if dest is not None else source.parent_id
    if target_parent is None:  # root nie ma rodzica — nie ma gdzie sprawdzać kolizji
        return
    if await files_repo.find_child(session, principal.user_id, target_parent, new_name) is not None:
        raise ValidationFailed(MSG_DUPLICATED_FILE_NAME)


async def _check_dest_not_inside_sources(
    svc: FilesService, session: AsyncSession, sources: Sequence[FileRow], dest: FileRow
) -> None:
    """Folder nie może trafić do siebie ani do własnego potomka (złoto ``files--23``)."""
    folder_ids = {source.id for source in sources if source.type == FOLDER_TYPE}
    if not folder_ids:
        return
    current: FileRow | None = dest
    seen: set[str] = set()
    while current is not None and current.id not in seen:
        if current.id in folder_ids:
            raise ValidationFailed(MSG_MOVE_INTO_SUBFOLDER)
        seen.add(current.id)
        current = await svc.visible(session, current.parent_id) if current.parent_id else None


def _check_dest_movable_target(sources: Sequence[FileRow], dest: FileRow) -> None:
    """Cel musi być folderem i różnym od każdego ``src_id`` (poprawka z przeglądu T3).

    Kolejność jak upstream ``move_files``/``_move_entry_recursive``: najpierw wiersz
    przenoszony sam w siebie — ``_move_entry_recursive`` rzuca wtedy
    „The folder is already in the target location…" niezależnie od typu; dopiero potem
    odrzucamy cel niebędący folderem. Upstream nie ma na to osobnego komunikatu, więc
    używamy tego samego co przy braku folderu docelowego („Parent folder not found!").
    Przypadki folder→on sam / folder→potomek obsługuje ``_check_dest_not_inside_sources``.
    """
    if any(source.id == dest.id for source in sources):
        raise ValidationFailed(MSG_ALREADY_IN_TARGET)
    if dest.type != FOLDER_TYPE:
        raise ValidationFailed(MSG_PARENT_FOLDER_NOT_FOUND)


async def delete_files(
    svc: FilesService, principal: Principal, ids: Sequence[str]
) -> DeleteOutcome:
    """Usuwa pliki/foldery rekurencyjnie i zwraca ``DeleteOutcome`` (T3, §D3).

    Każde id osobno — błąd jednego nie przerywa reszty; brak/ukryty → komunikat z id,
    cudzy → komunikat z id w ``errors`` (bez wyjątku, §D1.8), inaczej usunięcie wiersza.
    """
    errors: list[str] = []
    success_count = 0
    for file_id in ids:
        async with transaction(svc.sessionmaker()) as session:
            row = await svc.visible(session, file_id)
            if row is None:
                errors.append(MSG_FILE_OR_FOLDER_NOT_FOUND.format(file_id=file_id))
                continue
            if not can(principal, Action.READ, _ref(row)):
                errors.append(MSG_NO_AUTHORIZATION_FOR_FILE.format(file_id=file_id))
                continue
            if row.type == FOLDER_TYPE:
                success_count += await _delete_folder(svc, session, row)
            else:
                success_count += await _delete_single_file(svc, session, row)
    return DeleteOutcome(success_count=success_count, errors=errors)


async def _delete_folder(svc: FilesService, session: AsyncSession, folder: FileRow) -> int:
    """Folder: potomki od liści, na końcu sam folder; każdy usunięty wiersz liczy się osobno."""
    children = await files_repo.list_all_children(session, folder.id)
    by_parent: dict[str | None, list[FileRow]] = {}
    for child in children:
        by_parent.setdefault(child.parent_id, []).append(child)
    deleted = await _delete_subtree(svc, session, folder.id, by_parent)
    return deleted + await files_repo.delete(session, folder.id)


async def _delete_subtree(
    svc: FilesService,
    session: AsyncSession,
    parent_id: str,
    by_parent: dict[str | None, list[FileRow]],
) -> int:
    """Rekurencja po potomkach folderu: podfoldery od liści, pliki przez ``_delete_single_file``."""
    deleted = 0
    for child in by_parent.get(parent_id, []):
        if child.type == FOLDER_TYPE:
            deleted += await _delete_subtree(svc, session, child.id, by_parent)
            deleted += await files_repo.delete(session, child.id)
        else:
            deleted += await _delete_single_file(svc, session, child)
    return deleted


async def _delete_single_file(svc: FilesService, session: AsyncSession, row: FileRow) -> int:
    """Plik: najpierw zlinkowane dokumenty, potem wiersz, na końcu blob (K16 §2 p. 4).

    Kolejność gwarantuje, że awaria w połowie nie zostawia dokumentu bez bloba.
    """
    links = await files_repo.list_links(session, row.id)
    if links:
        await svc.container.ingest.delete_documents([link.document_id for link in links])
    deleted = await files_repo.delete(session, row.id)
    if row.location:
        await svc.container.storage.delete(StorageKey(row.location))
    return deleted
