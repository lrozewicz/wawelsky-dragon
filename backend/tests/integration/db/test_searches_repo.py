"""Testy repozytorium `searches`/`search_datasets` na MariaDB (CONTRACT E4-4a §D3, K15 §1)."""

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
from app.db.repositories import searches as repo
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME, TIME_MS, seed_dataset

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


async def _insert_search(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    sm: async_sessionmaker[AsyncSession],
    owner: str,
    name: str,
    *,
    search_id: str | None = None,
    description: str | None = None,
    avatar: str | None = None,
    search_config: dict | None = None,
    now_ms: int = TIME_MS,
) -> repo.SearchRow:
    """Wstawia wyszukiwarkę i zwraca `searchs.get` (§D3)."""
    search_id = search_id or uuid.uuid4().hex
    config = {"chat_id": ""} if search_config is None else search_config
    async with transaction(sm) as session:
        await repo.insert(
            session,
            id=search_id,
            tenant_id=owner,
            name=name,
            description=description,
            avatar=avatar,
            search_config=config,
            now_ms=now_ms,
        )
        row = await repo.get(session, search_id)
    assert row is not None
    return row


async def _raw(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> list[tuple]:
    """Wykonuje surowy SELECT/UPDATE w transakcji i zwraca wiersze."""
    async with transaction(sm) as session:
        result = await session.execute(text(sql), params)
        return [tuple(row) for row in result.all()] if result.returns_rows else []


async def test_insert_and_get_round_trip(sm: async_sessionmaker[AsyncSession]) -> None:
    """`insert` + `get`: pola, status '1', czasy z `now_ms`, daty z `from_ms` (§D3)."""
    owner = await _seed_user(sm)
    config = {"doc_ids": ["d" * 32], "top_k": 8, "chat_id": "c" * 32}
    row = await _insert_search(
        sm,
        owner,
        "Wyszukiwarka",
        description="opis",
        avatar="ikona",
        search_config=config,
    )
    assert (row.tenant_id, row.created_by, row.name) == (owner, owner, "Wyszukiwarka")
    assert row.status == "1"
    assert row.search_config == config
    assert (row.description, row.avatar) == ("opis", "ikona")
    assert (row.create_time, row.update_time) == (TIME_MS, TIME_MS)
    expected_date: datetime = from_ms(TIME_MS).replace(tzinfo=None)
    assert row.create_date == expected_date
    assert row.update_date == expected_date
    async with transaction(sm) as session:
        assert await repo.get(session, uuid.uuid4().hex) is None


async def test_insert_null_description_and_avatar(sm: async_sessionmaker[AsyncSession]) -> None:
    """`description`/`avatar` NULL zostają None (kolumny TEXT/MEDIUMTEXT, §D3)."""
    owner = await _seed_user(sm)
    row = await _insert_search(sm, owner, "Bez opisu")
    assert (row.description, row.avatar) == (None, None)


async def test_get_skips_inactive(sm: async_sessionmaker[AsyncSession]) -> None:
    """`get` filtruje `status='1'` — po przełączeniu na '0' zwraca None (§D3)."""
    owner = await _seed_user(sm)
    row = await _insert_search(sm, owner, "Wyłączona")
    await _raw(sm, "UPDATE searches SET status = '0' WHERE id = :id", id=row.id)
    async with transaction(sm) as session:
        assert await repo.get(session, row.id) is None


async def test_get_owned_other_user_is_none(sm: async_sessionmaker[AsyncSession]) -> None:
    """`get_owned` cudzej wyszukiwarki → None; własnej → wiersz (§D3)."""
    owner = await _seed_user(sm)
    row = await _insert_search(sm, owner, "Moja")
    async with transaction(sm) as session:
        assert await repo.get_owned(session, row.id, "x" * 32) is None
        assert await repo.get_owned(session, row.id, "inny_user") is None
        mine = await repo.get_owned(session, row.id, owner)
    assert mine is not None and mine.id == row.id


async def test_name_taken_case_insensitive_and_exclude(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`name_taken`: bez rozróżniania wielkości, zakres tenant, `exclude_id` pomija własny (§D3)."""
    owner = await _seed_user(sm)
    other = await _seed_user(sm)
    row = await _insert_search(sm, owner, "abc")
    await _insert_search(sm, other, "abc")  # inny tenant — nie koliduje
    async with transaction(sm) as session:
        assert await repo.name_taken(session, owner, "ABC") is True
        assert await repo.name_taken(session, owner, "abc") is True
        assert await repo.name_taken(session, owner, "ab") is False
        assert await repo.name_taken(session, owner, "ABC", exclude_id=row.id) is False
        assert await repo.name_taken(session, owner, "Abc", exclude_id=other) is True
        assert await repo.name_taken(session, other, "ABC") is True
        assert await repo.name_taken(session, other, "zzz") is False


async def test_name_taken_skips_inactive(sm: async_sessionmaker[AsyncSession]) -> None:
    """`name_taken` patrzy tylko na `status='1'` (§D3)."""
    owner = await _seed_user(sm)
    row = await _insert_search(sm, owner, "zajeta")
    await _raw(sm, "UPDATE searches SET status = '0' WHERE id = :id", id=row.id)
    async with transaction(sm) as session:
        assert await repo.name_taken(session, owner, "zajeta") is False


async def test_update_changes_fields_and_time(sm: async_sessionmaker[AsyncSession]) -> None:
    """`update` podmienia pola i podbija update_*, nie rusza create_time (§D3)."""
    owner = await _seed_user(sm)
    row = await _insert_search(sm, owner, "Stara", description="stary", avatar="a")
    config = {"top_k": 4, "chat_id": "c" * 32}
    async with transaction(sm) as session:
        await repo.update(
            session,
            row.id,
            name="Nowa",
            description="nowy",
            avatar=None,
            search_config=config,
            now_ms=LATER,
        )
        updated = await repo.get(session, row.id)
    assert updated is not None
    assert updated.name == "Nowa"
    assert (updated.description, updated.avatar) == ("nowy", None)
    assert updated.search_config == config
    assert updated.create_time == TIME_MS
    assert updated.update_time == LATER
    assert updated.update_date == from_ms(LATER).replace(tzinfo=None)


async def test_update_unknown_id_is_noop(sm: async_sessionmaker[AsyncSession]) -> None:
    """`update` nieznanego id nie tworzy wiersza (§D3)."""
    owner = await _seed_user(sm)
    async with transaction(sm) as session:
        await repo.update(
            session,
            "f" * 32,
            name="X",
            description=None,
            avatar=None,
            search_config={},
            now_ms=LATER,
        )
    rows = await _raw(sm, "SELECT COUNT(*) FROM searches")
    assert rows == [(0,)]
    assert owner  # właściciel istnieje, ale wyszukiwarki nie ma


async def test_delete_returns_rowcount_and_cascades_bindings(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`delete` zwraca rowcount; kaskada FK czyści `search_datasets` (§D3)."""
    dataset = await seed_dataset(sm)
    owner = dataset.tenant_id
    first = await _insert_search(sm, owner, "Pierwsza")
    second = await _insert_search(sm, owner, "Druga")
    async with transaction(sm) as session:
        await repo.set_dataset_ids(session, first.id, [dataset.id])
        assert await repo.delete(session, first.id) == 1
        assert await repo.list_dataset_ids(session, first.id) == []
        assert await repo.get(session, first.id) is None
        assert await repo.delete(session, uuid.uuid4().hex) == 0
        assert await repo.get(session, second.id) is not None
        assert await repo.delete(session, second.id) == 1


async def test_set_dataset_ids_replaces_and_keeps_order(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`set_dataset_ids` zamienia zestaw i zachowuje kolejność wejścia (`ordinal`, §D3)."""
    dataset_a = await seed_dataset(sm)
    dataset_b = await seed_dataset(sm)
    row = await _insert_search(sm, dataset_a.tenant_id, "W1")
    async with transaction(sm) as session:
        await repo.set_dataset_ids(session, row.id, [dataset_b.id, dataset_a.id])
        assert await repo.list_dataset_ids(session, row.id) == [dataset_b.id, dataset_a.id]
        await repo.set_dataset_ids(session, row.id, [dataset_a.id])
        assert await repo.list_dataset_ids(session, row.id) == [dataset_a.id]
        await repo.set_dataset_ids(session, row.id, [])
        assert await repo.list_dataset_ids(session, row.id) == []


async def test_list_dataset_ids_many_groups_and_orders(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`list_dataset_ids_many`: grupowanie po search_id, porządek ordinal, puste pominięte."""
    dataset_a = await seed_dataset(sm)
    dataset_b = await seed_dataset(sm)
    owner = dataset_a.tenant_id
    first = await _insert_search(sm, owner, "S1")
    second = await _insert_search(sm, owner, "S2")
    third = await _insert_search(sm, owner, "S3")
    async with transaction(sm) as session:
        await repo.set_dataset_ids(session, first.id, [dataset_b.id, dataset_a.id])
        await repo.set_dataset_ids(session, second.id, [dataset_a.id])
        bindings = await repo.list_dataset_ids_many(session, [first.id, second.id, third.id])
        assert bindings == {
            first.id: [dataset_b.id, dataset_a.id],
            second.id: [dataset_a.id],
        }
        assert await repo.list_dataset_ids_many(session, []) == {}


async def test_list_page_filters_order_total_and_owner_data(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`list_page`: zakres tenanta, keywords, orderby, paginacja, total, nickname/avatar (§D3)."""
    alice = await _seed_user(sm, nickname="Ala")
    bob = await _seed_user(sm, nickname="Bob")
    await _insert_search(sm, alice, "Gamma", now_ms=3)
    await _insert_search(sm, alice, "alfa", now_ms=1)
    await _insert_search(sm, alice, "Beta", now_ms=2)
    await _insert_search(sm, bob, "Obcy", now_ms=4)
    async with transaction(sm) as session:
        page, total = await repo.list_page(
            session, alice, keywords="", orderby="create_time", desc=True, page=1, page_size=2
        )
        assert [item.row.name for item in page] == ["Gamma", "Beta"]
        assert [item.row.create_time for item in page] == [3, 2]
        assert total == 3  # noqa: PLR2004 — trzy wyszukiwarki Ali (obca odfiltrowana)
        assert page[0].nickname == "Ala"
        assert page[0].tenant_avatar is None

        by_name, _ = await repo.list_page(
            session, alice, keywords="", orderby="name", desc=False, page=1, page_size=30
        )
        assert [item.row.name for item in by_name] == ["alfa", "Beta", "Gamma"]

        desc_name, _ = await repo.list_page(
            session, alice, keywords="", orderby="name", desc=True, page=1, page_size=30
        )
        assert [item.row.name for item in desc_name] == ["Gamma", "Beta", "alfa"]

        keyword_page, keyword_total = await repo.list_page(
            session, alice, keywords="AL", orderby="create_time", desc=False, page=1, page_size=30
        )
        assert [item.row.name for item in keyword_page] == ["alfa"]
        assert keyword_total == 1

        unknown_orderby, _ = await repo.list_page(
            session, alice, keywords="", orderby="id", desc=False, page=1, page_size=30
        )
        assert [item.row.name for item in unknown_orderby] == ["alfa", "Beta", "Gamma"]


async def test_list_page_keywords_escapes_underscore(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`list_page`: podkreślnik w keywords traktowany dosłownie (§D3)."""
    owner = await _seed_user(sm)
    await _insert_search(sm, owner, "Betaax")
    await _insert_search(sm, owner, "beta_x")
    async with transaction(sm) as session:
        page, total = await repo.list_page(
            session, owner, keywords="A_X", orderby="name", desc=False, page=1, page_size=30
        )
    assert [item.row.name for item in page] == ["beta_x"]
    assert total == 1


async def test_list_page_nonpositive_page_has_no_limit(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`list_page`: page<=0 lub page_size<=0 → bez LIMIT/OFFSET; total nie zależy od strony."""
    owner = await _seed_user(sm)
    for ms in (1, 2, 3):
        await _insert_search(sm, owner, f"W{ms}", now_ms=ms)
    async with transaction(sm) as session:
        all_rows, total = await repo.list_page(
            session, owner, keywords="", orderby="create_time", desc=False, page=0, page_size=30
        )
        assert [item.row.create_time for item in all_rows] == [1, 2, 3]
        assert total == 3  # noqa: PLR2004 — trzy wiersze z pętli
        zero_size, _ = await repo.list_page(
            session, owner, keywords="", orderby="create_time", desc=False, page=1, page_size=0
        )
        assert [item.row.create_time for item in zero_size] == [1, 2, 3]
        first_only, first_total = await repo.list_page(
            session, owner, keywords="", orderby="create_time", desc=False, page=2, page_size=1
        )
    assert [item.row.create_time for item in first_only] == [2]
    assert first_total == 3  # noqa: PLR2004 — total liczony osobno od strony
