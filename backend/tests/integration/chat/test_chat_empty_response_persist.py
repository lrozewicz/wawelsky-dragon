"""Test T1 (WP E5-H6e, kontrakt C1): empty_response trafia do sesji i przeżywa F5.

K4 §3.4: `save_progress` zapisuje wiadomość asystenta z `answer`; ścieżka `empty_response`
(§1.4) zapisywała `""` — usterka. Po poprawce `content` asystenta == `html.escape(empty_response)`.
"""

import html

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.uow import transaction
from app.domain.chat.events import Final
from app.services.chat import CompletionRequest
from tests.integration.chat.conftest import chat_with_doc, collect
from tests.integration.retrieval.conftest import principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

# Dokument o smoku; pytanie bez pokrycia termowego → retrieval zwraca 0 chunków (tryb termowy).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_NO_HITS_QUESTION = "Prognoza pogody na weekend w górach?"
# Znaki specjalne w tekście: zapisany content ma być html-escaped (K4 §1.4, E = html.escape(...)).
_EMPTY_RESPONSE = "Brak <danych> & informacji"


def _req(chat_id: str, question: str) -> CompletionRequest:
    """CompletionRequest jednego pytania user (K4 §3.3)."""
    return CompletionRequest(
        chat_id=chat_id,
        session_id=None,
        messages=({"role": "user", "content": question},),
        store_history_messages=True,
    )


async def test_empty_response_persisted_in_session(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """0 trafień + niepuste empty_response → assistant w sesji ma content = html.escape(E)."""
    chat, _dataset, _doc = await chat_with_doc(
        container, sm, _DOC, prompt_config={"empty_response": _EMPTY_RESPONSE}
    )
    stream = await container.chat.start(
        principal_for(chat.tenant_id), _req(chat.id, _NO_HITS_QUESTION)
    )
    events = await collect(stream)

    assert len(events) == 1
    final = events[0]
    assert isinstance(final, Final)
    assert final.empty is True
    assert final.answer == html.escape(_EMPTY_RESPONSE)

    session_id = stream.ids.session_id
    assert session_id is not None
    async with transaction(sm) as session:
        msgs = await chat_messages_repo.list_by_session(session, session_id)
    assistant = [m for m in msgs if m.role == "assistant"][-1]
    assert assistant.content == html.escape(_EMPTY_RESPONSE)
    assert assistant.reference == {"total": 0, "chunks": [], "doc_aggs": []}
