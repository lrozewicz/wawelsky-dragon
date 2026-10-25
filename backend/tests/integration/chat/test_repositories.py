"""Testy repozytoriów czatu na prawdziwej MariaDB (brief T3, kontrakt C9)."""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.timeutil import from_ms
from app.db.repositories import chat_datasets as chat_datasets_repo
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories import chat_sessions as chat_sessions_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories.chat_messages import MessageRow
from app.db.repositories.chat_sessions import SessionRow
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from tests.integration.chat.conftest import seed_chat, seed_user
from tests.integration.ingest.conftest import TIME_MS, seed_dataset
from tests.integration.retrieval.conftest import insert_document

pytestmark = pytest.mark.db

_SEQ_PO_DWOCH = 2  # next_seq po wstawieniu dwóch wiadomości (brief T3)


def _chat_row(chat_id: str, tenant_id: str, *, meta_data_filter: dict | None = None) -> ChatRow:
    """Pełny ChatRow do chats.insert; floaty 0.25/0.75 dokładne w FLOAT — porównanie ==."""
    return ChatRow(
        id=chat_id,
        tenant_id=tenant_id,
        created_by=tenant_id,
        name=f"Czat pomocniczy {chat_id[:8]}",  # UNIQUE (tenant_id, name)
        language="Polish",
        llm_id="fake-chat",
        llm_setting={"temperature": 0.5, "max_tokens": 1024},
        prompt_config={"system": "Jesteś asystentem.", "quote": True},
        similarity_threshold=0.25,
        vector_similarity_weight=0.75,
        top_n=8,
        top_k=512,
        rerank_candidates_count=32,
        rerank_id="r" * 32,
        meta_data_filter=meta_data_filter,
        status="1",
    )


def _session_row(session_id: str, chat_id: str, owner_id: str) -> SessionRow:
    """Pełny SessionRow do chat_sessions.insert (kontrakt C9)."""
    return SessionRow(
        id=session_id,
        chat_id=chat_id,
        name="Nowa sesja",
        user_id="user@example.com",
        owner_id=owner_id,
        source="api",
        message_count=1,
        create_time=TIME_MS,
        update_time=TIME_MS,
    )


def _message_row(
    session_id: str,
    seq: int,
    *,
    role: str,
    content: str,
    reference: dict | None = None,
) -> MessageRow:
    """Pełny MessageRow do chat_messages.insert (kontrakt C9)."""
    return MessageRow(
        id=str(uuid.uuid4()),
        session_id=session_id,
        seq=seq,
        role=role,  # type: ignore[arg-type]
        content=content,
        reference=reference,
        prompt_tokens=12 if seq % 2 else None,
        completion_tokens=34 if seq % 2 else None,
        created_at=TIME_MS / 1000 + seq,
        create_time=TIME_MS,
    )


async def test_chat_insert_get_all_fields(sm: async_sessionmaker[AsyncSession]) -> None:
    """insert/get: wszystkie pola ChatRow, JSON-y → dict, meta NULL → None; brak → None (C9)."""
    tenant = await seed_user(sm)
    with_meta = _chat_row(uuid.uuid4().hex, tenant, meta_data_filter={"user": {"name": "Jan"}})
    without_meta = _chat_row(uuid.uuid4().hex, tenant)
    async with transaction(sm) as session:
        await chats_repo.insert(session, with_meta, now_ms=TIME_MS)
        await chats_repo.insert(session, without_meta, now_ms=TIME_MS)
        got_meta = await chats_repo.get(session, with_meta.id)
        got_null = await chats_repo.get(session, without_meta.id)
        missing = await chats_repo.get(session, "e" * 32)
    assert got_meta == with_meta
    assert got_null == without_meta
    assert got_null is not None and got_null.meta_data_filter is None
    assert missing is None


async def test_chat_insert_column_defaults(sm: async_sessionmaker[AsyncSession]) -> None:
    """chats.insert: description='', icon NULL, prompt_type='simple', do_refer='1' (C9)."""
    tenant = await seed_user(sm)
    chat_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await chats_repo.insert(session, _chat_row(chat_id, tenant), now_ms=TIME_MS)
        found = (
            await session.execute(
                text(
                    "SELECT description, icon, prompt_type, do_refer, create_time,"
                    " update_time, create_date, update_date FROM chats WHERE id = :id"
                ),
                {"id": chat_id},
            )
        ).one()
    assert found.description == ""
    assert found.icon is None
    assert found.prompt_type == "simple"
    assert found.do_refer == "1"
    assert found.create_time == TIME_MS
    assert found.update_time == TIME_MS
    naive = from_ms(TIME_MS).replace(tzinfo=None)
    assert found.create_date == naive
    assert found.update_date == naive


async def test_chat_datasets_insert_many_and_list(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """insert_many + list_dataset_ids: kolejność wg ordinal; [] bez błędu i bez SQL (C9)."""
    tenant = await seed_user(sm)
    ds1 = await seed_dataset(sm)
    ds2 = await seed_dataset(sm)
    ds3 = await seed_dataset(sm)
    chat = await seed_chat(sm, tenant, [ds2.id, ds1.id, ds3.id])
    empty = await seed_chat(sm, tenant, [])
    assert chat is not None
    async with transaction(sm) as session:
        assert await chat_datasets_repo.list_dataset_ids(session, chat.id) == [
            ds2.id,
            ds1.id,
            ds3.id,
        ]
        assert await chat_datasets_repo.list_dataset_ids(session, empty.id) == []


async def test_documents_outside(sm: async_sessionmaker[AsyncSession]) -> None:
    """documents_outside: własny → [], obcy → [id], duplikaty → raz, puste wejścia (C9)."""
    tenant = await seed_user(sm)
    ds_chat = await seed_dataset(sm)
    ds_other = await seed_dataset(sm)
    inside_id = await insert_document(sm, ds_chat, name="wewnetrzny.txt")
    outside_id = await insert_document(sm, ds_other, name="obcy.txt")
    await seed_chat(sm, tenant, [ds_chat.id])
    async with transaction(sm) as session:
        assert await chat_datasets_repo.documents_outside(session, [ds_chat.id], [inside_id]) == []
        assert await chat_datasets_repo.documents_outside(session, [ds_chat.id], [outside_id]) == [
            outside_id
        ]
        assert await chat_datasets_repo.documents_outside(
            session, [ds_chat.id], [outside_id, outside_id]
        ) == [outside_id]
        assert await chat_datasets_repo.documents_outside(
            session, [ds_chat.id], [inside_id, outside_id]
        ) == [outside_id]
        assert await chat_datasets_repo.documents_outside(session, [ds_chat.id], []) == []
        assert await chat_datasets_repo.documents_outside(session, [], [inside_id, outside_id]) == [
            inside_id,
            outside_id,
        ]


async def test_session_insert_get_lock_bump(sm: async_sessionmaker[AsyncSession]) -> None:
    """Sesja: insert/get/lock; bump(added=2) → message_count +2 i nowe update_time (C9)."""
    tenant = await seed_user(sm)
    chat = await seed_chat(sm, tenant, [])
    assert chat is not None
    session_id = uuid.uuid4().hex
    row = _session_row(session_id, chat.id, tenant)
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, row)
        got = await chat_sessions_repo.get(session, session_id)
        locked = await chat_sessions_repo.lock(session, session_id)
    assert got == row
    assert locked == row
    async with transaction(sm) as session:
        await chat_sessions_repo.bump(session, session_id, added=2, now_ms=TIME_MS + 5000)
        after = await chat_sessions_repo.get(session, session_id)
    assert after == replace(row, message_count=3, update_time=TIME_MS + 5000)


async def test_session_get_and_lock_missing(sm: async_sessionmaker[AsyncSession]) -> None:
    """get i lock nieistniejącej sesji → None (C9)."""
    async with transaction(sm) as session:
        assert await chat_sessions_repo.get(session, "d" * 32) is None
        assert await chat_sessions_repo.lock(session, "d" * 32) is None


async def test_message_insert_list_order_and_reference(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Wiadomości: insert/list w kolejności seq; reference None i dict (C9)."""
    tenant = await seed_user(sm)
    chat = await seed_chat(sm, tenant, [])
    assert chat is not None
    session_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, _session_row(session_id, chat.id, tenant))
    user_msg = _message_row(session_id, 0, role="user", content="pytanie o umowę")
    assistant_msg = _message_row(
        session_id,
        1,
        role="assistant",
        content="odpowiedź [ID:0]",
        reference={"total": 1, "chunks": [{"id": "c1"}]},
    )
    async with transaction(sm) as session:
        await chat_messages_repo.insert(session, user_msg)
        await chat_messages_repo.insert(session, assistant_msg)
        listed = await chat_messages_repo.list_by_session(session, session_id)
    assert listed == [user_msg, assistant_msg]


async def test_next_seq_and_exists(sm: async_sessionmaker[AsyncSession]) -> None:
    """next_seq: pusta sesja → 0, po dwóch → 2; exists: jest/nie ma (C9)."""
    tenant = await seed_user(sm)
    chat = await seed_chat(sm, tenant, [])
    assert chat is not None
    session_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, _session_row(session_id, chat.id, tenant))
        assert await chat_messages_repo.next_seq(session, session_id) == 0
    first = _message_row(session_id, 0, role="user", content="pierwsze")
    second = _message_row(session_id, 1, role="assistant", content="drugie")
    async with transaction(sm) as session:
        await chat_messages_repo.insert(session, first)
        await chat_messages_repo.insert(session, second)
        assert await chat_messages_repo.next_seq(session, session_id) == _SEQ_PO_DWOCH
        assert await chat_messages_repo.exists(session, first.id) is True
        assert await chat_messages_repo.exists(session, uuid.uuid4().hex) is False


async def test_duplicate_seq_rejected(sm: async_sessionmaker[AsyncSession]) -> None:
    """UNIQUE (session_id, seq): drugi insert tego samego seq → IntegrityError (C9)."""
    tenant = await seed_user(sm)
    chat = await seed_chat(sm, tenant, [])
    assert chat is not None
    session_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(session, _session_row(session_id, chat.id, tenant))
    first = _message_row(session_id, 0, role="user", content="pierwsze")
    async with transaction(sm) as session:
        await chat_messages_repo.insert(session, first)
    duplicate = _message_row(session_id, 0, role="assistant", content="ten sam seq")
    async with transaction(sm) as session:
        with pytest.raises(IntegrityError):
            await chat_messages_repo.insert(session, duplicate)
