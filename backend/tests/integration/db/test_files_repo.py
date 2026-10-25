"""Testy repozytorium `files`/`file2document` na MariaDB (CONTRACT E4-5a §D2, K16 §1)."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.timeutil import from_ms
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import documents as documents_repo
from app.db.repositories import files as repo
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME, TIME_MS, make_document_row, seed_dataset

pytestmark = pytest.mark.db

LATER = TIME_MS + 1000


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def _seed_user(sm: async_sessionmaker[AsyncSession], *, nickname: str = "seed") -> str:
    """Wstawia `users`; zwraca id (e-mail `{id}@example.com`)."""
    user_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :email, :nickname, :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": user_id,
                "email": f"{user_id}@example.com",
                "nickname": nickname,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
    return user_id


def _make_file(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    *,
    tenant_id: str,
    name: str,
    parent_id: str | None = None,
    file_type: str = "folder",
    size: int = 0,
    location: str | None = None,
    source_type: str = "local",
    file_id: str | None = None,
    now_ms: int = TIME_MS,
) -> repo.FileRow:
    """Buduje `FileRow` z domyślnymi wartościami (§D2); daty naive jak po odczycie z DB."""
    date = from_ms(now_ms).replace(tzinfo=None)
    return repo.FileRow(
        id=file_id or uuid.uuid4().hex,
        tenant_id=tenant_id,
        created_by=tenant_id,
        parent_id=parent_id,
        name=name,
        type=file_type,
        size=size,
        location=location,
        source_type=source_type,
        create_time=now_ms,
        create_date=date,
        update_time=now_ms,
        update_date=date,
    )


async def _put(sm: async_sessionmaker[AsyncSession], row: repo.FileRow) -> repo.FileRow:
    """Wstawia wiersz `files` i zwraca go (bez odczytu)."""
    async with transaction(sm) as session:
        await repo.insert(session, row)
    return row


async def _raw(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> list[tuple]:
    """Wykonuje surowy SELECT/UPDATE w transakcji i zwraca wiersze."""
    async with transaction(sm) as session:
        result = await session.execute(text(sql), params)
        return [tuple(row) for row in result.all()] if result.returns_rows else []


async def test_get_root_per_tenant(sm: async_sessionmaker[AsyncSession]) -> None:
    """`get_root`: root wg tenanta; inny tenant / brak wiersza → None (§D1.2)."""
    alice = await _seed_user(sm)
    bob = await _seed_user(sm)
    root = await _put(sm, _make_file(tenant_id=alice, name="/"))
    async with transaction(sm) as session:
        found = await repo.get_root(session, alice)
        other = await repo.get_root(session, bob)
        missing = await repo.get_root(session, uuid.uuid4().hex)
        malformed = await repo.get_root(session, "nie-hex")
    assert found is not None
    assert (found.id, found.parent_id, found.name, found.type) == (root.id, None, "/", "folder")
    assert other is None
    assert missing is None
    assert malformed is None


async def test_insert_and_get_round_trip(sm: async_sessionmaker[AsyncSession]) -> None:
    """`insert` + `get`: wszystkie pola, czasy z `now_ms`, daty z `from_ms` (§D2)."""
    alice = await _seed_user(sm)
    row = await _put(
        sm,
        _make_file(
            tenant_id=alice,
            name="umowa.txt",
            file_type="doc",
            size=1319,
            location="filemanager/" + "f" * 32 + "/original.txt",
        ),
    )
    async with transaction(sm) as session:
        found = await repo.get(session, row.id)
        missing = await repo.get(session, uuid.uuid4().hex)
    assert found is not None
    assert found == row
    expected_date: datetime = from_ms(TIME_MS).replace(tzinfo=None)
    assert (found.create_time, found.update_time) == (TIME_MS, TIME_MS)
    assert (found.create_date, found.update_date) == (expected_date, expected_date)
    assert missing is None


async def test_get_and_get_many_skip_knowledgebase(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`get`/`get_many` nie widzą wierszy `source_type='knowledgebase'` (§D1.1)."""
    alice = await _seed_user(sm)
    visible = await _put(sm, _make_file(tenant_id=alice, name="plik.txt", file_type="doc"))
    hidden = await _put(
        sm,
        _make_file(tenant_id=alice, name="widok.txt", file_type="doc", source_type="knowledgebase"),
    )
    async with transaction(sm) as session:
        assert await repo.get(session, hidden.id) is None
        assert (await repo.get(session, visible.id)) is not None
        many = await repo.get_many(session, [visible.id, hidden.id, uuid.uuid4().hex])
        assert [item.id for item in many] == [visible.id]
        assert await repo.get_many(session, []) == []


async def test_find_child_visible_and_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`find_child` po (tenant, parent, name); ukryty i cudzy nie pasują (§D2)."""
    alice = await _seed_user(sm)
    bob = await _seed_user(sm)
    root = await _put(sm, _make_file(tenant_id=alice, name="/"))
    child = await _put(
        sm, _make_file(tenant_id=alice, name="a.txt", parent_id=root.id, file_type="doc")
    )
    await _put(
        sm,
        _make_file(
            tenant_id=alice,
            name="ukryty.txt",
            parent_id=root.id,
            file_type="doc",
            source_type="knowledgebase",
        ),
    )
    async with transaction(sm) as session:
        found = await repo.find_child(session, alice, root.id, "a.txt")
        assert found is not None and found.id == child.id
        assert await repo.find_child(session, alice, root.id, "ukryty.txt") is None
        assert await repo.find_child(session, alice, root.id, "brak.txt") is None
        assert await repo.find_child(session, bob, root.id, "a.txt") is None


async def test_list_children_keywords_escapes_wildcards(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`list_children`: keywords traktuje `%` i `_` dosłownie (jak `list_page`, §D2)."""
    alice = await _seed_user(sm)
    root = await _put(sm, _make_file(tenant_id=alice, name="/"))
    for name in ("a50%b", "a500b", "beta_x", "betaax"):
        await _put(sm, _make_file(tenant_id=alice, name=name, parent_id=root.id, file_type="doc"))
    async with transaction(sm) as session:
        percent, percent_total = await repo.list_children(
            session,
            root.id,
            alice,
            keywords="50%",
            orderby="name",
            desc=False,
            page=1,
            page_size=30,
        )
        underscore, underscore_total = await repo.list_children(
            session,
            root.id,
            alice,
            keywords="A_X",
            orderby="name",
            desc=False,
            page=1,
            page_size=30,
        )
    assert [item.name for item in percent] == ["a50%b"]
    assert percent_total == 1
    assert [item.name for item in underscore] == ["beta_x"]
    assert underscore_total == 1


async def test_list_children_orderby_whitelist_and_direction(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`list_children`: orderby z białej listy, DESC/ASC, nieznany → create_time (§D2)."""
    alice = await _seed_user(sm)
    root = await _put(sm, _make_file(tenant_id=alice, name="/"))
    await _put(sm, _make_file(tenant_id=alice, name="Gamma", parent_id=root.id, now_ms=3))
    await _put(sm, _make_file(tenant_id=alice, name="alfa", parent_id=root.id, now_ms=1))
    await _put(sm, _make_file(tenant_id=alice, name="Beta", parent_id=root.id, now_ms=2))
    async with transaction(sm) as session:
        by_name, _ = await repo.list_children(
            session,
            root.id,
            alice,
            keywords=None,
            orderby="name",
            desc=False,
            page=1,
            page_size=30,
        )
        desc_name, _ = await repo.list_children(
            session,
            root.id,
            alice,
            keywords=None,
            orderby="name",
            desc=True,
            page=1,
            page_size=30,
        )
        unknown, _ = await repo.list_children(
            session,
            root.id,
            alice,
            keywords=None,
            orderby="id",
            desc=False,
            page=1,
            page_size=30,
        )
    # Kolacja `utf8mb4_uca1400_ai_ci` jest bez rozróżniania wielkości liter: alfa < Beta < Gamma.
    assert [item.name for item in by_name] == ["alfa", "Beta", "Gamma"]
    assert [item.name for item in desc_name] == ["Gamma", "Beta", "alfa"]
    assert [item.create_time for item in unknown] == [1, 2, 3]


async def test_list_children_pagination_total_and_hidden(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`list_children`: LIMIT/OFFSET, total przed stronicowaniem, ukryte poza wynikiem."""
    alice = await _seed_user(sm)
    root = await _put(sm, _make_file(tenant_id=alice, name="/"))
    for ms in (1, 2, 3):
        await _put(sm, _make_file(tenant_id=alice, name=f"W{ms}", parent_id=root.id, now_ms=ms))
    await _put(
        sm,
        _make_file(
            tenant_id=alice,
            name="ukryty",
            parent_id=root.id,
            now_ms=4,
            source_type="knowledgebase",
        ),
    )
    async with transaction(sm) as session:
        first, total = await repo.list_children(
            session,
            root.id,
            alice,
            keywords=None,
            orderby="create_time",
            desc=False,
            page=1,
            page_size=2,
        )
        second, second_total = await repo.list_children(
            session,
            root.id,
            alice,
            keywords=None,
            orderby="create_time",
            desc=False,
            page=2,
            page_size=2,
        )
        everything, _ = await repo.list_children(
            session,
            root.id,
            alice,
            keywords=None,
            orderby="create_time",
            desc=False,
            page=0,
            page_size=0,
        )
    assert [item.create_time for item in first] == [1, 2]
    assert total == 3  # noqa: PLR2004 — trzy widoczne wiersze (ukryty odfiltrowany)
    assert [item.create_time for item in second] == [3]
    assert second_total == 3  # noqa: PLR2004 — total liczony przed stronicowaniem
    assert [item.create_time for item in everything] == [1, 2, 3]


async def test_list_all_children_is_recursive_and_visible(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`list_all_children` schodzi rekurencyjnie i pomija ukryte (§D2)."""
    alice = await _seed_user(sm)
    root = await _put(sm, _make_file(tenant_id=alice, name="/"))
    folder = await _put(sm, _make_file(tenant_id=alice, name="folder", parent_id=root.id))
    subfolder = await _put(sm, _make_file(tenant_id=alice, name="sub", parent_id=folder.id))
    deep = await _put(
        sm, _make_file(tenant_id=alice, name="deep.txt", parent_id=subfolder.id, file_type="doc")
    )
    await _put(
        sm,
        _make_file(
            tenant_id=alice, name="ukryty", parent_id=folder.id, source_type="knowledgebase"
        ),
    )
    outside = await _put(sm, _make_file(tenant_id=alice, name="poza"))
    async with transaction(sm) as session:
        descendants = await repo.list_all_children(session, root.id)
    ids = {item.id for item in descendants}
    assert ids == {folder.id, subfolder.id, deep.id}
    assert outside.id not in ids


async def test_folders_with_child_folder(sm: async_sessionmaker[AsyncSession]) -> None:
    """`folders_with_child_folder` zwraca tylko foldery z widocznym dzieckiem-folderem (§D2)."""
    alice = await _seed_user(sm)
    parent = await _put(sm, _make_file(tenant_id=alice, name="parent"))
    leaf = await _put(sm, _make_file(tenant_id=alice, name="leaf", parent_id=parent.id))
    empty = await _put(sm, _make_file(tenant_id=alice, name="empty"))
    await _put(sm, _make_file(tenant_id=alice, name="plik.txt", parent_id=leaf.id, file_type="doc"))
    await _put(
        sm,
        _make_file(tenant_id=alice, name="ukryty", parent_id=empty.id, source_type="knowledgebase"),
    )
    async with transaction(sm) as session:
        assert await repo.folders_with_child_folder(session, [parent.id, leaf.id, empty.id]) == {
            parent.id
        }
        assert await repo.folders_with_child_folder(session, []) == set()


async def test_set_name_and_set_parent_bump_time(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`set_name`/`set_parent` zmieniają pole i podbijają update_*, nie ruszają create_* (§D2)."""
    alice = await _seed_user(sm)
    root = await _put(sm, _make_file(tenant_id=alice, name="/"))
    target = await _put(sm, _make_file(tenant_id=alice, name="cel", parent_id=root.id))
    row = await _put(
        sm, _make_file(tenant_id=alice, name="stara.txt", parent_id=root.id, file_type="doc")
    )
    async with transaction(sm) as session:
        await repo.set_name(session, row.id, "nowa.txt", LATER)
        renamed = await repo.get(session, row.id)
    assert renamed is not None
    assert renamed.name == "nowa.txt"
    assert renamed.create_time == TIME_MS
    assert renamed.update_time == LATER
    assert renamed.update_date == from_ms(LATER).replace(tzinfo=None)
    async with transaction(sm) as session:
        await repo.set_parent(session, row.id, target.id, LATER)
        moved = await repo.get(session, row.id)
    assert moved is not None and moved.parent_id == target.id


async def test_delete_cascades_links_and_children(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`delete` zwraca rowcount; FK kaskaduje dzieci i wiązania (§D2)."""
    alice = await _seed_user(sm)
    dataset = await seed_dataset(sm)
    folder = await _put(sm, _make_file(tenant_id=alice, name="folder"))
    child = await _put(
        sm, _make_file(tenant_id=alice, name="w.txt", parent_id=folder.id, file_type="doc")
    )
    document = make_document_row(dataset)
    async with transaction(sm) as session:
        await documents_repo.insert(session, document)
        await repo.insert_link(
            session,
            id=uuid.uuid4().hex,
            file_id=child.id,
            document_id=document.id,
            now_ms=TIME_MS,
        )
        assert await repo.list_links(session, child.id) != []
        assert await repo.delete(session, folder.id) == 1
        assert await repo.get(session, folder.id) is None
        assert await repo.get(session, child.id) is None
        assert await repo.list_links(session, child.id) == []
        assert await repo.delete(session, uuid.uuid4().hex) == 0


async def test_insert_link_and_delete_links_by_document(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`insert_link`/`list_links`/`delete_links_by_document` (§D2)."""
    alice = await _seed_user(sm)
    dataset = await seed_dataset(sm)
    first = await _put(sm, _make_file(tenant_id=alice, name="a.txt", file_type="doc"))
    second = await _put(sm, _make_file(tenant_id=alice, name="b.txt", file_type="doc"))
    document = make_document_row(dataset)
    async with transaction(sm) as session:
        await documents_repo.insert(session, document)
        await repo.insert_link(
            session, id="1" * 32, file_id=first.id, document_id=document.id, now_ms=TIME_MS
        )
        await repo.insert_link(
            session, id="2" * 32, file_id=second.id, document_id=document.id, now_ms=LATER
        )
        links = await repo.list_links(session, first.id)
        assert [(link.file_id, link.document_id) for link in links] == [(first.id, document.id)]
        assert await repo.delete_links_by_document(session, document.id) == 2  # noqa: PLR2004
        assert await repo.list_links(session, first.id) == []
        assert await repo.list_links(session, second.id) == []


async def test_kbs_info_three_keys_per_link(sm: async_sessionmaker[AsyncSession]) -> None:
    """`kbs_info` grupuje po pliku; element = {kb_id, kb_name, document_id} (DEC-178, §D2)."""
    dataset_a = await seed_dataset(sm)
    dataset_b = await seed_dataset(sm)
    owner = dataset_a.tenant_id
    first = await _put(sm, _make_file(tenant_id=owner, name="a.txt", file_type="doc"))
    second = await _put(sm, _make_file(tenant_id=owner, name="b.txt", file_type="doc"))
    lonely = await _put(sm, _make_file(tenant_id=owner, name="c.txt", file_type="doc"))
    doc_a1 = make_document_row(dataset_a, name="a1.txt")
    doc_a2 = make_document_row(dataset_a, name="a2.txt")
    doc_b = make_document_row(dataset_b, name="b.txt")
    async with transaction(sm) as session:
        for doc in (doc_a1, doc_a2, doc_b):
            await documents_repo.insert(session, doc)
        await repo.insert_link(
            session, id="1" * 32, file_id=first.id, document_id=doc_a1.id, now_ms=TIME_MS
        )
        await repo.insert_link(
            session, id="2" * 32, file_id=first.id, document_id=doc_a2.id, now_ms=LATER
        )
        await repo.insert_link(
            session, id="3" * 32, file_id=second.id, document_id=doc_b.id, now_ms=TIME_MS
        )
        info = await repo.kbs_info(session, [first.id, second.id, lonely.id])
    assert set(info) == {first.id, second.id}
    assert info[first.id] == [
        {"kb_id": dataset_a.id, "kb_name": dataset_a.name, "document_id": doc_a1.id},
        {"kb_id": dataset_a.id, "kb_name": dataset_a.name, "document_id": doc_a2.id},
    ]
    assert info[second.id] == [
        {"kb_id": dataset_b.id, "kb_name": dataset_b.name, "document_id": doc_b.id}
    ]
    for items in info.values():
        for item in items:
            assert set(item) == {"kb_id", "kb_name", "document_id"}


async def test_kbs_info_empty_input(sm: async_sessionmaker[AsyncSession]) -> None:
    """`kbs_info([])` → `{}` bez SQL (§D2)."""
    async with transaction(sm) as session:
        assert await repo.kbs_info(session, []) == {}


async def test_non_ascii_id_gives_empty_result_not_collation_error(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Id spoza ASCII (np. „żółw" z żądania) → pusty wynik, nie błąd kolacji 1267 (§D2).

    Kolumny `files.id`/`files.parent_id`/`file2document.file_id` mają kolację `ascii_bin`,
    a parametr wiązany jest `utf8mb4_*` — bez ``CAST(… AS BINARY)`` MariaDB rzuca
    „Illegal mix of collations" (odpowiednik `DELETE /files` z takim id).
    """
    alice = await _seed_user(sm)
    parent = await _put(sm, _make_file(tenant_id=alice, name="parent"))
    visible = await _put(sm, _make_file(tenant_id=alice, name="a.txt", file_type="doc"))
    nested = await _put(sm, _make_file(tenant_id=alice, name="dziecko", parent_id=parent.id))
    async with transaction(sm) as session:
        assert await repo.get_many(session, ["żółw"]) == []
        assert [row.id for row in await repo.get_many(session, [visible.id, "żółw"])] == [
            visible.id
        ]
        assert await repo.folders_with_child_folder(session, ["żółw"]) == set()
        assert await repo.folders_with_child_folder(session, [parent.id, "żółw"]) == {parent.id}
        assert await repo.kbs_info(session, ["żółw"]) == {}
    assert nested.parent_id == parent.id


async def test_lock_user_in_transaction(sm: async_sessionmaker[AsyncSession]) -> None:
    """`lock_user` działa w transakcji wywołującego; brak użytkownika nie jest błędem (§D1.2)."""
    alice = await _seed_user(sm)
    async with transaction(sm) as session:
        await repo.lock_user(session, alice)
        assert await repo.get_root(session, alice) is None
    rows = await _raw(sm, "SELECT COUNT(*) FROM users WHERE id = :id", id=alice)
    assert rows == [(1,)]
    async with transaction(sm) as session:
        await repo.lock_user(session, uuid.uuid4().hex)
