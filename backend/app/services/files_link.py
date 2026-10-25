"""Linkowanie plików do datasetów — treść T4 (CONTRACT §D1.7, §D3, §D4).

Port ``_convert_files``/``convert`` z upstream ``file2document_api.py`` v0.27.2: walidacja
wszystkich plików i datasetów PRZED jakąkolwiek pracą, rozwinięcie folderów do plików-liści,
tryb ``replace`` usuwa linki do datasetów spoza ``kb_ids``, tryb ``add`` tylko dokłada.
W przeciwieństwie do upstream (praca w tle) linkowanie jest synchroniczne (§D1.7).
``FilesService`` importujemy pod ``TYPE_CHECKING`` — moduł importuje nas leniwie.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import documents_query
from app.db.repositories import files as files_repo
from app.db.repositories.files import FileRow
from app.db.uow import transaction
from app.domain.files import FOLDER_TYPE
from app.domain.policy import Action
from app.services.datasets import DatasetService, unique_name
from app.services.files import MSG_DATASET_NOT_FOUND, MSG_FILE_NOT_FOUND, MSG_NO_AUTHORIZATION

if TYPE_CHECKING:
    from app.domain.policy.principal import Principal
    from app.services.files import FilesService

__all__ = ["FileLink", "link_files"]


@dataclass(frozen=True)
class FileLink:
    """Wiązanie plik↔dokument datasetu zwracane przez linkowanie (§D6).

    ``id`` to wiersz `file2document`, ``file_id`` plik-liść, a ``document_id`` dokument
    datasetu. Kolejność zwracanych wiązań: pliki-liście, a w obrębie pliku ``kb_ids``.
    """

    id: str
    file_id: str
    document_id: str


async def link_files(
    svc: FilesService,
    principal: Principal,
    file_ids: Sequence[str],
    kb_ids: Sequence[str],
    mode: str,
) -> list[FileLink]:
    """Tworzy dokumenty datasetów na kluczach blobów plików (tryby ``replace``/``add``; T4).

    Kolejność sprawdzeń dosłownie upstream ``convert``: pliki istnieją, datasety istnieją,
    foldery rozwinięte, własność plików, dostęp do datasetów. Wykonanie po jednym pliku-liściu.
    Zwraca wiązania (świeżo utworzone i już istniejące) potrzebne odpowiedzi ``/file/convert`` 0.24.
    """
    leaves = await _expand_files(svc, principal, file_ids, kb_ids)
    await _require_datasets(svc, principal, kb_ids)
    targets = list(dict.fromkeys(kb_ids))
    links: list[FileLink] = []
    for leaf in leaves:
        links.extend(await _link_file(svc, principal, leaf, targets, mode))
    return links


async def _expand_files(
    svc: FilesService,
    principal: Principal,
    file_ids: Sequence[str],
    kb_ids: Sequence[str],
) -> list[FileRow]:
    """Waliduje pliki i datasety oraz rozwija foldery do plików-liści.

    Brak/ukryty plik → ``ValidationFailed("File not found!")`` (upstream przed rozwijaniem),
    nieistniejący dataset → ``ValidationFailed("Can't find this dataset!")``, cudzy plik →
    ``PermissionDenied("no authorization")``. Kolejność liści deterministyczna (kolejność
    ``file_ids``, a w folderze ``list_all_children``: czas, id).
    """
    async with transaction(svc.sessionmaker()) as session:
        rows = await files_repo.get_many(session, list(file_ids))
        by_id = {row.id: row for row in rows}
        if not file_ids or any(file_id not in by_id for file_id in file_ids):
            raise ValidationFailed(MSG_FILE_NOT_FOUND)
        for kb_id in kb_ids:
            if await datasets_repo.get(session, kb_id) is None:
                raise ValidationFailed(MSG_DATASET_NOT_FOUND)
        leaves: list[FileRow] = []
        for file_id in file_ids:
            row = by_id[file_id]
            if row.type == FOLDER_TYPE:
                children = await files_repo.list_all_children(session, row.id)
                leaves.extend(child for child in children if child.type != FOLDER_TYPE)
            else:
                leaves.append(row)
    # Własność plików: cudzy → „no authorization" (upstream ``check_file_team_permission``).
    for leaf in leaves:
        svc.owned(principal, leaf)
    return leaves


async def _require_datasets(svc: FilesService, principal: Principal, kb_ids: Sequence[str]) -> None:
    """Dostęp do zapisu w każdym datasecie; odmowa → ``PermissionDenied("no authorization")``.

    Jedyne miejsce sprawdzania datasetu (K16 §D3): ``DatasetService.load`` z ``Action.UPDATE``;
    przechwytujemy jego ``PermissionDenied``/``NotFound`` i tłumaczymy na komunikat upstreamu.
    """
    service = DatasetService(svc.container)
    for kb_id in kb_ids:
        try:
            await service.load(principal, kb_id, Action.UPDATE)
        except (PermissionDenied, NotFound) as exc:
            raise PermissionDenied(MSG_NO_AUTHORIZATION) from exc


async def _link_file(
    svc: FilesService,
    principal: Principal,
    leaf: FileRow,
    kb_ids: Sequence[str],
    mode: str,
) -> list[FileLink]:
    """Wykonanie dla jednego pliku-liścia: ``replace`` usuwa obce linki, potem brakujące.

    Już zlinkowany (plik, dataset) jest pomijany (upstream „skip existing"), a jego wiązanie
    wraca z id wiersza z ``files_repo.list_links``. Linki do datasetów poza ``kb_ids`` w trybie
    ``replace`` kasujemy przez ``ingest.delete_documents`` — wiersz ``file2document`` znika
    kaskadą FK, a blob ``filemanager/…`` należy do wiersza `files` i zostaje (K16 §1 p. 5).
    Zwraca wiązania w kolejności ``kb_ids``; plik bez bloba nie ma czego zlinkować.
    """
    if leaf.location is None:  # plik bez bloba nie ma czego zlinkować (upload zawsze go zapisuje)
        return []
    async with transaction(svc.sessionmaker()) as session:
        links = await files_repo.list_links(session, leaf.id)
        docs = await documents_repo.get_many(session, [link.document_id for link in links])
    dataset_of = {doc.id: doc.dataset_id for doc in docs}
    existing = {
        dataset_of[link.document_id]: FileLink(
            id=link.id, file_id=leaf.id, document_id=link.document_id
        )
        for link in links
        if link.document_id in dataset_of
    }
    wanted = set(kb_ids)
    if mode == "replace":
        stale = [doc.id for doc in docs if doc.dataset_id not in wanted]
        if stale:
            await svc.container.ingest.delete_documents(stale)
    bound: list[FileLink] = []
    for kb_id in kb_ids:
        if kb_id in existing:
            bound.append(existing[kb_id])
            continue
        async with transaction(svc.sessionmaker()) as session:
            taken = await documents_query.names_in_dataset(session, kb_id)
        document = await svc.container.ingest.link_existing(
            kb_id,
            name=unique_name(leaf.name, taken),
            location=leaf.location,
            size=leaf.size,
            created_by=principal.user_id,
        )
        link_id = svc.container.id_gen.new_id()
        async with transaction(svc.sessionmaker()) as session:
            await files_repo.insert_link(
                session,
                id=link_id,
                file_id=leaf.id,
                document_id=document.id,
                now_ms=svc.container.clock.now_ms(),
            )
        bound.append(FileLink(id=link_id, file_id=leaf.id, document_id=document.id))
    return bound
