"""Testy `move_files`/`delete_files` na prawdziwej MariaDB (brief T3, CONTRACT E4-5a §D1.8, §D3).

Każdy wiersz tabeli „wejście → wyjście" z briefu T3 ma osobny test; komunikaty błędów
porównywane dosłownie z upstreamem i złotem (``files__move/files--*``, ``files/files--*``).
Testy negatywne „move cudzego" i „delete cudzego" są tu dla mutacji T7.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import PermissionDenied, ValidationFailed
from app.db.repositories import files as files_repo
from app.db.repositories.files import FileRow
from app.db.uow import transaction
from app.domain.policy.principal import Principal
from app.services.files import DeleteOutcome, FilesService
from app.storage.keys import StorageKey
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

MSG_SOURCE_FILES_NOT_FOUND = "Source files not found!"
MSG_MOVE_INTO_SUBFOLDER = "Cannot move a folder into its own subfolder."
MSG_NO_AUTHORIZATION = "no authorization"
MSG_EXTENSION_CHANGED = "The extension of file can't be changed"
MSG_DUPLICATED_FILE_NAME = "Duplicated file name in the same folder."
# Poprawka z przeglądu T3 (dopisane w T6): komunikaty upstream `move_files`/
# `_move_entry_recursive` dla braku/niewłaściwego celu i przeniesienia wiersza w siebie.
MSG_PARENT_FOLDER_NOT_FOUND = "Parent folder not found!"
MSG_ALREADY_IN_TARGET = "The folder is already in the target location. There is no need to move it."
CONTENT = b"tresc pliku"  # treść uploadu w testach move/delete


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (wzór tests/integration/api/test_files_service.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


async def _uploaded(
    svc: FilesService, principal: Principal, *, name: str = "a.txt", parent_id: str | None = None
) -> FileRow:
    """Plik wg usługi (blob `filemanager/{id}/original.txt`)."""
    return await svc.upload(principal, filename=name, content=CONTENT, parent_id=parent_id)


async def _row(sm: async_sessionmaker[AsyncSession], file_id: str) -> FileRow | None:
    """Świeży wiersz `files` (widoczny) albo ``None``."""
    async with transaction(sm) as session:
        return await files_repo.get(session, file_id)


async def test_move_file_to_folder_keeps_name_and_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`move(dest_id)` → plik w folderze docelowym, nazwa i blob bez zmian, `update_time` rośnie."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    folder = await svc.create_folder(alice, name="cel", parent_id=None)
    file_row = await _uploaded(svc, alice, name="a.txt", parent_id=None)

    await svc.move(alice, [file_row.id], dest_id=folder.id, new_name=None)

    moved = await _row(sm, file_row.id)
    assert moved is not None
    assert moved.parent_id == folder.id
    assert moved.name == "a.txt"
    assert moved.location == file_row.location
    assert await container.storage.exists(StorageKey(file_row.location or ""))
    assert moved.update_time >= file_row.update_time


async def test_rename_file_in_place_and_with_move(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`move(new_name)` → tylko nazwa; `move(dest_id, new_name)` → przeniesienie i nazwa."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    root = await svc.root(alice)
    file_row = await _uploaded(svc, alice, name="a.txt", parent_id=None)

    await svc.move(alice, [file_row.id], dest_id=None, new_name="b.txt")

    renamed = await _row(sm, file_row.id)
    assert renamed is not None
    assert renamed.name == "b.txt"
    assert renamed.parent_id == root.id
    assert renamed.location == file_row.location

    folder = await svc.create_folder(alice, name="cel", parent_id=None)
    await svc.move(alice, [file_row.id], dest_id=folder.id, new_name="c.txt")

    both = await _row(sm, file_row.id)
    assert both is not None
    assert (both.name, both.parent_id) == ("c.txt", folder.id)
    assert await container.storage.exists(StorageKey(file_row.location or ""))


async def test_move_source_not_found(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieistniejący `src_id` → 102 „Source files not found!" (złoto ``files--20``)."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    folder = await svc.create_folder(alice, name="cel", parent_id=None)
    missing = "0" * 32

    with pytest.raises(ValidationFailed) as error:
        await svc.move(alice, [missing], dest_id=folder.id, new_name=None)

    assert str(error.value) == MSG_SOURCE_FILES_NOT_FOUND


async def test_move_folder_into_own_subfolder_and_into_itself(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Folder do własnego potomka/siebie → 102 „Cannot move a folder into its own subfolder."."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    root = await svc.root(alice)
    folder = await svc.create_folder(alice, name="f", parent_id=None)
    sub = await svc.create_folder(alice, name="sub", parent_id=folder.id)

    for dest_id in (sub.id, folder.id):
        with pytest.raises(ValidationFailed) as error:
            await svc.move(alice, [folder.id], dest_id=dest_id, new_name=None)
        assert str(error.value) == MSG_MOVE_INTO_SUBFOLDER

    unchanged = await _row(sm, folder.id)
    assert unchanged is not None and unchanged.parent_id == root.id


async def test_move_foreign_file_or_foreign_destination(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudzy plik i cudzy folder docelowy → ``PermissionDenied("no authorization")`` (files--29)."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    svc = FilesService(container)
    alice_file = await _uploaded(svc, alice, name="a.txt", parent_id=None)
    alice_folder = await svc.create_folder(alice, name="alice", parent_id=None)
    bob_file = await _uploaded(svc, bob, name="b.txt", parent_id=None)
    bob_folder = await svc.create_folder(bob, name="bob", parent_id=None)

    with pytest.raises(PermissionDenied) as error:
        await svc.move(bob, [alice_file.id], dest_id=bob_folder.id, new_name=None)
    assert str(error.value) == MSG_NO_AUTHORIZATION

    with pytest.raises(PermissionDenied) as error:
        await svc.move(alice, [bob_file.id], dest_id=alice_folder.id, new_name=None)
    assert str(error.value) == MSG_NO_AUTHORIZATION

    with pytest.raises(PermissionDenied) as error:
        await svc.move(alice, [alice_file.id], dest_id=bob_folder.id, new_name=None)
    assert str(error.value) == MSG_NO_AUTHORIZATION

    untouched = await _row(sm, alice_file.id)
    assert untouched is not None and untouched.parent_id is not None


async def test_move_new_name_validation(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`new_name`: separator, zmiana rozszerzenia i zajęta nazwa → 102 jak upstream."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    file_row = await _uploaded(svc, alice, name="a.txt", parent_id=None)
    await _uploaded(svc, alice, name="zajete.txt", parent_id=None)

    with pytest.raises(ValidationFailed) as error:
        await svc.move(alice, [file_row.id], dest_id=None, new_name="pod/plik.txt")
    assert str(error.value) == 'Name cannot contain "/"'

    with pytest.raises(ValidationFailed) as error:
        await svc.move(alice, [file_row.id], dest_id=None, new_name="a.pdf")
    assert str(error.value) == MSG_EXTENSION_CHANGED

    with pytest.raises(ValidationFailed) as error:
        await svc.move(alice, [file_row.id], dest_id=None, new_name="zajete.txt")
    assert str(error.value) == MSG_DUPLICATED_FILE_NAME

    unchanged = await _row(sm, file_row.id)
    assert unchanged is not None and unchanged.name == "a.txt"


async def test_delete_file_removes_row_and_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`delete([plik])` → ``DeleteOutcome(1, [])``, wiersz i blob zniknęły (złoto ``files--34``)."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    file_row = await _uploaded(svc, alice, name="a.txt", parent_id=None)

    outcome = await svc.delete(alice, [file_row.id])

    assert outcome == DeleteOutcome(success_count=1, errors=[])
    assert await _row(sm, file_row.id) is None
    assert not await container.storage.exists(StorageKey(file_row.location or ""))


async def test_delete_folder_with_subfolder_counts_every_row(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`delete([folder z podfolderem])` → ``DeleteOutcome(2, [])`` (złoto ``files--35``)."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    folder = await svc.create_folder(alice, name="f", parent_id=None)
    sub = await svc.create_folder(alice, name="sub", parent_id=folder.id)

    outcome = await svc.delete(alice, [folder.id])

    assert outcome == DeleteOutcome(success_count=2, errors=[])
    assert await _row(sm, folder.id) is None
    assert await _row(sm, sub.id) is None


async def test_delete_folder_recurses_into_file_and_removes_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Folder z plikiem w podfolderze → 3 wiersze i blob pliku usunięty (rekurencja od liści)."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    outer = await svc.create_folder(alice, name="outer", parent_id=None)
    inner = await svc.create_folder(alice, name="inner", parent_id=outer.id)
    deep_file = await _uploaded(svc, alice, name="a.txt", parent_id=inner.id)

    outcome = await svc.delete(alice, [outer.id])

    assert outcome == DeleteOutcome(success_count=3, errors=[])
    assert await _row(sm, deep_file.id) is None
    assert not await container.storage.exists(StorageKey(deep_file.location or ""))


async def test_delete_missing_id_reports_error(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieistniejące id → ``errors == ["File or Folder not found: <id>"]`` i 0 sukcesów (§D1.8)."""
    alice = principal_for(await seed_user(sm))
    missing = "0" * 32

    outcome = await FilesService(container).delete(alice, [missing])

    assert outcome == DeleteOutcome(
        success_count=0, errors=[f"File or Folder not found: {missing}"]
    )


async def test_delete_foreign_file_reports_error_and_keeps_it(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudzy plik → błąd w ``errors`` (nie wyjątek), wiersz i blob nietknięte (``files--31``)."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    svc = FilesService(container)
    alice_file = await _uploaded(svc, alice, name="a.txt", parent_id=None)

    outcome = await svc.delete(bob, [alice_file.id])

    assert outcome == DeleteOutcome(
        success_count=0, errors=[f"No authorization for file {alice_file.id}"]
    )
    assert await _row(sm, alice_file.id) is not None
    assert await container.storage.exists(StorageKey(alice_file.location or ""))


async def test_delete_mixed_ids_reports_partial_success(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Plik + nieistniejące id → ``success_count 1`` i jeden błąd (kolejność wejścia, §D1.8)."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    file_row = await _uploaded(svc, alice, name="a.txt", parent_id=None)
    missing = uuid.uuid4().hex

    outcome = await svc.delete(alice, [file_row.id, missing])

    assert outcome == DeleteOutcome(
        success_count=1, errors=[f"File or Folder not found: {missing}"]
    )
    assert await _row(sm, file_row.id) is None


async def test_move_missing_destination_folder(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak/ukryty folder docelowy → 102 „Parent folder not found!" (upstream ``move_files``)."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    root = await svc.root(alice)
    file_row = await _uploaded(svc, alice, name="a.txt", parent_id=None)

    with pytest.raises(ValidationFailed) as error:
        await svc.move(alice, [file_row.id], dest_id="0" * 32, new_name=None)

    assert str(error.value) == MSG_PARENT_FOLDER_NOT_FOUND
    unchanged = await _row(sm, file_row.id)
    assert unchanged is not None and unchanged.parent_id == root.id


async def test_move_destination_must_be_folder_and_not_source(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cel = plik → „Parent folder not found!"; cel = źródło → „already in the target location"."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    root = await svc.root(alice)
    source = await _uploaded(svc, alice, name="a.txt", parent_id=None)
    other = await _uploaded(svc, alice, name="b.txt", parent_id=None)

    # Cel nie jest folderem (plik B) — upstream nie ma na to własnego komunikatu, a dla
    # klienta to sytuacja braku folderu docelowego (decyzja Doradcy, punkt 8).
    with pytest.raises(ValidationFailed) as error:
        await svc.move(alice, [source.id], dest_id=other.id, new_name=None)
    assert str(error.value) == MSG_PARENT_FOLDER_NOT_FOUND

    # Cel = źródło (plik sam w siebie) — dosłownie upstream `_move_entry_recursive`.
    with pytest.raises(ValidationFailed) as error:
        await svc.move(alice, [source.id], dest_id=source.id, new_name=None)
    assert str(error.value) == MSG_ALREADY_IN_TARGET

    unchanged = await _row(sm, source.id)
    assert unchanged is not None and unchanged.parent_id == root.id
    assert await container.storage.exists(StorageKey(source.location or ""))
