"""Własność bloba `filemanager/…` wobec dokumentów (CONTRACT E4-5a §D1.6, K16 §1 p. 5, §2 p. 4).

Trzy scenariusze zmiany własności: usunięcie dokumentu nie kasuje bloba pliku (`ingest.
delete_documents`), podmiana treści dokumentu nie kasuje starego bloba `filemanager/`
(`ingest.replace`), a usunięcie pliku kasuje razem zlinkowany dokument (`FilesService.delete`).
Wiązanie `file2document` zakładamy ręcznie (usługa linkowania to T4).
"""

import dataclasses
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.repositories import files as files_repo
from app.db.repositories.documents import DocumentRow
from app.db.repositories.files import FileRow
from app.db.uow import transaction
from app.domain.policy.principal import Principal
from app.services.files import DeleteOutcome, FilesService
from app.storage.keys import StorageKey
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME_MS, make_document_row, seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container, make_source
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

FILE_CONTENT = b"tresc pliku z filemanagera"
REPLACED_CONTENT = b"nowa tresc dokumentu"


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (wzór tests/integration/api/test_files_service.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


async def _uploaded_file(svc: FilesService, principal: Principal) -> FileRow:
    """Plik z blobem `filemanager/{id}/original.txt` (przez usługę, nie surowy wiersz)."""
    return await svc.upload(principal, filename="a.txt", content=FILE_CONTENT, parent_id=None)


async def _link_document_to_file_blob(
    sm: async_sessionmaker[AsyncSession], file_row: FileRow
) -> DocumentRow:
    """Wstawia dokument z `location` = klucz bloba pliku i wiązanie `file2document` (ręcznie)."""
    dataset = await seed_dataset(sm)
    document = dataclasses.replace(
        make_document_row(dataset, name=file_row.name), location=file_row.location
    )
    async with transaction(sm) as session:
        await documents_repo.insert(session, document)
        await files_repo.insert_link(
            session,
            id=uuid.uuid4().hex,
            file_id=file_row.id,
            document_id=document.id,
            now_ms=TIME_MS,
        )
    return document


async def _row_exists(sm: async_sessionmaker[AsyncSession], file_id: str) -> bool:
    """Czy wiersz `files` jeszcze jest (§D1.1 — wiersze widoczne)."""
    async with transaction(sm) as session:
        return await files_repo.get(session, file_id) is not None


async def _document_exists(sm: async_sessionmaker[AsyncSession], document_id: str) -> bool:
    """Czy wiersz `documents` jeszcze jest."""
    async with transaction(sm) as session:
        return await documents_repo.get(session, document_id) is not None


async def test_delete_documents_keeps_file_blob_and_row(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Usunięcie dokumentu: blob pliku i wiersz `files` zostają, wiązanie znika (§D1.6)."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    file_row = await _uploaded_file(svc, alice)
    document = await _link_document_to_file_blob(sm, file_row)
    location = StorageKey(file_row.location or "")
    assert await container.storage.exists(location)

    await container.ingest.delete_documents([document.id])

    assert await container.storage.exists(location)
    assert await _row_exists(sm, file_row.id)
    assert not await _document_exists(sm, document.id)
    async with transaction(sm) as session:
        assert await files_repo.list_links(session, file_row.id) == []


async def test_replace_keeps_old_filemanager_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`ingest.replace`: stary blob `filemanager/` zostaje, dokument dostaje klucz `files/`.

    Reguła z CONTRACT §D1.6 (K16 §1 p. 5): blob `filemanager/…` jest własnością wiersza
    `files`, więc podmiana treści dokumentu nie może go usunąć.
    """
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    file_row = await _uploaded_file(svc, alice)
    document = await _link_document_to_file_blob(sm, file_row)
    old_location = StorageKey(file_row.location or "")

    updated = await container.ingest.replace(
        document.id, make_source(REPLACED_CONTENT, file_row.name)
    )

    assert updated.location != file_row.location
    assert updated.location.startswith("files/")
    assert await container.storage.exists(old_location)
    assert await container.storage.exists(StorageKey(updated.location))
    assert await _row_exists(sm, file_row.id)


async def test_delete_file_removes_document_row_and_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`FilesService.delete`: dokument znika z `documents`, wiersz pliku i blob też (§D1.6)."""
    alice = principal_for(await seed_user(sm))
    svc = FilesService(container)
    file_row = await _uploaded_file(svc, alice)
    document = await _link_document_to_file_blob(sm, file_row)

    outcome = await svc.delete(alice, [file_row.id])

    assert outcome == DeleteOutcome(success_count=1, errors=[])
    assert not await container.storage.exists(StorageKey(file_row.location or ""))
    assert not await _row_exists(sm, file_row.id)
    assert not await _document_exists(sm, document.id)
    async with transaction(sm) as session:
        assert await files_repo.list_links(session, file_row.id) == []
