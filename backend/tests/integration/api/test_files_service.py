"""Testy usługi menedżera plików na prawdziwej MariaDB (brief T2, CONTRACT E4-5a §D1, §D3).

Każdy wiersz tabeli „wejście → wyjście" z briefu T2 ma osobny test; komunikaty błędów
porównywane dosłownie. Port `file_api_service`/`FileService` upstream v0.27.2.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import PermissionDenied, ValidationFailed
from app.db.repositories import files as files_repo
from app.db.uow import transaction
from app.services import files_ops
from app.services.files import FileListPage, FilesService
from app.storage.keys import StorageKey
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME, TIME_MS
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

MSG_DUPLICATED_FOLDER_NAME = "Duplicated folder name in the same folder."
MSG_FOLDER_NOT_FOUND = "Folder not found!"
MSG_DOCUMENT_NOT_FOUND = "document not found"
MSG_NO_AUTHORIZATION = "no authorization"
MSG_FILE_EMPTY = "This file is empty."
UPLOAD_CONTENT = b"x" * 10  # treść uploadu z tabeli briefu T2 (size = 10)
ROOT_ENTRIES = 3  # wiersze widoczne w rootcie w teście listingu
MATCHING_ENTRIES = 2  # wiersze pasujące do keywords „B” w teście listingu
PAGE_SIZE = 2  # rozmiar strony w teście stronicowania


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (wzór tests/integration/api/test_searches_service.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _svc(container: Container) -> FilesService:
    """Serwis na kontenerze testowym."""
    return FilesService(container)


async def _root_rows(sm: async_sessionmaker[AsyncSession], tenant_id: str) -> int:
    """Liczba wierszy roota użytkownika (parent_id NULL, nazwa „/"”)."""
    async with transaction(sm) as session:
        found = await session.execute(
            text(
                "SELECT COUNT(*) FROM files WHERE tenant_id = :tenant"
                " AND parent_id IS NULL AND name = '/'"
            ),
            {"tenant": tenant_id},
        )
    return int(found.scalar_one())


async def _seed_file_row(  # noqa: PLR0913 — helper testowy z opcjonalnymi polami wiersza
    sm: async_sessionmaker[AsyncSession],
    tenant_id: str,
    parent_id: str,
    name: str,
    *,
    source_type: str = "local",
    type_: str = "doc",
    location: str | None = None,
) -> str:
    """Wstawia surowy wiersz `files` (pomija serwis) i zwraca jego id."""
    file_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO files (id, tenant_id, created_by, parent_id, name, type, size,"
                " location, source_type, create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, :parent, :name, :type, 0, :location,"
                " :source_type, :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": file_id,
                "tenant": tenant_id,
                "parent": parent_id,
                "name": name,
                "type": type_,
                "location": location,
                "source_type": source_type,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
    return file_id


async def _seed_linked_document(
    sm: async_sessionmaker[AsyncSession],
    tenant_id: str,
    file_id: str,
    *,
    dataset_name: str = "Korpus",
) -> tuple[str, str]:
    """Wstawia dataset + dokument oraz wiązanie `file2document`; zwraca (dataset_id, doc_id)."""
    dataset_id = uuid.uuid4().hex
    document_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, :name, 'fake-embed-1024', 1024,"
                " :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": dataset_id,
                "tenant": tenant_id,
                "name": dataset_name,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
        await session.execute(
            text(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type,"
                " location, content_hash, chunk_method, parser_config, create_time,"
                " create_date, update_time, update_date)"
                " VALUES (:id, :dataset, :tenant, 'a.txt', 'txt', 'doc', :location,"
                " :hash, 'naive', '{}', :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": document_id,
                "dataset": dataset_id,
                "tenant": tenant_id,
                "location": f"filemanager/{file_id}/original.txt",
                "hash": "0" * 32,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
        await files_repo.insert_link(
            session, id=uuid.uuid4().hex, file_id=file_id, document_id=document_id, now_ms=TIME_MS
        )
    return dataset_id, document_id


async def test_root_is_lazy_and_single_row_under_concurrency(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dwa równoległe `root` → ten sam id i JEDEN wiersz roota (brief T2 §3, D1.2)."""
    alice = principal_for(await seed_user(sm))
    service = _svc(container)
    assert await _root_rows(sm, alice.user_id) == 0
    first, second = await asyncio.gather(service.root(alice), service.root(alice))
    assert first.id == second.id
    assert await _root_rows(sm, alice.user_id) == 1
    assert (first.name, first.type, first.parent_id) == ("/", "folder", None)
    assert first.tenant_id == alice.user_id
    assert first.created_by == alice.user_id
    assert first.location is None
    assert first.size == 0
    assert (await service.root(alice)).id == first.id
    assert await _root_rows(sm, alice.user_id) == 1


async def test_list_new_user_returns_root_page(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nowy użytkownik: listing roota → pusta strona, w DB jeden wiersz roota (brief T2)."""
    alice = principal_for(await seed_user(sm))
    page = await _svc(container).list(
        alice, parent_id=None, keywords=None, orderby="create_time", desc=True, page=1, page_size=15
    )
    assert isinstance(page, FileListPage)
    assert (page.parent.name, page.parent.type) == ("/", "folder")
    assert page.files == []
    assert page.total == 0
    assert await _root_rows(sm, alice.user_id) == 1


async def test_create_folder_duplicate_rejected(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`create_folder` dwa razy o tej samej nazwie → 102 „Duplicated folder name…” (brief T2)."""
    alice = principal_for(await seed_user(sm))
    service = _svc(container)
    root = await service.root(alice)
    first = await service.create_folder(alice, name="f", parent_id=None)
    assert (first.name, first.type, first.parent_id) == ("f", "folder", root.id)
    assert first.location is None
    assert first.size == 0
    with pytest.raises(ValidationFailed) as error:
        await service.create_folder(alice, name="f", parent_id=None)
    assert str(error.value) == MSG_DUPLICATED_FOLDER_NAME
    other = await service.create_folder(alice, name="g", parent_id=None)
    assert (await service.create_folder(alice, name="f", parent_id=other.id)).parent_id == other.id


async def test_create_folder_missing_or_foreign_parent(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieistniejący rodzic → 102 „Parent Folder Doesn't Exist!”; cudzy → 102 „no authorization”."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    service = _svc(container)
    with pytest.raises(ValidationFailed) as error:
        await service.create_folder(alice, name="f", parent_id=uuid.uuid4().hex)
    assert str(error.value) == "Parent Folder Doesn't Exist!"
    bob_folder = await service.create_folder(bob, name="boba", parent_id=None)
    with pytest.raises(PermissionDenied) as error:
        await service.create_folder(alice, name="f", parent_id=bob_folder.id)
    assert str(error.value) == MSG_NO_AUTHORIZATION


async def test_create_folder_name_with_slash_rejected(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nazwa z „/"” → 102 jak upstream `create_folder` („Folder name cannot contain…")."""
    alice = principal_for(await seed_user(sm))
    with pytest.raises(ValidationFailed) as error:
        await _svc(container).create_folder(alice, name="a/b", parent_id=None)
    assert str(error.value) == 'Folder name cannot contain "/"'


async def test_upload_stores_blob_and_row_fields(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Upload: `size` = bajty, `type` = doc, `location` = `filemanager/<id>/original.txt`."""
    alice = principal_for(await seed_user(sm))
    service = _svc(container)
    root = await service.root(alice)
    row = await service.upload(alice, filename="a.txt", content=UPLOAD_CONTENT, parent_id=None)
    assert row.size == len(UPLOAD_CONTENT)
    assert row.type == "doc"
    assert row.name == "a.txt"
    assert row.location == f"filemanager/{row.id}/original.txt"
    assert row.source_type == "local"
    assert row.parent_id == root.id
    assert row.tenant_id == alice.user_id
    assert row.created_by == alice.user_id
    assert await container.storage.exists(StorageKey(row.location))


async def test_upload_duplicate_name_gets_counter(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Ten sam upload drugi raz w tym samym folderze → nazwa `a(1).txt` (brief T2)."""
    alice = principal_for(await seed_user(sm))
    service = _svc(container)
    folder = await service.create_folder(alice, name="f", parent_id=None)
    first = await service.upload(alice, filename="a.txt", content=b"x", parent_id=folder.id)
    second = await service.upload(alice, filename="a.txt", content=b"y", parent_id=folder.id)
    third = await service.upload(alice, filename="a.txt", content=b"z", parent_id=folder.id)
    assert first.name == "a.txt"
    assert second.name == "a(1).txt"
    assert third.name == "a(2).txt"
    assert second.location == f"filemanager/{second.id}/original.txt"
    assert await container.storage.exists(StorageKey(second.location))


async def test_upload_missing_or_foreign_parent(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Upload do nieistniejącego folderu → 102; do cudzego → 102 „no authorization”."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    service = _svc(container)
    with pytest.raises(ValidationFailed) as error:
        await service.upload(alice, filename="a.txt", content=b"x", parent_id=uuid.uuid4().hex)
    assert str(error.value) == "Can't find this folder!"
    bob_folder = await service.create_folder(bob, name="boba", parent_id=None)
    with pytest.raises(PermissionDenied) as error:
        await service.upload(alice, filename="a.txt", content=b"x", parent_id=bob_folder.id)
    assert str(error.value) == MSG_NO_AUTHORIZATION


async def test_ancestors_and_parent_chain(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`ancestors` pliku w `sub/f` → [plik, sub, f, root]; `parent` roota → root (brief T2)."""
    alice = principal_for(await seed_user(sm))
    service = _svc(container)
    root = await service.root(alice)
    parent = await service.create_folder(alice, name="f", parent_id=None)
    sub = await service.create_folder(alice, name="sub", parent_id=parent.id)
    file = await service.upload(alice, filename="a.txt", content=b"x", parent_id=sub.id)
    chain = await service.ancestors(alice, file.id)
    assert [row.name for row in chain] == ["a.txt", "sub", "f", "/"]
    assert [row.id for row in chain] == [file.id, sub.id, parent.id, root.id]
    assert (await service.ancestors(alice, root.id))[0].id == root.id
    assert (await service.parent(alice, file.id)).id == sub.id
    assert (await service.parent(alice, sub.id)).id == parent.id
    assert (await service.parent(alice, root.id)).id == root.id


async def test_ancestors_and_parent_missing_or_foreign(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak → 102 „Folder not found!”; cudzy → ``PermissionDenied("no authorization")``."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    service = _svc(container)
    missing = uuid.uuid4().hex
    with pytest.raises(ValidationFailed) as error:
        await service.ancestors(alice, missing)
    assert str(error.value) == MSG_FOLDER_NOT_FOUND
    with pytest.raises(ValidationFailed) as error:
        await service.parent(alice, missing)
    assert str(error.value) == MSG_FOLDER_NOT_FOUND
    alice_file = await service.upload(alice, filename="a.txt", content=b"x", parent_id=None)
    with pytest.raises(PermissionDenied) as error:
        await service.ancestors(bob, alice_file.id)
    assert str(error.value) == MSG_NO_AUTHORIZATION
    with pytest.raises(PermissionDenied) as error:
        await service.parent(bob, alice_file.id)
    assert str(error.value) == MSG_NO_AUTHORIZATION


async def test_open_missing_foreign_folder_and_empty_blob(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`open`: brak → „document not found”; cudzy → 102; folder/brak bloba → „empty”."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    service = _svc(container)
    with pytest.raises(ValidationFailed) as error:
        await service.open(alice, uuid.uuid4().hex)
    assert str(error.value) == MSG_DOCUMENT_NOT_FOUND
    row = await service.upload(alice, filename="a.txt", content=b"hello", parent_id=None)
    with pytest.raises(PermissionDenied) as error:
        await service.open(bob, row.id)
    assert str(error.value) == MSG_NO_AUTHORIZATION
    got, stream = await service.open(alice, row.id)
    assert got.id == row.id
    assert b"".join([chunk async for chunk in stream]) == b"hello"
    root = await service.root(alice)
    folder = await service.create_folder(alice, name="f", parent_id=None)
    with pytest.raises(ValidationFailed) as error:
        await service.open(alice, folder.id)
    assert str(error.value) == MSG_FILE_EMPTY
    ghost = await _seed_file_row(
        sm,
        alice.user_id,
        root.id,
        "ghost.txt",
        location=f"filemanager/{uuid.uuid4().hex}/original.txt",
    )
    with pytest.raises(ValidationFailed) as error:
        await service.open(alice, ghost)
    assert str(error.value) == MSG_FILE_EMPTY


async def test_visible_returns_only_visible_rows(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`visible` zwraca wiersz lokalny, ``None`` dla `knowledgebase` i dla braku (D1.1)."""
    alice = principal_for(await seed_user(sm))
    service = _svc(container)
    root = await service.root(alice)
    hidden = await _seed_file_row(
        sm, alice.user_id, root.id, ".knowledgebase", source_type="knowledgebase", type_="folder"
    )
    async with transaction(sm) as session:
        assert (await service.visible(session, root.id)).id == root.id
        assert await service.visible(session, hidden) is None
        assert await service.visible(session, uuid.uuid4().hex) is None


async def test_list_views_and_hidden_knowledgebase(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Listing: `has_child_folder`/`kbs_info` dla folderów, ``None`` dla plików, bez `kb`."""
    alice = principal_for(await seed_user(sm))
    service = _svc(container)
    root = await service.root(alice)
    folder = await service.create_folder(alice, name="f", parent_id=None)
    await service.create_folder(alice, name="leaf", parent_id=folder.id)
    empty = await service.create_folder(alice, name="empty", parent_id=None)
    file = await service.upload(alice, filename="a.txt", content=b"x", parent_id=None)
    await _seed_file_row(
        sm, alice.user_id, root.id, ".knowledgebase", source_type="knowledgebase", type_="folder"
    )
    dataset_id, document_id = await _seed_linked_document(sm, alice.user_id, file.id)
    page = await service.list(
        alice, parent_id=None, keywords=None, orderby="create_time", desc=True, page=1, page_size=15
    )
    assert page.total == ROOT_ENTRIES
    assert {view.row.name for view in page.files} == {"f", "empty", "a.txt"}
    by_name = {view.row.name: view for view in page.files}
    assert by_name["f"].has_child_folder is True
    assert by_name["empty"].has_child_folder is False
    assert by_name["a.txt"].has_child_folder is None
    assert by_name["f"].kbs_info == []
    assert by_name["empty"].kbs_info == []
    assert by_name["a.txt"].kbs_info == [
        {"kb_id": dataset_id, "kb_name": "Korpus", "document_id": document_id}
    ]
    assert page.parent.id == root.id
    assert empty.parent_id == root.id


async def test_list_keywords_orderby_pagination_and_foreign(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Filtrowanie/orientacja/stronicowanie listingu; cudzy i brakujący folder (brief T2 §4)."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    service = _svc(container)
    await service.create_folder(alice, name="a1", parent_id=None)
    await service.create_folder(alice, name="b1", parent_id=None)
    await service.upload(alice, filename="b1.txt", content=b"x", parent_id=None)
    filtered = await service.list(
        alice, parent_id=None, keywords="B", orderby="name", desc=False, page=1, page_size=15
    )
    assert {view.row.name for view in filtered.files} == {"b1", "b1.txt"}
    assert filtered.total == MATCHING_ENTRIES
    first_page = await service.list(
        alice,
        parent_id=None,
        keywords=None,
        orderby="name",
        desc=False,
        page=1,
        page_size=PAGE_SIZE,
    )
    assert [view.row.name for view in first_page.files] == ["a1", "b1"]
    assert first_page.total == ROOT_ENTRIES
    bob_folder = await service.create_folder(bob, name="boba", parent_id=None)
    with pytest.raises(PermissionDenied) as error:
        await service.list(
            alice,
            parent_id=bob_folder.id,
            keywords=None,
            orderby="create_time",
            desc=True,
            page=1,
            page_size=15,
        )
    assert str(error.value) == MSG_NO_AUTHORIZATION
    with pytest.raises(ValidationFailed) as error:
        await service.list(
            alice,
            parent_id=uuid.uuid4().hex,
            keywords=None,
            orderby="create_time",
            desc=True,
            page=1,
            page_size=15,
        )
    assert str(error.value) == MSG_FOLDER_NOT_FOUND


async def test_move_delete_link_delegate_to_modules(
    container: Container, sm: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`move`/`delete`/`link_to_datasets` tylko delegują do `files_ops`/`files_link` (brief §7)."""
    alice = principal_for(await seed_user(sm))
    calls: list[tuple] = []

    async def fake_move(
        svc: object, principal: object, src_ids: list, dest_id: object, new_name: object
    ) -> None:
        calls.append(("move", svc, principal, list(src_ids), dest_id, new_name))

    async def fake_delete(svc: object, principal: object, ids: list) -> None:
        calls.append(("delete", svc, principal, list(ids)))

    async def fake_link(
        svc: object, principal: object, file_ids: list, kb_ids: list, mode: str
    ) -> None:
        calls.append(("link", svc, principal, list(file_ids), list(kb_ids), mode))

    monkeypatch.setattr(files_ops, "move_files", fake_move)
    monkeypatch.setattr(files_ops, "delete_files", fake_delete)
    monkeypatch.setattr("app.services.files_link.link_files", fake_link)
    service = _svc(container)
    await service.move(alice, ["src"], dest_id="dest", new_name="n")
    await service.delete(alice, ["a", "b"])
    await service.link_to_datasets(alice, ["f"], ["kb"], mode="add")
    assert calls == [
        ("move", service, alice, ["src"], "dest", "n"),
        ("delete", service, alice, ["a", "b"]),
        ("link", service, alice, ["f"], ["kb"], "add"),
    ]
