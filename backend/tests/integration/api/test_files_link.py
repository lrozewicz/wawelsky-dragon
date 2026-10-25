"""Testy linkowania plików do datasetów na prawdziwej MariaDB (brief T4, CONTRACT §D1.7, §D4).

Każdy wiersz tabeli „wejście → wyjście" z briefu ma osobny test; komunikaty błędów
porównywane dosłownie. Alice i Bob; datasety przez ``DatasetService.create``, pliki uploadem
przez ``FilesService`` (bloby w ``filemanager/``).
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import PermissionDenied, ValidationFailed
from app.db.repositories import documents as documents_repo
from app.db.repositories import files as files_repo
from app.db.repositories import models as models_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.domain.policy.principal import Principal
from app.services.datasets import DatasetService
from app.services.files import FilesService
from app.storage.keys import StorageKey
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME_MS
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

MSG_FILE_NOT_FOUND = "File not found!"
MSG_DATASET_NOT_FOUND = "Can't find this dataset!"
MSG_NO_AUTHORIZATION = "no authorization"
MISSING_DATASET = "0" * 32
CONTENT = b"ragflow intro"  # treść uploadu w testach linkowania
TWO_LINKS = 2  # liczba wiązań pliku po `mode="add"` do dwóch datasetów


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (wzór test_files_service) + wymiar modelu embedding z briefu T1a."""
    instance = await make_container(migrated_db, tmp_path)
    # register_models z make_container nie nadaje wymiaru; DatasetService.create go wymaga.
    async with transaction(instance.sessionmaker) as session:
        await models_repo.set_dimension_if_null(session, "e" * 32, 1024, TIME_MS)
    yield instance
    await instance.aclose()


def _svc(container: Container) -> FilesService:
    """Serwis na kontenerze testowym."""
    return FilesService(container)


async def _dataset(container: Container, principal: Principal, name: str) -> str:
    """Dataset principala przez usługę (domyślne modele z ``make_container``)."""
    record = await DatasetService(container).create(principal, name=name)
    return record.id


async def _doc_ids(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> list[str]:
    """Id dokumentów datasetu (kolejność: czas, id)."""
    async with transaction(sm) as session:
        found = await session.execute(
            text("SELECT id FROM documents WHERE dataset_id = :id ORDER BY create_time, id"),
            {"id": dataset_id},
        )
    return [str(row[0]) for row in found]


async def _docs(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> list[DocumentRow]:
    """Wiersze dokumentów datasetu."""
    ids = await _doc_ids(sm, dataset_id)
    if not ids:
        return []
    async with transaction(sm) as session:
        return await documents_repo.get_many(session, ids)


async def _links(sm: async_sessionmaker[AsyncSession], file_id: str) -> list[files_repo.LinkRow]:
    """Wiązania `file2document` pliku."""
    async with transaction(sm) as session:
        return await files_repo.list_links(session, file_id)


async def _kbs_info(sm: async_sessionmaker[AsyncSession], file_id: str) -> list[dict[str, str]]:
    """``kbs_info`` pliku (file_id → datasety linków)."""
    async with transaction(sm) as session:
        return (await files_repo.kbs_info(session, [file_id])).get(file_id, [])


async def _link(
    container: Container,
    principal: Principal,
    file_ids: list[str],
    kb_ids: list[str],
    *,
    mode: str = "replace",
) -> None:
    """Linkuje pliki do datasetów przez ``FilesService`` (wzorzec briefu T4)."""
    await _svc(container).link_to_datasets(principal, file_ids, kb_ids, mode=mode)


async def test_link_file_creates_document_on_file_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Link pliku → dokument datasetu z `location`/`name` pliku, `run="0"`, wiązanie (§D1.7)."""
    alice = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "A")
    file = await _svc(container).upload(
        alice, filename="ragflow_intro.txt", content=CONTENT, parent_id=None
    )
    await _link(container, alice, [file.id], [dataset_id])

    docs = await _docs(sm, dataset_id)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.name == "ragflow_intro.txt"
    assert doc.location == file.location
    assert doc.location == f"filemanager/{file.id}/original.txt"
    assert doc.suffix == "txt"
    assert doc.type == "doc"
    assert doc.size == file.size
    assert doc.created_by == alice.user_id
    assert doc.run == "0"
    assert doc.chunk_count == 0
    assert doc.dataset_id == dataset_id

    links = await _links(sm, file.id)
    assert [link.document_id for link in links] == [doc.id]
    assert await _kbs_info(sm, file.id) == [
        {"kb_id": dataset_id, "kb_name": "A", "document_id": doc.id}
    ]


async def test_link_folder_expands_to_nested_files(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Link folderu → dokumenty plików z folderu i podfolderów (brief T4 §4)."""
    alice = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "A")
    service = _svc(container)
    folder = await service.create_folder(alice, name="docs", parent_id=None)
    sub = await service.create_folder(alice, name="sub", parent_id=folder.id)
    await service.upload(alice, filename="a.txt", content=b"a", parent_id=folder.id)
    await service.upload(alice, filename="b.txt", content=b"b", parent_id=sub.id)

    await _link(container, alice, [folder.id], [dataset_id])

    assert sorted(doc.name for doc in await _docs(sm, dataset_id)) == ["a.txt", "b.txt"]


async def test_add_mode_keeps_previous_link(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`mode="add"` do drugiego datasetu zostawia pierwszy link (brief T4 §4)."""
    alice = principal_for(await seed_user(sm))
    first = await _dataset(container, alice, "A")
    second = await _dataset(container, alice, "B")
    file = await _svc(container).upload(alice, filename="a.txt", content=CONTENT, parent_id=None)
    await _link(container, alice, [file.id], [first])
    await _link(container, alice, [file.id], [second], mode="add")

    assert len(await _docs(sm, first)) == 1
    assert len(await _docs(sm, second)) == 1
    assert len(await _links(sm, file.id)) == TWO_LINKS


async def test_replace_mode_removes_previous_document_but_keeps_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`mode="replace"` z innym datasetem usuwa poprzedni dokument, blob pliku zostaje (§D1.6)."""
    alice = principal_for(await seed_user(sm))
    first = await _dataset(container, alice, "A")
    second = await _dataset(container, alice, "B")
    file = await _svc(container).upload(alice, filename="a.txt", content=CONTENT, parent_id=None)
    await _link(container, alice, [file.id], [first])
    await _link(container, alice, [file.id], [second])

    assert await _docs(sm, first) == []
    assert len(await _docs(sm, second)) == 1
    assert len(await _links(sm, file.id)) == 1
    assert await container.storage.exists(StorageKey(file.location or ""))


async def test_repeat_link_same_dataset_has_no_duplicate(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Ponowny link (plik, dataset) nie tworzy drugiego dokumentu (brief T4 §4)."""
    alice = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "A")
    file = await _svc(container).upload(alice, filename="a.txt", content=CONTENT, parent_id=None)
    await _link(container, alice, [file.id], [dataset_id])
    await _link(container, alice, [file.id], [dataset_id])

    assert len(await _docs(sm, dataset_id)) == 1
    assert len(await _links(sm, file.id)) == 1


async def test_name_collision_gets_counter(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dwa pliki o tej samej nazwie w datasecie → drugi dostaje dopisek `a(1).txt` (§D1.7)."""
    alice = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "A")
    service = _svc(container)
    first_folder = await service.create_folder(alice, name="f1", parent_id=None)
    second_folder = await service.create_folder(alice, name="f2", parent_id=None)
    first = await service.upload(alice, filename="a.txt", content=b"1", parent_id=first_folder.id)
    second = await service.upload(alice, filename="a.txt", content=b"2", parent_id=second_folder.id)

    await _link(container, alice, [first.id, second.id], [dataset_id])

    assert sorted(doc.name for doc in await _docs(sm, dataset_id)) == ["a(1).txt", "a.txt"]


async def test_missing_file_raises(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieistniejący plik → 102 „File not found!" (brief T4 §4)."""
    alice = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "A")
    with pytest.raises(ValidationFailed) as error:
        await _link(container, alice, [uuid.uuid4().hex], [dataset_id])
    assert str(error.value) == MSG_FILE_NOT_FOUND


async def test_missing_dataset_raises(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieistniejący dataset → 102 „Can't find this dataset!" (brief T4 §4)."""
    alice = principal_for(await seed_user(sm))
    file = await _svc(container).upload(alice, filename="a.txt", content=CONTENT, parent_id=None)
    with pytest.raises(ValidationFailed) as error:
        await _link(container, alice, [file.id], [MISSING_DATASET])
    assert str(error.value) == MSG_DATASET_NOT_FOUND


async def test_foreign_file_raises(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudzy plik → `PermissionDenied("no authorization")` (brief T4 §4)."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "A")
    foreign = await _svc(container).upload(bob, filename="a.txt", content=CONTENT, parent_id=None)
    with pytest.raises(PermissionDenied) as error:
        await _link(container, alice, [foreign.id], [dataset_id])
    assert str(error.value) == MSG_NO_AUTHORIZATION


async def test_foreign_dataset_raises(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Własny plik + cudzy dataset → `PermissionDenied("no authorization")` (brief T4 §4)."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    foreign_dataset = await _dataset(container, bob, "B")
    file = await _svc(container).upload(alice, filename="a.txt", content=CONTENT, parent_id=None)
    with pytest.raises(PermissionDenied) as error:
        await _link(container, alice, [file.id], [foreign_dataset])
    assert str(error.value) == MSG_NO_AUTHORIZATION


async def test_deleting_linked_document_keeps_file_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Usunięcie zlinkowanego dokumentu zostawia blob pliku i kasuje wiązanie (§D1.6, T3)."""
    alice = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "A")
    file = await _svc(container).upload(alice, filename="a.txt", content=CONTENT, parent_id=None)
    await _link(container, alice, [file.id], [dataset_id])
    docs = await _docs(sm, dataset_id)
    assert len(docs) == 1

    await container.ingest.delete_documents([docs[0].id])

    assert await _docs(sm, dataset_id) == []
    assert await _links(sm, file.id) == []
    assert await container.storage.exists(StorageKey(file.location or ""))
