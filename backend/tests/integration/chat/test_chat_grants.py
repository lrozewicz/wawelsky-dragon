"""Testy integracyjne grantów czatu (brief T3, kontrakt C6) na MariaDB + fake-llm.

Grant (`assistant_access`) daje READ+USE czatu: grantobiorca widzi czat na liście,
otwiera go, tworzy sesje i rozmawia — bez prawa UPDATE/DELETE i bez dostępu do datasetu.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.errors import NotFound, PermissionDenied
from app.domain.chat.events import AnswerDelta
from app.services.chat import CompletionRequest
from app.services.chats import ChatInput, ChatListQuery, ChatsService
from app.services.sessions import SessionListQuery, SessionsService
from tests.integration.chat.conftest import chat_with_doc, collect, seed_user
from tests.integration.retrieval.conftest import principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

# Dokument o smoku wawelskim; pytanie zawiera jego słowa (tryb termowy, w=0.0).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_QUESTION = "Gdzie mieszkał smok wawelski?"


def _chats(container: Container) -> ChatsService:
    """Usługa czatów na kontenerze testowym."""
    return ChatsService(container)


def _sessions(container: Container) -> SessionsService:
    """Usługa sesji na kontenerze testowym."""
    return SessionsService(container)


def _chat_query() -> ChatListQuery:
    """Pierwsza strona listy czatów po create_time malejąco (jak w briefie T3)."""
    return ChatListQuery(
        page=1,
        page_size=30,
        orderby="create_time",
        desc=True,
        chat_id=None,
        name=None,
        keywords="",
    )


def _session_query() -> SessionListQuery:
    """Pierwsza strona listy sesji po create_time malejąco."""
    return SessionListQuery(
        page=1,
        page_size=30,
        orderby="create_time",
        desc=True,
        session_id=None,
        name=None,
        user_id=None,
    )


async def _grant(container: Container, email: str, chat_id: str) -> None:
    """Nadaje grant e-mailowi przez AccessService kontenera."""
    access = container.access
    assert access is not None
    await access.grant(email, chat_id, None)


async def _revoke(container: Container, email: str, chat_id: str) -> None:
    """Odbiera grant e-mailowi przez AccessService kontenera."""
    access = container.access
    assert access is not None
    await access.revoke(email, chat_id)


async def _seed_foreign_chat(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> tuple[str, str]:
    """Czat użytkownika A (bez datasetów); zwraca (id czatu, id właściciela)."""
    owner = await seed_user(sm)
    chat = await _chats(container).create(
        principal_for(owner), ChatInput({"name": "grant", "dataset_ids": []})
    )
    return chat.id, owner


async def test_no_grant_denies_get_and_list(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """B bez grantu: `get` → PermissionDenied, lista nie zawiera czatu A (przykład briefu)."""
    chat_id, _owner = await _seed_foreign_chat(container, sm)
    viewer = principal_for(await seed_user(sm))
    with pytest.raises(PermissionDenied):
        await _chats(container).get(viewer, chat_id)
    views, total = await _chats(container).list(viewer, _chat_query())
    assert views == []
    assert total == 0


async def test_grant_allows_read_use_and_denies_update_delete(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Po grancie B widzi czat, otwiera go i tworzy sesję; UPDATE/DELETE wciąż odmawiane (C6)."""
    chat_id, _owner = await _seed_foreign_chat(container, sm)
    viewer = principal_for(await seed_user(sm))
    await _grant(container, viewer.email, chat_id)
    views, total = await _chats(container).list(viewer, _chat_query())
    assert [view.id for view in views] == [chat_id]
    assert total == 1
    assert (await _chats(container).get(viewer, chat_id)).id == chat_id
    session = await _sessions(container).create(viewer, chat_id, "moja")
    assert session.user_id == viewer.user_id
    with pytest.raises(PermissionDenied):
        await _chats(container).update(viewer, chat_id, ChatInput({"name": "x"}), merge=False)
    with pytest.raises(PermissionDenied):
        await _chats(container).delete(viewer, chat_id)
    assert await _chats(container).ensure_owned(viewer, chat_id) is False
    with pytest.raises(NotFound) as err:
        await _chats(container).delete_many(viewer, [chat_id], False)
    assert err.value.message == f"Chat({chat_id}) not found."


async def test_grant_session_list_is_own_only(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Sesje grantobiorcy: widzi tylko własne, sesja właściciela czatu jest poza listą (C6)."""
    chat_id, owner = await _seed_foreign_chat(container, sm)
    await _sessions(container).create(principal_for(owner), chat_id, "właściciela")
    viewer = principal_for(await seed_user(sm))
    await _grant(container, viewer.email, chat_id)
    mine = await _sessions(container).create(viewer, chat_id, "moja")
    listed = await _sessions(container).list(viewer, chat_id, _session_query())
    assert [session.id for session in listed] == [mine.id]


async def test_grant_completion_retrieves_without_dataset_access(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Completion grantobiorcy działa i retrievuje przez czat mimo braku dostępu do datasetu."""
    owner = await seed_user(sm)
    chat, dataset, _doc = await chat_with_doc(container, sm, _DOC, owner=owner)
    viewer = principal_for(await seed_user(sm))
    await _grant(container, viewer.email, chat.id)
    # dataset ma permission="me" i innego właściciela — B nie ma do niego bezpośredniego dostępu.
    assert dataset.tenant_id != viewer.user_id
    request = CompletionRequest(
        chat_id=chat.id,
        session_id=None,
        messages=({"role": "user", "content": _QUESTION},),
    )
    events = await collect(await container.chat.start(viewer, request))
    deltas = [event for event in events if isinstance(event, AnswerDelta)]
    answer = "".join(delta.text for delta in deltas)
    assert answer.startswith("Na podstawie źródeł: ")
    assert "[ID:0]" in answer


async def test_revoke_hides_chat(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Po `revoke` widoczność czatu znika (lista wraca do pustej) (C6)."""
    chat_id, _owner = await _seed_foreign_chat(container, sm)
    viewer = principal_for(await seed_user(sm))
    await _grant(container, viewer.email, chat_id)
    views, total = await _chats(container).list(viewer, _chat_query())
    assert [view.id for view in views] == [chat_id]
    assert total == 1
    await _revoke(container, viewer.email, chat_id)
    views, total = await _chats(container).list(viewer, _chat_query())
    assert views == []
    assert total == 0
