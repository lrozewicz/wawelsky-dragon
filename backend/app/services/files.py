"""Usługa menedżera plików — rdzeń K16 (CONTRACT E4-5a §D1, §D3).
Port ``file_api_service.py`` i ``db/services/file_service.py`` upstream v0.27.2: leniwy root pod
blokadą wiersza użytkownika, foldery, upload do ``filemanager/``, listing z ``kbs_info``/
``has_child_folder``, rodzic/przodkowie i pobranie bloba. ``move``/``delete``/``link_to_datasets``
delegują do ``files_ops``/``files_link`` (importy leniwe — moduły te importują stąd
``FilesService``/``DeleteOutcome``). Stałe ``MSG_*`` (§D1.8) wspólne dla modułów T3/T4 i tras T5.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import TYPE_CHECKING, Final

from app.core.errors import PermissionDenied, ValidationFailed
from app.core.timeutil import from_ms
from app.db.repositories import files as files_repo
from app.db.repositories.files import FileRow
from app.db.uow import transaction
from app.domain.files import FOLDER_TYPE, filename_type
from app.domain.policy import Action, ResourceRef, can
from app.storage.keys import StorageKey, filemanager_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.container import Container
    from app.domain.policy.principal import Principal
    from app.services.files_link import FileLink

__all__ = [
    "MSG_CANT_FIND_FOLDER",
    "MSG_DATASET_NOT_FOUND",
    "MSG_DELETE_FAILED",
    "MSG_DOCUMENT_NOT_FOUND",
    "MSG_DUPLICATED_FOLDER_NAME",
    "MSG_FILE_EMPTY",
    "MSG_FILE_NOT_FOUND",
    "MSG_FILE_OR_FOLDER_NOT_FOUND",
    "MSG_FOLDER_NAME_INVALID",
    "MSG_FOLDER_NOT_FOUND",
    "MSG_MODE_INVALID",
    "MSG_MOVE_INTO_SUBFOLDER",
    "MSG_NO_AUTHORIZATION",
    "MSG_NO_AUTHORIZATION_FOR_FILE",
    "MSG_PARENT_NOT_EXIST",
    "MSG_PARTIALLY_DELETED",
    "MSG_SOURCE_FILES_NOT_FOUND",
    "DeleteOutcome",
    "FileListPage",
    "FileRow",
    "FileView",
    "FilesService",
]

# Komunikaty dosłownie upstream/złoto (CONTRACT §D1.8) — wspólne dla usługi, modułów i tras.
MSG_DUPLICATED_FOLDER_NAME: Final = "Duplicated folder name in the same folder."
MSG_DOCUMENT_NOT_FOUND: Final = "document not found"
MSG_FOLDER_NOT_FOUND: Final = "Folder not found!"
MSG_SOURCE_FILES_NOT_FOUND: Final = "Source files not found!"
MSG_MOVE_INTO_SUBFOLDER: Final = "Cannot move a folder into its own subfolder."
MSG_FILE_OR_FOLDER_NOT_FOUND: Final = "File or Folder not found: {file_id}"
MSG_NO_AUTHORIZATION_FOR_FILE: Final = "No authorization for file {file_id}"
MSG_FILE_NOT_FOUND: Final = "File not found!"
MSG_DATASET_NOT_FOUND: Final = "Can't find this dataset!"
MSG_NO_AUTHORIZATION: Final = "no authorization"
MSG_MODE_INVALID: Final = "mode must be 'add' or 'replace'"
MSG_PARTIALLY_DELETED: Final = "Partially deleted {count} files with {errors} errors"
MSG_DELETE_FAILED: Final = "Deleted files failed with {errors} errors"
# Komunikaty upstream `create_folder`/`upload_file`/pobrania (nie ma ich w §D1.8, ale port wierny).
MSG_FOLDER_NAME_INVALID: Final = 'Folder name cannot contain "/"'
MSG_PARENT_NOT_EXIST: Final = "Parent Folder Doesn't Exist!"
MSG_CANT_FIND_FOLDER: Final = "Can't find this folder!"
MSG_FILE_EMPTY: Final = "This file is empty."

# Dopisek licznika jak upstream `duplicate_name`: „a(2).txt” → baza „a”, licznik 2.
_COUNTER_RE: Final = re.compile(r"^(.*?)\((\d+)\)$")
_MAX_NAME_ATTEMPTS: Final = 1000


type FileRows = list[FileRow]
type FileLinks = list[FileLink]  # ``list`` przesłania wbudowane ``list`` w klasie (mypy, PEP 695)


@dataclass(frozen=True)
class FileView:
    """Wiersz listingu: `kbs_info` i `has_child_folder` (``None`` dla plików, §D3)."""

    row: FileRow
    kbs_info: list[dict[str, str]]
    has_child_folder: bool | None


@dataclass(frozen=True)
class FileListPage:
    """Strona listingu: folder-kontekst (``parent_folder``), widoki dzieci i liczba (§D3)."""

    parent: FileRow
    files: list[FileView]
    total: int


@dataclass(frozen=True)
class DeleteOutcome:
    """Wynik ``DELETE /files``: ile usunięto i komunikaty błędów (§D1.8)."""

    success_count: int
    errors: list[str]


def _file_ref(row: FileRow) -> ResourceRef:
    """ResourceRef wiersza `files`; decyzja zapada w ``can`` (K5 §7.2, §D3)."""
    return ResourceRef(kind="file", owner_id=row.tenant_id, id=row.id)


def _split_counter(stem: str) -> tuple[str, int]:
    """Rozbija rdzeń nazwy na bazę i licznik (upstream ``_split_name_counter``)."""
    match = _COUNTER_RE.search(stem)
    if match is None:
        return stem, 0
    return match.group(1).rstrip(), int(match.group(2))


async def _unique_name(session: AsyncSession, tenant_id: str, parent_id: str, filename: str) -> str:
    """Pierwsza wolna nazwa w folderze — port upstream ``duplicate_name`` (suffix zostaje).

    ``a.txt`` zajęte → ``a(1).txt`` (licznik rośnie w kolejnych iteracjach); po 1000 prób
    ``RuntimeError`` (jak upstream).
    """
    current = filename
    for _ in range(_MAX_NAME_ATTEMPTS):
        if await files_repo.find_child(session, tenant_id, parent_id, current) is None:
            return current
        path = PurePath(current)
        base, counter = _split_counter(path.stem)
        current = f"{base}({counter + 1}){path.suffix}"
    raise RuntimeError(
        f"Failed to generate unique name within {_MAX_NAME_ATTEMPTS} attempts. Original: {filename}"
    )


class FilesService:
    """Rdzeń menedżera plików (§D3); transakcje przez ``app.db.uow.transaction``."""

    def __init__(self, container: Container) -> None:
        """Zapamiętuje kontener; bez I/O — właściwość może powstać przed ``start()``."""
        self._container = container

    @property
    def container(self) -> Container:
        """Kontener dla modułów T3/T4 (``svc.container.ingest…``, brief T2 §7)."""
        return self._container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji kontenera; bez startu → RuntimeError (wzór ``services/searches.py``)."""
        if self._container.sessionmaker is None:
            raise RuntimeError("container not started")
        return self._container.sessionmaker

    # Brief T2 §7 i kontrakt §D3: dwa aliasy tej samej implementacji (T3/T4 działają niezależnie).
    sessionmaker = _sessionmaker

    async def visible(self, session: AsyncSession, file_id: str) -> FileRow | None:
        """Widoczny wiersz `files` po id (bez ``knowledgebase``); ``None`` gdy brak (§D2)."""
        return await files_repo.get(session, file_id)

    def owned(self, principal: Principal, row: FileRow) -> None:
        """Własność wiersza pliku; cudzy → ``PermissionDenied("no authorization")`` (§D3)."""
        if not can(principal, Action.READ, _file_ref(row)):
            raise PermissionDenied(MSG_NO_AUTHORIZATION)

    _owned = owned

    async def root(self, principal: Principal) -> FileRow:
        """Leniwy root użytkownika — jeden wiersz, tworzony pod blokadą wiersza users (§D1.2)."""
        async with transaction(self._sessionmaker()) as session:
            return await self._root_in(session, principal)

    async def create_folder(
        self, principal: Principal, *, name: str, parent_id: str | None
    ) -> FileRow:
        """Nowy folder w ``parent_id`` (``None`` → root); duplikat nazwy → 102 (§D3)."""
        if "/" in name:
            raise ValidationFailed(MSG_FOLDER_NAME_INVALID)
        async with transaction(self._sessionmaker()) as session:
            parent = await self._load_parent(session, principal, parent_id, MSG_PARENT_NOT_EXIST)
            if await files_repo.find_child(session, principal.user_id, parent.id, name) is not None:
                raise ValidationFailed(MSG_DUPLICATED_FOLDER_NAME)
            row = self._new_row(
                principal, parent_id=parent.id, name=name, type_=FOLDER_TYPE, size=0, location=None
            )
            await files_repo.insert(session, row)
        return row

    async def upload(
        self, principal: Principal, *, filename: str, content: bytes, parent_id: str | None
    ) -> FileRow:
        """Zapisuje blob ``filemanager/{id}/original{.suffix}`` i wiersz `files` (§D1.3, §D1.4).

        ``size`` = ``len(content)`` (bajty, złoto ``files--04``), typ z ``filename_type``;
        kolizja nazwy w folderze → dopisek licznika jak upstream ``duplicate_name``.
        """
        suffix = PurePath(filename).suffix.lower().lstrip(".")
        async with transaction(self._sessionmaker()) as session:
            parent = await self._load_parent(session, principal, parent_id, MSG_CANT_FIND_FOLDER)
            name = await _unique_name(session, principal.user_id, parent.id, filename)
            row = self._new_row(
                principal,
                parent_id=parent.id,
                name=name,
                type_=filename_type(filename),
                size=len(content),
                location=None,
            )
            location = filemanager_key(row.id, suffix)
            row = replace(row, location=location)
            await self._container.storage.put(
                location, content, max_bytes=self._container.settings.max_upload_mb * 1024 * 1024
            )
            await files_repo.insert(session, row)
        return row

    async def list(  # noqa: PLR0913 — sygnatura z kontraktu §D3
        self,
        principal: Principal,
        *,
        parent_id: str | None,
        keywords: str | None,
        orderby: str,
        desc: bool,
        page: int,
        page_size: int,
    ) -> FileListPage:
        """Strona widocznych dzieci folderu z ``kbs_info`` i ``has_child_folder`` (§D3)."""
        async with transaction(self._sessionmaker()) as session:
            parent = await self._load_parent(session, principal, parent_id, MSG_FOLDER_NOT_FOUND)
            # ``parent_folder`` = rodzic listowanego folderu (upstream ``list_files``; files--07).
            context = await files_repo.parent_of(session, parent)
            rows, total = await files_repo.list_children(
                session,
                parent.id,
                principal.user_id,
                keywords=keywords,
                orderby=orderby,
                desc=desc,
                page=page,
                page_size=page_size,
            )
            info = await files_repo.kbs_info(
                session, [row.id for row in rows if row.type != FOLDER_TYPE]
            )
            with_child = await files_repo.folders_with_child_folder(
                session, [row.id for row in rows if row.type == FOLDER_TYPE]
            )
        files = [
            FileView(
                row=row,
                kbs_info=[] if row.type == FOLDER_TYPE else info.get(row.id, []),
                has_child_folder=(row.id in with_child) if row.type == FOLDER_TYPE else None,
            )
            for row in rows
        ]
        return FileListPage(parent=context, files=files, total=total)

    async def open(
        self, principal: Principal, file_id: str
    ) -> tuple[FileRow, AsyncIterator[bytes]]:
        """(wiersz, strumień bloba) dla ``GET /files/{id}`` (§D3); folder/brak bloba → 102."""
        async with transaction(self._sessionmaker()) as session:
            row = await self.visible(session, file_id)
            if row is None:
                raise ValidationFailed(MSG_DOCUMENT_NOT_FOUND)
            self.owned(principal, row)
        if row.type == FOLDER_TYPE or not row.location:
            raise ValidationFailed(MSG_FILE_EMPTY)
        key = StorageKey(row.location)
        if not await self._container.storage.exists(key):
            raise ValidationFailed(MSG_FILE_EMPTY)
        return row, self._container.storage.open(key)

    async def parent(self, principal: Principal, file_id: str) -> FileRow:
        """Rodzic wiersza; dla roota — sam root (``parent_id`` roota = jego id, jak upstream)."""
        async with transaction(self._sessionmaker()) as session:
            row = await self.visible(session, file_id)
            if row is None:
                raise ValidationFailed(MSG_FOLDER_NOT_FOUND)
            self.owned(principal, row)
            if row.parent_id is None:
                return row
            parent_row = await self.visible(session, row.parent_id)
        if parent_row is None:
            raise ValidationFailed(MSG_FOLDER_NOT_FOUND)
        return parent_row

    async def ancestors(self, principal: Principal, file_id: str) -> FileRows:
        """Ścieżka ``[plik, rodzic, …, root]`` — zawiera sam plik (złoto ``files--13``, §D3)."""
        async with transaction(self._sessionmaker()) as session:
            row = await self.visible(session, file_id)
            if row is None:
                raise ValidationFailed(MSG_FOLDER_NOT_FOUND)
            self.owned(principal, row)
            chain = [row]
            current = row
            while current.parent_id is not None and current.parent_id != current.id:
                ancestor = await self.visible(session, current.parent_id)
                if ancestor is None:
                    raise ValidationFailed(MSG_FOLDER_NOT_FOUND)
                chain.append(ancestor)
                current = ancestor
        return chain

    async def move(
        self,
        principal: Principal,
        src_ids: Sequence[str],
        *,
        dest_id: str | None,
        new_name: str | None,
    ) -> None:
        """Deleguje do ``files_ops.move_files`` (T3, §D3)."""
        from app.services.files_ops import move_files  # noqa: PLC0415 — cykl modułów (§D3)

        return await move_files(self, principal, src_ids, dest_id, new_name)

    async def delete(self, principal: Principal, ids: Sequence[str]) -> DeleteOutcome:
        """Deleguje do ``files_ops.delete_files`` (T3, §D3)."""
        from app.services.files_ops import delete_files  # noqa: PLC0415 — cykl modułów (§D3)

        return await delete_files(self, principal, ids)

    async def link_to_datasets(
        self,
        principal: Principal,
        file_ids: Sequence[str],
        kb_ids: Sequence[str],
        *,
        mode: str = "replace",
    ) -> FileLinks:
        """Deleguje do ``files_link.link_files`` (T4, §D3); zwraca wiązania (§D6)."""
        from app.services.files_link import link_files  # noqa: PLC0415 — cykl modułów (§D3)

        return await link_files(self, principal, file_ids, kb_ids, mode)

    async def _root_in(self, session: AsyncSession, principal: Principal) -> FileRow:
        """Root principala w sesji: blokada users → odczyt → ewentualny INSERT (§D1.2)."""
        await files_repo.lock_user(session, principal.user_id)
        existing = await files_repo.get_root(session, principal.user_id)
        if existing is not None:
            return existing
        row = self._new_row(
            principal, parent_id=None, name="/", type_=FOLDER_TYPE, size=0, location=None
        )
        await files_repo.insert(session, row)
        return row

    async def _load_parent(
        self,
        session: AsyncSession,
        principal: Principal,
        parent_id: str | None,
        missing: str,
    ) -> FileRow:
        """Folder docelowy: root gdy brak id; brakujący → 102, cudzy → odmowa (§D3)."""
        if parent_id is None:
            return await self._root_in(session, principal)
        parent = await self.visible(session, parent_id)
        if parent is None:
            raise ValidationFailed(missing)
        self.owned(principal, parent)
        return parent

    def _new_row(  # noqa: PLR0913 — konstruktor wiersza `files` (§D2)
        self,
        principal: Principal,
        *,
        parent_id: str | None,
        name: str,
        type_: str,
        size: int,
        location: str | None,
    ) -> FileRow:
        """Nowy wiersz `files` z id i znacznikami czasu kontenera (§D2)."""
        now = self._container.clock.now_ms()
        return FileRow(
            id=self._container.id_gen.new_id(),
            tenant_id=principal.user_id,
            created_by=principal.user_id,
            parent_id=parent_id,
            name=name,
            type=type_,
            size=size,
            location=location,
            source_type="local",
            create_time=now,
            create_date=from_ms(now),
            update_time=now,
            update_date=from_ms(now),
        )
