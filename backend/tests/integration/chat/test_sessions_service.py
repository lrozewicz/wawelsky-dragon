"""Testy usługi sesji SessionsService na MariaDB (brief T3a, kontrakt C3, R2, R5, R6, R11)."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories import chat_sessions as chat_sessions_repo
from app.db.repositories.chat_messages import MessageRow
from app.db.repositories.chat_sessions import SessionRow
from app.db.uow import transaction
from app.services.sessions import SessionListQuery, SessionsService
from tests.integration.chat.conftest import TIME_MS, seed_chat, seed_user
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

# Prologue z DEFAULT_PROMPT_CONFIG (merge z pustym prompt_config czatu).
PROLOGUE = "Hi! I'm your assistant. What can I do for you?"


def _svc(container: Container) -> SessionsService:
    """Usługa na kontenerze testowym."""
    return SessionsService(container)


def _query(**over: Any) -> SessionListQuery:
    """Parametry listy: pierwsza strona po create_time malejąco (jak w briefie)."""
    params: dict[str, Any] = {
        "page": 1,
        "page_size": 30,
        "orderby": "create_time",
        "desc": True,
        "session_id": None,
        "name": None,
        "user_id": None,
    }
    params.update(over)
    return SessionListQuery(**params)


async def _set_time(sm: async_sessionmaker[AsyncSession], session_id: str, time_ms: int) -> None:
    """Ustawia create_time/update_time sesji wprost (deterministyczna kolejność listy)."""
    async with transaction(sm) as session:
        await session.execute(
            # Składany SQL: wyłącznie stały fragment SET z tego pliku (S608).
            text("UPDATE chat_sessions SET create_time = :t, update_time = :t WHERE id = :id"),
            {"id": session_id, "t": time_ms},
        )


async def _session_row(sm: async_sessionmaker[AsyncSession], session_id: str) -> SessionRow:
    """Sesja z bazy po id (asercje stanu trwałego)."""
    async with transaction(sm) as session:
        row = await chat_sessions_repo.get(session, session_id)
    assert row is not None
    return row


async def test_create_defaults(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """create: czat z prompt_config={} → prologue domyślny, message_count 1, source api (R5)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    view = await _svc(container).create(principal_for(user), chat.id, "s1")
    assert view.name == "s1"
    assert view.user_id == user
    assert view.chat_id == chat.id
    assert len(view.messages) == 1
    msg = view.messages[0]
    assert msg.seq == 0
    assert msg.role == "assistant"
    assert msg.content == PROLOGUE
    assert msg.reference is None
    assert msg.id
    assert msg.created_at > 0
    row = await _session_row(sm, view.id)
    assert row.message_count == 1
    assert row.source == "api"
    assert row.user_id == user
    assert row.owner_id == user


async def test_create_empty_prologue(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """create: prompt_config z prologue "" → wiadomość seq 0 z pustą treścią istnieje (R5)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={"prologue": ""})
    view = await _svc(container).create(principal_for(user), chat.id, "s1")
    assert len(view.messages) == 1
    assert view.messages[0].content == ""


async def test_create_permissions(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """create: cudzy czat → PermissionDenied; brak czatu → NotFound "Chat not found!" (R2)."""
    user = await seed_user(sm)
    stranger = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    with pytest.raises(PermissionDenied):
        await _svc(container).create(principal_for(stranger), chat.id, "x")
    with pytest.raises(NotFound) as err:
        await _svc(container).create(principal_for(user), "brak", "x")
    assert err.value.message == "Chat not found!"


async def test_ensure_owned_missing_stranger_and_grantee(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """ensure_owned: brak czatu → False; cudzy czat → False; grantobiorca → True (DEC-091 p. 1)."""
    user = await seed_user(sm)
    stranger = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    assert await service.ensure_owned(principal_for(user), "brak") is False
    assert await service.ensure_owned(principal_for(stranger), chat.id) is False
    assert await service.ensure_owned(principal_for(user), chat.id) is True
    access = container.access
    assert access is not None
    await access.grant(principal_for(stranger).email, chat.id, None)
    assert await service.ensure_owned(principal_for(stranger), chat.id) is True


async def test_list_paging(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """list: 3 sesje, strona 2-elementowa desc → 2 najnowsze, każda z prologiem (C3 list)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    first = await service.create(principal_for(user), chat.id, "s1")
    second = await service.create(principal_for(user), chat.id, "s2")
    third = await service.create(principal_for(user), chat.id, "s3")
    await _set_time(sm, first.id, 1000)
    await _set_time(sm, second.id, 2000)
    await _set_time(sm, third.id, 3000)
    views = await service.list(
        principal_for(user),
        chat.id,
        _query(page=1, page_size=2),
    )
    assert [v.id for v in views] == [third.id, second.id]
    assert [v.name for v in views] == ["s3", "s2"]
    for view in views:
        assert len(view.messages) == 1
        assert view.messages[0].content == PROLOGUE


async def test_list_zero_page_size(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """list: page_size 0 → [] bez zapytania o sesje (Q25)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    views = await _svc(container).list(principal_for(user), chat.id, _query(page_size=0))
    assert views == []


async def test_list_name_filter(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """list: filtr name → tylko sesja o tej nazwie (C3 list)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    target = await service.create(principal_for(user), chat.id, "s1")
    await service.create(principal_for(user), chat.id, "s2")
    views = await service.list(principal_for(user), chat.id, _query(name="s1"))
    assert [v.id for v in views] == [target.id]


async def test_list_visibility(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """list: właściciel widzi tylko swoje sesje, superuser wszystkie (R6)."""
    user = await seed_user(sm)
    other = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    own = await service.create(principal_for(user), chat.id, "wlasna")
    foreign_id = container.id_gen.new_id()
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(
            session,
            SessionRow(
                id=foreign_id,
                chat_id=chat.id,
                name="obca",
                user_id=other,
                owner_id=other,
                source="api",
                message_count=1,
                create_time=2000,
                update_time=2000,
            ),
        )
    views = await service.list(principal_for(user), chat.id, _query())
    assert [v.id for v in views] == [own.id]
    all_views = await service.list(principal_for(user, superuser=True), chat.id, _query())
    assert {v.id for v in all_views} == {own.id, foreign_id}


async def test_list_foreign_chat_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """list: cudzy czat → PermissionDenied (wykrywa łatkę session-list-scope)."""
    user = await seed_user(sm)
    stranger = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    with pytest.raises(PermissionDenied):
        await _svc(container).list(principal_for(stranger), chat.id, _query())


async def test_get_errors(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """get: brak sesji → NotFound; sesja innego czatu → Conflict (C3 get, C8)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    other_chat = await seed_chat(sm, user, [], prompt_config={})
    elsewhere = await _svc(container).create(principal_for(user), other_chat.id, "gdzies")
    with pytest.raises(NotFound) as err:
        await _svc(container).get(principal_for(user), chat.id, "brak")
    assert err.value.message == "Session not found!"
    with pytest.raises(Conflict) as err:
        await _svc(container).get(principal_for(user), chat.id, elsewhere.id)
    assert err.value.message == "Session does not belong to this chat!"


async def test_get_avatar(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """get: czat bez ikony → avatar "" (C3 get)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    view = await _svc(container).create(principal_for(user), chat.id, "s1")
    detail = await _svc(container).get(principal_for(user), chat.id, view.id)
    assert detail.avatar == ""


async def test_rename(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """rename: nowa nazwa; name None → bez zmian; sesja innego czatu → NotFound (C3 rename)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    other_chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    view = await service.create(principal_for(user), chat.id, "stara")
    elsewhere = await service.create(principal_for(user), other_chat.id, "gdzies")
    renamed = await service.rename(principal_for(user), chat.id, view.id, "nowa")
    assert renamed.name == "nowa"
    unchanged = await service.rename(principal_for(user), chat.id, view.id, None)
    assert unchanged.name == "nowa"
    with pytest.raises(NotFound) as err:
        await service.rename(principal_for(user), chat.id, elsewhere.id, "x")
    assert err.value.message == "Session not found!"


async def test_delete_many_mixed(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete_many: duplikaty i obcy id → sukces częściowy, błędy id przed duplikatami (C8)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    view = await _svc(container).create(principal_for(user), chat.id, "s1")
    result = await _svc(container).delete_many(
        principal_for(user), chat.id, [view.id, "brak", view.id], False
    )
    assert result.success_count == 1
    assert result.errors == [
        "The chat doesn't own the session brak",
        f"Duplicate session ids: {view.id}",
    ]
    assert result.nothing is False


async def test_delete_many_all_fail(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete_many: 0 sukcesów i błędy → NotFound z komunikatami po średniku (C8)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    with pytest.raises(NotFound) as err:
        await _svc(container).delete_many(principal_for(user), chat.id, ["brak"], False)
    assert err.value.message == "The chat doesn't own the session brak"


async def test_delete_many_all(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """delete_many: delete_all usuwa sesje właściciela; bez ids i bez delete_all → nothing (C3)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    principal = principal_for(user)
    names = ["s1", "s2"]
    for name in names:
        await service.create(principal, chat.id, name)
    result = await service.delete_many(principal, chat.id, None, True)
    assert result.success_count == len(names)
    assert await service.list(principal, chat.id, _query()) == []
    again = await service.delete_many(principal, chat.id, None, True)
    assert again.nothing is True
    without_all = await service.delete_many(principal, chat.id, None, False)
    assert without_all.nothing is True


# Prologue + para user/assistant (asercje bez liczb w kodzie — PLR2004).
_PROLOGUE_AND_PAIR = 3


async def _seed_pair(sm: async_sessionmaker[AsyncSession], session_id: str) -> str:
    """Wstawia parę user(seq 1)+assistant(seq 2) do sesji; zwraca id pary (asystenta)."""
    async with transaction(sm) as session:
        for seq, role, message_id in ((1, "user", "u" * 32), (2, "assistant", "a" * 32)):
            await chat_messages_repo.insert(
                session,
                MessageRow(
                    id=message_id,
                    session_id=session_id,
                    seq=seq,
                    role=role,  # type: ignore[arg-type]
                    content=f"treść {role}",
                    reference={"chunks": [{"id": "c1"}], "doc_aggs": []},
                    prompt_tokens=None,
                    completion_tokens=None,
                    created_at=1.0 + seq,
                    create_time=TIME_MS,
                ),
            )
        await chat_sessions_repo.bump(session, session_id, added=2, now_ms=TIME_MS)
    return "a" * 32


async def test_delete_message_removes_pair(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete_message: para user+assistant znika, reference [] i licznik minus 2 (E2-1 CHAT)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    principal = principal_for(user)
    created = await service.create(principal, chat.id, "s1")
    pair_id = await _seed_pair(sm, created.id)
    before = await service.get(principal, chat.id, created.id)
    assert [message.id for message in before.messages] == [created.messages[0].id, pair_id, pair_id]
    after = await service.delete_message(principal, chat.id, created.id, pair_id)
    assert [message.role for message in after.messages] == ["assistant"]
    assert after.messages[0].id == created.messages[0].id
    assert (await _session_row(sm, created.id)).message_count == 1


async def test_delete_message_missing_is_noop(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete_message: id spoza sesji → brak zmian, koperta sesji (chat_api.py:1008)."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    principal = principal_for(user)
    created = await service.create(principal, chat.id, "s1")
    pair_id = await _seed_pair(sm, created.id)
    same = await service.delete_message(principal, chat.id, created.id, "nie-ma")
    assert len(same.messages) == _PROLOGUE_AND_PAIR
    assert (await _session_row(sm, created.id)).message_count == _PROLOGUE_AND_PAIR
    assert [message.id for message in same.messages][1:] == [pair_id, pair_id]


async def test_message_feedback_up_down_and_clear(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """set_message_feedback: up czyści feedback, down zapisuje, brak trafienia → bez zmian."""
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    service = _svc(container)
    principal = principal_for(user)
    created = await service.create(principal, chat.id, "s1")
    pair_id = await _seed_pair(sm, created.id)
    up = await service.set_message_feedback(
        principal, chat.id, created.id, pair_id, thumbup=True, feedback="wd_rec thumbup"
    )
    assert up.messages[2].thumbup is True
    assert up.messages[2].feedback is None
    down = await service.set_message_feedback(
        principal, chat.id, created.id, pair_id, thumbup=False, feedback="nie tak"
    )
    assert down.messages[2].thumbup is False
    assert down.messages[2].feedback == "nie tak"
    again = await service.set_message_feedback(
        principal, chat.id, created.id, pair_id, thumbup=True, feedback=None
    )
    assert again.messages[2].thumbup is True
    assert again.messages[2].feedback is None
    untouched = await service.set_message_feedback(
        principal, chat.id, created.id, "nie-ma", thumbup=True, feedback=None
    )
    assert untouched.messages[2].thumbup is True


async def test_message_ops_foreign_session_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudza sesja (właściciel inny niż czatu) → PermissionDenied, para nietknięta (R2).

    Cel łatki ``e2-1-msg-delete-foreign.patch`` (usuwa ``require(UPDATE, session)``).
    """
    user = await seed_user(sm)
    chat = await seed_chat(sm, user, [], prompt_config={})
    other = await seed_user(sm)
    foreign_session = "f" * 32
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(
            session,
            SessionRow(
                id=foreign_session,
                chat_id=chat.id,
                name="sesja obca",
                user_id=f"{other}@example.com",
                owner_id=other,
                source="api",
                message_count=2,
                create_time=TIME_MS,
                update_time=TIME_MS,
            ),
        )
    pair_id = await _seed_pair(sm, foreign_session)
    service = _svc(container)
    principal = principal_for(user)
    with pytest.raises(PermissionDenied):
        await service.delete_message(principal, chat.id, foreign_session, pair_id)
    with pytest.raises(PermissionDenied):
        await service.set_message_feedback(
            principal, chat.id, foreign_session, pair_id, thumbup=True, feedback=None
        )
    async with transaction(sm) as session:
        rows = await chat_messages_repo.list_by_session(session, foreign_session)
    assert [row.role for row in rows] == ["user", "assistant"]
