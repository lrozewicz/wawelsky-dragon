"""Testy CRUD repozytoriów czatów, sesji i wiadomości na MariaDB (brief T2a, kontrakt C1)."""

import json
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import chat_datasets as chat_datasets_repo
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories import chat_sessions as chat_sessions_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories.chat_datasets import DatasetBrief
from app.db.repositories.chat_messages import MessageRow
from app.db.repositories.chat_sessions import SessionRow
from app.db.repositories.chats import ChatRow
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME_MS, seed_dataset

pytestmark = pytest.mark.db


def _chat_row(chat_id: str, tenant_id: str, name: str, *, now_ms: int = TIME_MS) -> ChatRow:
    """Pełny ChatRow (C1) do chats.insert; czasy w row informacyjnie — insert ustawia z now_ms."""
    return ChatRow(
        id=chat_id,
        tenant_id=tenant_id,
        created_by=tenant_id,
        name=name,  # UNIQUE (tenant_id, name) — wywołujący podaje różne
        language="Polish",
        llm_id="fake-chat",
        llm_setting={"temperature": 0.5},
        prompt_config={"system": "Jesteś asystentem."},
        similarity_threshold=0.25,
        vector_similarity_weight=0.75,
        top_n=8,
        top_k=512,
        rerank_candidates_count=32,
        rerank_id="r" * 32,
        meta_data_filter=None,
        status="1",
        description=f"opis {name}",
        icon=f"ikona-{name}",
        prompt_type="simple",
        do_refer="1",
        create_time=now_ms,
        update_time=now_ms,
    )


async def _insert_chat(
    sm: async_sessionmaker[AsyncSession], row: ChatRow, *, now_ms: int = TIME_MS
) -> ChatRow:
    """Wstawia czat i zwraca chats.get (C1)."""
    async with transaction(sm) as session:
        await chats_repo.insert(session, row, now_ms=now_ms)
        got = await chats_repo.get(session, row.id)
    assert got is not None
    return got


def _session_row(  # noqa: PLR0913 — kształt sygnatury SessionRow
    session_id: str,
    chat_id: str,
    owner_id: str,
    *,
    name: str = "Sesja",
    user_id: str = "user@example.com",
    now_ms: int = TIME_MS,
) -> SessionRow:
    """Pełny SessionRow do chat_sessions.insert (C1)."""
    return SessionRow(
        id=session_id,
        chat_id=chat_id,
        name=name,
        user_id=user_id,
        owner_id=owner_id,
        source="api",
        message_count=1,
        create_time=now_ms,
        update_time=now_ms,
    )


def _message_row(session_id: str, seq: int, *, role: str, content: str) -> MessageRow:
    """Pełny MessageRow do chat_messages.insert (C1)."""
    return MessageRow(
        id=str(uuid.uuid4()),
        session_id=session_id,
        seq=seq,
        role=role,  # type: ignore[arg-type]
        content=content,
        reference=None,
        prompt_tokens=None,
        completion_tokens=None,
        created_at=TIME_MS / 1000 + seq,
        create_time=TIME_MS,
    )


def _brief_of(dataset: DatasetRow) -> DatasetBrief:
    """Oczekiwany DatasetBrief dla datasetu z seed_dataset (status '1', chunk_count 0)."""
    return DatasetBrief(
        id=dataset.id,
        name=dataset.name,
        tenant_id=dataset.tenant_id,
        permission="me",
        chunk_count=0,
        embedding_model=dataset.embedding_model,
        status="1",
    )


async def test_insert_get_defaults_e1_8(sm: async_sessionmaker[AsyncSession]) -> None:
    """E1-8: ChatRow bez nowych pól — get zwraca domyślne pola i create_time = now_ms (C1)."""
    tenant = await seed_user(sm)
    row = ChatRow(
        id=uuid.uuid4().hex,
        tenant_id=tenant,
        created_by=tenant,
        name="Stary czat",
        language="Polish",
        llm_id="fake-chat",
        llm_setting={},
        prompt_config={},
        similarity_threshold=0.2,
        vector_similarity_weight=0.3,
        top_n=6,
        top_k=1024,
        rerank_candidates_count=64,
        rerank_id="",
        meta_data_filter=None,
        status="1",
    )
    async with transaction(sm) as session:
        await chats_repo.insert(session, row, now_ms=TIME_MS)
        got = await chats_repo.get(session, row.id)
    assert got is not None
    assert got.description == ""
    assert got.icon == ""
    assert got.prompt_type == "simple"
    assert got.do_refer == "1"
    assert got.create_time == TIME_MS
    assert got.update_time == TIME_MS
    assert got == row  # czasy wyłączone z == (compare=False wg DEC-030)


async def test_insert_get_new_fields_round_trip(sm: async_sessionmaker[AsyncSession]) -> None:
    """insert/get: description/icon/prompt_type/do_refer z row; icon "" → NULL w bazie (C1)."""
    tenant = await seed_user(sm)
    with_icon = _chat_row(uuid.uuid4().hex, tenant, "Z ikoną")
    empty_icon = replace(
        with_icon, id=uuid.uuid4().hex, name="Bez ikony", description="drugi", icon=""
    )
    async with transaction(sm) as session:
        await chats_repo.insert(session, with_icon, now_ms=TIME_MS)
        await chats_repo.insert(session, empty_icon, now_ms=TIME_MS)
        got = await chats_repo.get(session, with_icon.id)
        got_null_icon = await chats_repo.get(session, empty_icon.id)
        raw = (
            await session.execute(
                text("SELECT icon FROM chats WHERE id = :id"), {"id": empty_icon.id}
            )
        ).scalar_one()
    assert got == with_icon
    assert got_null_icon == empty_icon
    assert raw is None  # icon "" zapisany jako NULL (C1)


async def test_list_page_owner_desc_and_total(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_page: filtr właściciela, create_time DESC, LIMIT, total i nickname właściciela (C1)."""
    owner = await seed_user(sm)
    rows = [
        await _insert_chat(
            sm, _chat_row(uuid.uuid4().hex, owner, f"Czat {ms}", now_ms=ms), now_ms=ms
        )
        for ms in (1, 2, 3)
    ]
    async with transaction(sm) as session:
        page, total = await chats_repo.list_page(
            session,
            owner_ids=frozenset({owner}),
            chat_id=None,
            name=None,
            keywords="",
            orderby="create_time",
            desc=True,
            offset=0,
            limit=2,
        )
    assert [item.chat.id for item in page] == [rows[2].id, rows[1].id]
    assert [item.chat.create_time for item in page] == [3, 2]
    assert total == 3  # noqa: PLR2004 — liczby z przykładu briefu (czaty o czasach 1, 2, 3)
    assert page[0].nickname == "seed"
    assert page[0].avatar is None


async def test_list_page_owner_ids_none_returns_all_owners(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """list_page: owner_ids None — czaty wszystkich właścicieli (C1)."""
    alice = await seed_user(sm)
    bob = await seed_user(sm)
    from_alice = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, alice, "Czat A"))
    from_bob = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, bob, "Czat B"))
    async with transaction(sm) as session:
        page, total = await chats_repo.list_page(
            session,
            owner_ids=None,
            chat_id=None,
            name=None,
            keywords="",
            orderby="create_time",
            desc=False,
            offset=0,
            limit=10,
        )
    assert {item.chat.id for item in page} == {from_alice.id, from_bob.id}
    assert total == 2  # noqa: PLR2004 — dwóch seeded właścicieli (przykład briefu)


async def test_list_page_empty_owner_ids_without_sql(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """list_page: pusty frozenset owner_ids → ([], 0) bez SQL (C1)."""
    async with transaction(sm) as session:
        assert await chats_repo.list_page(
            session,
            owner_ids=frozenset(),
            chat_id=None,
            name=None,
            keywords="",
            orderby="create_time",
            desc=False,
            offset=0,
            limit=5,
        ) == ([], 0)


async def test_list_page_keywords_escape_underscore(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """list_page: keywords „A_X" — podkreślnik dosłownie, trafia tylko beta_x (C1)."""
    owner = await seed_user(sm)
    beta = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "beta_x"))
    await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Alfa"))
    await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Betaax"))
    async with transaction(sm) as session:
        page, total = await chats_repo.list_page(
            session,
            owner_ids=None,
            chat_id=None,
            name=None,
            keywords="A_X",
            orderby="name",
            desc=False,
            offset=0,
            limit=30,
        )
    assert [item.chat.id for item in page] == [beta.id]
    assert total == 1


async def test_list_page_orderby_unknown_raises(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_page: orderby poza {create_time, update_time, name} → ValueError (C1)."""
    async with transaction(sm) as session:
        with pytest.raises(ValueError, match="orderby: id"):
            await chats_repo.list_page(
                session,
                owner_ids=None,
                chat_id=None,
                name=None,
                keywords="",
                orderby="id",
                desc=False,
                offset=0,
                limit=5,
            )


async def test_list_page_limit_zero_and_offset(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_page: limit 0 → wszystkie wiersze bez LIMIT; offset działa przy limit > 0 (C1)."""
    owner = await seed_user(sm)
    for ms in (1, 2, 3):
        await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, f"Czat {ms}"), now_ms=ms)
    async with transaction(sm) as session:
        page, total = await chats_repo.list_page(
            session,
            owner_ids=None,
            chat_id=None,
            name=None,
            keywords="",
            orderby="create_time",
            desc=False,
            offset=7,
            limit=0,
        )
        page_one, total_one = await chats_repo.list_page(
            session,
            owner_ids=None,
            chat_id=None,
            name=None,
            keywords="",
            orderby="create_time",
            desc=False,
            offset=1,
            limit=1,
        )
    assert [item.chat.create_time for item in page] == [1, 2, 3]
    assert total == 3  # noqa: PLR2004 — liczby z przykładu briefu (czaty o czasach 1, 2, 3)
    assert [item.chat.create_time for item in page_one] == [2]
    assert total_one == 3  # noqa: PLR2004 — total nie zależy od LIMIT/OFFSET


async def test_list_page_chat_id_and_name_filters(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_page: chat_id/name — równość; keywords ignorowane gdy podane chat_id (C1)."""
    owner = await seed_user(sm)
    alfa = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Alfa"))
    beta = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Beta"))
    async with transaction(sm) as session:
        by_id, total_id = await chats_repo.list_page(
            session,
            owner_ids=None,
            chat_id=alfa.id,
            name=None,
            keywords="brak-dopasowania",
            orderby="name",
            desc=False,
            offset=0,
            limit=5,
        )
        by_name, total_name = await chats_repo.list_page(
            session,
            owner_ids=None,
            chat_id=None,
            name="Beta",
            keywords="",
            orderby="name",
            desc=False,
            offset=0,
            limit=5,
        )
    assert [item.chat.id for item in by_id] == [alfa.id]
    assert total_id == 1
    assert [item.chat.id for item in by_name] == [beta.id]
    assert total_name == 1


async def test_name_taken_case_insensitive_and_exclude(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """name_taken: kolacja ai_ci — bez rozróżniania wielkości; exclude_id pomija własny (C1)."""
    owner = await seed_user(sm)
    alfa = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Alfa"))
    async with transaction(sm) as session:
        assert await chats_repo.name_taken(session, owner, "ALFA") is True
        assert await chats_repo.name_taken(session, owner, "ALFA", exclude_id=alfa.id) is False
        assert await chats_repo.name_taken(session, owner, "nieobecna") is False


async def test_update_json_icon_and_time(sm: async_sessionmaker[AsyncSession]) -> None:
    """update: dict przez JSON, icon "" → NULL w bazie, update_time = now_ms (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    async with transaction(sm) as session:
        await chats_repo.update(
            session, chat.id, {"llm_setting": {"temperature": 0.5}, "icon": ""}, now_ms=9
        )
        got = await chats_repo.get(session, chat.id)
        raw_icon = (
            await session.execute(text("SELECT icon FROM chats WHERE id = :id"), {"id": chat.id})
        ).scalar_one()
    assert got is not None
    assert got.llm_setting == {"temperature": 0.5}
    assert got.icon == ""
    assert got.update_time == 9  # noqa: PLR2004 — now_ms=9 z przykładu briefu
    assert raw_icon is None


async def test_update_unknown_key_raises(sm: async_sessionmaker[AsyncSession]) -> None:
    """update: klucz spoza UPDATABLE → ValueError (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    async with transaction(sm) as session:
        with pytest.raises(ValueError, match="tenant_id"):
            await chats_repo.update(session, chat.id, {"tenant_id": "x"}, now_ms=1)


async def test_update_empty_fields_bumps_time_only(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """update: puste fields → tylko update_time/update_date, reszta bez zmian (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    async with transaction(sm) as session:
        await chats_repo.update(session, chat.id, {}, now_ms=99)
        got = await chats_repo.get(session, chat.id)
    assert got is not None
    assert got.name == chat.name
    assert got.update_time == 99  # noqa: PLR2004 — now_ms=99 z przykładu briefu


async def test_update_list_value_and_icon(sm: async_sessionmaker[AsyncSession]) -> None:
    """update: list przez JSON, niepusty icon i str zapisane jak są (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    async with transaction(sm) as session:
        await chats_repo.update(
            session,
            chat.id,
            {"meta_data_filter": ["user", "tag"], "icon": "data:image/png", "name": "Zmieniony"},
            now_ms=11,
        )
        got = await chats_repo.get(session, chat.id)
        raw = (
            await session.execute(
                text("SELECT meta_data_filter, icon FROM chats WHERE id = :id"), {"id": chat.id}
            )
        ).one()
    assert got is not None
    assert got.name == "Zmieniony"
    assert got.icon == "data:image/png"
    assert json.loads(raw.meta_data_filter) == ["user", "tag"]
    assert raw.icon == "data:image/png"


async def test_chat_id_outside_ascii_keeps_collation_intact(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """DEC-090 p. H: `get`/`list_page(chat_id=…)`/`delete` z id spoza ASCII nie rzucają 1267.

    `chats.id` ma kolację `ascii_bin`; bez `CAST(:id AS BINARY)` MariaDB wywraca porównanie
    parametrem w `utf8mb4_*` („Illegal mix of collations").
    """
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    foreign_id = "čhat-id"
    async with transaction(sm) as session:
        assert await chats_repo.get(session, foreign_id) is None
        rows, total = await chats_repo.list_page(
            session,
            owner_ids=None,
            chat_id=foreign_id,
            name=None,
            keywords="",
            orderby="create_time",
            desc=True,
            offset=0,
            limit=5,
        )
        assert rows == []
        assert total == 0
        assert await chats_repo.delete(session, foreign_id) is False
        assert await chats_repo.get(session, chat.id) is not None


async def test_delete_cascades_bindings_sessions_messages(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """delete: True raz; kaskada FK czyści chat_datasets/chat_sessions/chat_messages (C1, R3)."""
    owner = await seed_user(sm)
    dataset = await seed_dataset(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    session_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await chat_datasets_repo.insert_many(session, chat.id, [dataset.id])
        await chat_sessions_repo.insert(session, _session_row(session_id, chat.id, owner))
        await chat_messages_repo.insert(
            session, _message_row(session_id, 0, role="user", content="pytanie")
        )
    async with transaction(sm) as session:
        assert await chats_repo.delete(session, chat.id) is True
        assert await chats_repo.delete(session, chat.id) is False
        assert (
            await session.execute(
                text("SELECT COUNT(*) FROM chat_datasets WHERE chat_id = :id"), {"id": chat.id}
            )
        ).scalar_one() == 0
        assert (
            await session.execute(
                text("SELECT COUNT(*) FROM chat_sessions WHERE chat_id = :id"), {"id": chat.id}
            )
        ).scalar_one() == 0
        assert (
            await session.execute(
                text("SELECT COUNT(*) FROM chat_messages WHERE session_id = :id"),
                {"id": session_id},
            )
        ).scalar_one() == 0


async def test_list_ids_by_owner(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_ids_by_owner: id czatów właściciela po (create_time, id); cudze pominięte (C1)."""
    owner = await seed_user(sm)
    other = await seed_user(sm)
    first = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Pierwszy"), now_ms=1)
    second = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Drugi"), now_ms=2)
    foreign = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, other, "Obcy"), now_ms=3)
    async with transaction(sm) as session:
        assert await chats_repo.list_ids_by_owner(session, owner) == [first.id, second.id]
        assert await chats_repo.list_ids_by_owner(session, other) == [foreign.id]


async def test_dataset_briefs_input_order_skips_missing(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """dataset_briefs: kolejność wejścia, brakujące pominięte, [] → [] bez SQL (C1)."""
    d1 = await seed_dataset(sm)
    d2 = await seed_dataset(sm)
    async with transaction(sm) as session:
        assert await chat_datasets_repo.dataset_briefs(session, [d2.id, "f" * 32, d1.id]) == [
            _brief_of(d2),
            _brief_of(d1),
        ]
        assert await chat_datasets_repo.dataset_briefs(session, []) == []


async def test_replace_datasets(sm: async_sessionmaker[AsyncSession]) -> None:
    """replace: DELETE wiązań czatu + insert_many — zostaje tylko nowa lista (C1)."""
    owner = await seed_user(sm)
    d1 = await seed_dataset(sm)
    d2 = await seed_dataset(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    async with transaction(sm) as session:
        await chat_datasets_repo.insert_many(session, chat.id, [d2.id, d1.id])
        await chat_datasets_repo.replace(session, chat.id, [d1.id])
        assert await chat_datasets_repo.list_dataset_ids(session, chat.id) == [d1.id]


async def test_names_by_chat_only_active_datasets(sm: async_sessionmaker[AsyncSession]) -> None:
    """names_by_chat: po ordinal, tylko status '1'; czat bez wiązań — brak klucza; [] → {} (C1)."""
    owner = await seed_user(sm)
    d1 = await seed_dataset(sm)
    d2 = await seed_dataset(sm)
    c1 = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Pierwszy"))
    c2 = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Drugi"))
    async with transaction(sm) as session:
        await chat_datasets_repo.insert_many(session, c1.id, [d1.id, d2.id])
        await session.execute(
            text("UPDATE datasets SET status = '0' WHERE id = :id"), {"id": d2.id}
        )
        names = await chat_datasets_repo.names_by_chat(session, [c1.id, c2.id])
        assert await chat_datasets_repo.names_by_chat(session, []) == {}
    assert names == {c1.id: [(d1.id, d1.name)]}


async def test_sessions_list_page_owner_filter(sm: async_sessionmaker[AsyncSession]) -> None:
    """chat_sessions.list_page: filtr owner_ids — tylko sesje właściciela (C1)."""
    owner = await seed_user(sm)
    other = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    s1 = _session_row(uuid.uuid4().hex, chat.id, owner, name="Pierwsza", now_ms=TIME_MS)
    s2 = _session_row(uuid.uuid4().hex, chat.id, other, name="Druga", now_ms=TIME_MS + 1000)
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, s1)
        await chat_sessions_repo.insert(session, s2)
        page = await chat_sessions_repo.list_page(
            session,
            chat.id,
            owner_ids=frozenset({owner}),
            session_id=None,
            name=None,
            user_id=None,
            orderby="create_time",
            desc=False,
            offset=0,
            limit=30,
        )
    assert page == [s1]


async def test_sessions_list_page_filters(sm: async_sessionmaker[AsyncSession]) -> None:
    """chat_sessions.list_page: owner_ids None/[], filtry session_id/name/user_id (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    s1 = _session_row(
        uuid.uuid4().hex,
        chat.id,
        owner,
        name="Rano",
        user_id="user-a@example.com",
        now_ms=TIME_MS,
    )
    s2 = _session_row(
        uuid.uuid4().hex,
        chat.id,
        owner,
        name="Wieczór",
        user_id="user-b@example.com",
        now_ms=TIME_MS + 1000,
    )
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, s1)
        await chat_sessions_repo.insert(session, s2)
        both = await chat_sessions_repo.list_page(
            session,
            chat.id,
            owner_ids=None,
            session_id=None,
            name=None,
            user_id=None,
            orderby="create_time",
            desc=False,
            offset=0,
            limit=30,
        )
        empty = await chat_sessions_repo.list_page(
            session,
            chat.id,
            owner_ids=frozenset(),
            session_id=None,
            name=None,
            user_id=None,
            orderby="create_time",
            desc=False,
            offset=0,
            limit=30,
        )
        by_id = await chat_sessions_repo.list_page(
            session,
            chat.id,
            owner_ids=None,
            session_id=s2.id,
            name=None,
            user_id=None,
            orderby="create_time",
            desc=False,
            offset=0,
            limit=30,
        )
        by_name = await chat_sessions_repo.list_page(
            session,
            chat.id,
            owner_ids=None,
            session_id=None,
            name="Rano",
            user_id=None,
            orderby="create_time",
            desc=False,
            offset=0,
            limit=30,
        )
        by_user = await chat_sessions_repo.list_page(
            session,
            chat.id,
            owner_ids=None,
            session_id=None,
            name=None,
            user_id="user-b@example.com",
            orderby="create_time",
            desc=False,
            offset=0,
            limit=30,
        )
    assert [s.id for s in both] == [s1.id, s2.id]
    assert empty == []
    assert [s.id for s in by_id] == [s2.id]
    assert [s.id for s in by_name] == [s1.id]
    assert [s.id for s in by_user] == [s2.id]


async def test_sessions_list_page_ordering_and_invalid(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """chat_sessions.list_page: orderby name/update_time, remis po id; złe → ValueError (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    s1 = _session_row(uuid.uuid4().hex, chat.id, owner, name="Alfa", now_ms=TIME_MS)
    s2 = _session_row(uuid.uuid4().hex, chat.id, owner, name="Beta", now_ms=TIME_MS)
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, s2)
        await chat_sessions_repo.insert(session, s1)
        by_name = await chat_sessions_repo.list_page(
            session,
            chat.id,
            owner_ids=None,
            session_id=None,
            name=None,
            user_id=None,
            orderby="name",
            desc=False,
            offset=0,
            limit=30,
        )
        by_update_desc = await chat_sessions_repo.list_page(
            session,
            chat.id,
            owner_ids=None,
            session_id=None,
            name=None,
            user_id=None,
            orderby="update_time",
            desc=True,
            offset=0,
            limit=30,
        )
        with pytest.raises(ValueError, match="orderby: id"):
            await chat_sessions_repo.list_page(
                session,
                chat.id,
                owner_ids=None,
                session_id=None,
                name=None,
                user_id=None,
                orderby="id",
                desc=False,
                offset=0,
                limit=30,
            )
    assert [s.id for s in by_name] == [s1.id, s2.id]
    # remis update_time → id w tym samym kierunku (DESC)
    assert [s.id for s in by_update_desc] == sorted([s1.id, s2.id], reverse=True)


async def test_sessions_list_ids(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_ids: owner_ids None → obie sesje; filtr właściciela; pusty frozenset → [] (C1)."""
    owner = await seed_user(sm)
    other = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    s1 = _session_row(uuid.uuid4().hex, chat.id, owner, now_ms=TIME_MS)
    s2 = _session_row(uuid.uuid4().hex, chat.id, other, now_ms=TIME_MS + 1000)
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, s1)
        await chat_sessions_repo.insert(session, s2)
        assert await chat_sessions_repo.list_ids(session, chat.id, owner_ids=None) == [
            s1.id,
            s2.id,
        ]
        assert await chat_sessions_repo.list_ids(
            session, chat.id, owner_ids=frozenset({other})
        ) == [s2.id]
        assert await chat_sessions_repo.list_ids(session, chat.id, owner_ids=frozenset()) == []


async def test_sessions_rename(sm: async_sessionmaker[AsyncSession]) -> None:
    """rename: nazwa i update_time/update_date zaktualizowane (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    s1 = _session_row(uuid.uuid4().hex, chat.id, owner)
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, s1)
        await chat_sessions_repo.rename(session, s1.id, "nowa", now_ms=5)
        got = await chat_sessions_repo.get(session, s1.id)
    assert got is not None
    assert got.name == "nowa"
    assert got.update_time == 5  # noqa: PLR2004 — now_ms=5 z przykładu briefu


async def test_sessions_delete_cascades_messages(sm: async_sessionmaker[AsyncSession]) -> None:
    """delete sesji: True raz; kaskada FK czyści chat_messages (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    s1 = _session_row(uuid.uuid4().hex, chat.id, owner)
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, s1)
        await chat_messages_repo.insert(
            session, _message_row(s1.id, 0, role="user", content="pytanie")
        )
        assert await chat_sessions_repo.delete(session, s1.id) is True
        assert await chat_sessions_repo.delete(session, s1.id) is False
        assert (
            await session.execute(
                text("SELECT COUNT(*) FROM chat_messages WHERE session_id = :id"), {"id": s1.id}
            )
        ).scalar_one() == 0


async def test_list_by_sessions_groups_by_seq(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_by_sessions: wiadomości po seq; sesja bez wiadomości — brak klucza; [] → {} (C1)."""
    owner = await seed_user(sm)
    chat = await _insert_chat(sm, _chat_row(uuid.uuid4().hex, owner, "Czat"))
    s1 = _session_row(uuid.uuid4().hex, chat.id, owner)
    s2 = _session_row(uuid.uuid4().hex, chat.id, owner)
    m0 = _message_row(s1.id, 0, role="user", content="pierwsze")
    m1 = _message_row(s1.id, 1, role="assistant", content="drugie")
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, s1)
        await chat_sessions_repo.insert(session, s2)
        await chat_messages_repo.insert(session, m0)
        await chat_messages_repo.insert(session, m1)
        grouped = await chat_messages_repo.list_by_sessions(session, [s1.id, s2.id])
        assert await chat_messages_repo.list_by_sessions(session, []) == {}
    assert grouped == {s1.id: [m0, m1]}
