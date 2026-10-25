"""Testy integracyjne DbChatService na MariaDB + fake-llm (brief T4, kontrakt C12)."""

import html
import re
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories import chat_sessions as chat_sessions_repo
from app.db.repositories.chat_sessions import SessionRow
from app.db.uow import transaction
from app.domain.chat.events import AnswerDelta, ErrorEvent, Final
from app.domain.chat.kb_text import kb_text
from app.services.chat import CompletionRequest
from tests.integration.chat.conftest import (
    chat_with_doc,
    collect,
    seed_chat,
    seed_user,
    use_scenario,
)
from tests.integration.ingest.conftest import TIME_MS, seed_dataset
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

# Dokument o smoku wawelskim; pytanie zawiera jego słowa (tryb termowy, w=0.0).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_QUESTION = "Gdzie mieszkał smok wawelski?"
_LONG_QUESTION = (
    "Gdzie według starych krakowskich legend mieszkał smok wawelski i co stało się z nim potem?"
)
_NO_HITS_QUESTION = "Prognoza pogody na weekend w górach?"
_EMPTY_RESPONSE = "Sorry! No relevant content was found in the knowledge base!"
# message_count po pierwszej i drugiej turze (prologue + 2 wiadomości na turę).
_COUNT_AFTER_FIRST = 3
_COUNT_AFTER_SECOND = 5


def _req(  # noqa: PLR0913 — pola CompletionRequest (K4 §3.3)
    chat_id: str | None,
    question: str,
    *,
    session_id: str | None = None,
    llm_id: str | None = None,
    doc_ids: tuple[str, ...] | None = None,
    store_history_messages: bool = True,
    pass_all_history_messages: bool = False,
) -> CompletionRequest:
    """CompletionRequest jednego pytania user (domyślne pola kontraktu K4 §3.3)."""
    return CompletionRequest(
        chat_id=chat_id,
        session_id=session_id,
        messages=({"role": "user", "content": question},),
        llm_id=llm_id,
        doc_ids=doc_ids,
        store_history_messages=store_history_messages,
        pass_all_history_messages=pass_all_history_messages,
    )


async def _expected_answer(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> str:
    """Odpowiedź fake-chat (K10 §4): "Na podstawie źródeł: " + treść bloku ID:0 (≤80 znaków).

    Treść bloku to ``kb_text(content_llm) or content`` (E4-7c: prompt bez HTML poza tabelami).
    """
    async with transaction(sm) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.content, c.content_llm, d.name FROM chunks c"
                    " JOIN documents d ON d.id = c.document_id"
                    " WHERE c.dataset_id = :d"
                ),
                {"d": dataset_id},
            )
        ).one()
    plain, llm, doc_name = str(row[0]), row[1], str(row[2])
    content = kb_text(str(llm) if llm is not None else plain) or plain
    body = f"├── Title: {doc_name}\n└── Content:\n{content}"
    snippet = body.strip()[:80].rstrip()
    return "Na podstawie źródeł: " + snippet + " [ID:0]"


async def test_answer_stream_with_citation(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek (a): delty == odpowiedź modelu, Final z referencją, prompt z blokiem ID: 0."""
    chat, ds, _doc = await chat_with_doc(container, sm, _DOC)
    expected = await _expected_answer(sm, ds.id)
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    events = await collect(stream)
    deltas = [e for e in events if isinstance(e, AnswerDelta)]
    finals = [e for e in events if isinstance(e, Final)]
    assert deltas, "odpowiedź modelu ma przyjść deltami"
    assert len(finals) == 1
    assert not finals[0].empty
    assert "".join(d.text for d in deltas) == expected
    async with transaction(sm) as session:
        chunk_id = str(
            (
                await session.execute(
                    text("SELECT id FROM chunks WHERE dataset_id = :d"), {"d": ds.id}
                )
            ).scalar_one()
        )
    reference = finals[0].reference
    assert reference["chunks"][0]["id"] == chunk_id
    assert "ID: 0" in finals[0].prompt
    assert "[ID:0]" in finals[0].final_answer
    assert len(reference["doc_aggs"]) == 1


async def test_empty_response(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """Przypadek (c): brak trafień i domyślny empty_response → dokładnie jedno Final(empty=True)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    chat = await seed_chat(
        sm,
        dataset.tenant_id,
        [dataset.id],
        prompt_config={},
        similarity_threshold=0.99,
        vector_similarity_weight=0.0,
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
    assert final.final_answer == html.escape(_EMPTY_RESPONSE)
    assert final.reference == {"total": 0, "chunks": [], "doc_aggs": []}
    assert final.prompt == "\n\n### Query:\n" + _NO_HITS_QUESTION
    assert final.created_at is None


async def test_session_persistence_and_second_turn(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek (g): sesja, prologue, wiadomości 0-2; druga tura → seq 3-4, message_count 5."""
    chat, _ds, _doc = await chat_with_doc(
        container, sm, _DOC, prompt_config={"refine_multiturn": False}
    )
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _LONG_QUESTION))
    events = await collect(stream)
    assert any(isinstance(e, Final) and not e.empty for e in events)
    session_id = stream.ids.session_id
    assert session_id is not None
    async with transaction(sm) as session:
        srow = await chat_sessions_repo.get(session, session_id)
        msgs = await chat_messages_repo.list_by_session(session, session_id)
    assert srow is not None
    assert srow.name == _LONG_QUESTION[:50]
    assert srow.user_id == principal.email
    assert srow.owner_id == principal.user_id
    assert srow.message_count == _COUNT_AFTER_FIRST
    assert [m.seq for m in msgs] == [0, 1, 2]
    assert msgs[0].role == "assistant" and msgs[0].reference is None
    assert msgs[1].role == "user"
    assert msgs[2].role == "assistant"
    assert msgs[2].id == stream.ids.message_id
    assert msgs[2].reference is not None
    assert (msgs[2].completion_tokens or 0) > 0

    stream2 = await container.chat.start(principal, _req(chat.id, _QUESTION, session_id=session_id))
    events2 = await collect(stream2)
    assert any(isinstance(e, Final) and not e.empty for e in events2)
    async with transaction(sm) as session:
        srow2 = await chat_sessions_repo.get(session, session_id)
        msgs2 = await chat_messages_repo.list_by_session(session, session_id)
    assert srow2 is not None and srow2.message_count == _COUNT_AFTER_SECOND
    assert [m.seq for m in msgs2] == [0, 1, 2, 3, 4]


async def test_store_history_disabled_requires_pass_all(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek (h): store=False z pass_all → brak zapisu; store=False bez pass_all → błąd."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(
        principal,
        _req(chat.id, _QUESTION, store_history_messages=False, pass_all_history_messages=True),
    )
    await collect(stream)
    async with transaction(sm) as session:
        sessions = (
            await session.execute(
                text("SELECT COUNT(*) FROM chat_sessions WHERE chat_id = :c"), {"c": chat.id}
            )
        ).scalar_one()
        messages = (await session.execute(text("SELECT COUNT(*) FROM chat_messages"))).scalar_one()
    assert sessions == 0
    assert messages == 0
    with pytest.raises(ValidationFailed, match="must be true when `store_history_messages`"):
        await container.chat.start(
            principal, _req(chat.id, _QUESTION, store_history_messages=False)
        )


async def test_start_denies_user_without_chat_use(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek (i): użytkownik C (nie właściciel, nie admin) → PermissionDenied przed iteracją."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    stranger = principal_for(await seed_user(sm))
    with pytest.raises(PermissionDenied):
        await container.chat.start(stranger, _req(chat.id, _QUESTION))


async def test_session_of_other_chat_rejected(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek (j): sesja innego czatu → ValidationFailed."""
    chat, ds, _doc = await chat_with_doc(container, sm, _DOC)
    other_chat = await seed_chat(sm, ds.tenant_id, [ds.id])
    other_session = uuid.uuid4().hex
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(
            session,
            SessionRow(
                id=other_session,
                chat_id=other_chat.id,
                name="obca",
                user_id=None,
                owner_id=ds.tenant_id,
                source="api",
                message_count=0,
                create_time=TIME_MS,
                update_time=TIME_MS,
            ),
        )
    principal = principal_for(chat.tenant_id)
    with pytest.raises(ValidationFailed, match="Session does not belong to this chat!"):
        await container.chat.start(principal, _req(chat.id, _QUESTION, session_id=other_session))


async def test_session_of_other_user_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek (j): sesja użytkownika A; właściciel czatu B → PermissionDenied (can: session)."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    a_user_id = await seed_user(sm)
    a_session = uuid.uuid4().hex
    async with transaction(sm) as session:
        await chat_sessions_repo.insert(
            session,
            SessionRow(
                id=a_session,
                chat_id=chat.id,
                name="sesja A",
                user_id=f"{a_user_id}@example.com",
                owner_id=a_user_id,
                source="api",
                message_count=0,
                create_time=TIME_MS,
                update_time=TIME_MS,
            ),
        )
    owner = principal_for(chat.tenant_id)  # B — właściciel czatu, nie admin
    with pytest.raises(PermissionDenied):
        await container.chat.start(owner, _req(chat.id, _QUESTION, session_id=a_session))


async def test_session_validation_errors(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek (j): session_id bez chat_id; nieistniejąca sesja; nieistniejący czat."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    principal = principal_for(chat.tenant_id)
    with pytest.raises(ValidationFailed, match="`chat_id` is required"):
        await container.chat.start(principal, _req(None, _QUESTION, session_id="abc"))
    missing = uuid.uuid4().hex
    with pytest.raises(NotFound, match="Session not found!"):
        await container.chat.start(principal, _req(chat.id, _QUESTION, session_id=missing))
    with pytest.raises(NotFound, match="Chat not found!"):
        await container.chat.start(principal, _req(uuid.uuid4().hex, _QUESTION))


async def test_doc_ids_outside_chat_datasets_rejected(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek (k): dokument innego datasetu → ValidationFailed; dokument czatu → działa."""
    chat, _ds, doc_id = await chat_with_doc(container, sm, _DOC)
    other_ds = await seed_dataset(sm)
    other_doc = await ingest_text(
        container, other_ds, "inny.txt", "Prognoza pogody: słonecznie i bez opadów."
    )
    principal = principal_for(chat.tenant_id)
    with pytest.raises(ValidationFailed, match="are not in the chat's datasets"):
        await container.chat.start(principal, _req(chat.id, _QUESTION, doc_ids=(other_doc,)))
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION, doc_ids=(doc_id,)))
    events = await collect(stream)
    assert any(isinstance(e, Final) and not e.empty for e in events)


async def test_solo_chat(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """Solo (chat_id=None): delty + Final z R={"chunks":[]}, ids None, zero nowych sesji."""
    principal = principal_for(await seed_user(sm))
    async with transaction(sm) as session:
        before = (await session.execute(text("SELECT COUNT(*) FROM chat_sessions"))).scalar_one()
    stream = await container.chat.start(principal, _req(None, _QUESTION))
    events = await collect(stream)
    deltas = [e for e in events if isinstance(e, AnswerDelta)]
    finals = [e for e in events if isinstance(e, Final)]
    assert deltas
    assert len(finals) == 1 and not finals[0].empty
    assert finals[0].reference == {"chunks": []}
    assert stream.ids.session_id is None
    assert stream.ids.chat_id is None
    async with transaction(sm) as session:
        after = (await session.execute(text("SELECT COUNT(*) FROM chat_sessions"))).scalar_one()
    assert after == before


async def test_last_message_must_be_from_user(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Walidacja: ostatnia wiadomość nie user → ValidationFailed."""
    principal = principal_for(await seed_user(sm))
    request = CompletionRequest(
        chat_id=None,
        session_id=None,
        messages=(
            {"role": "user", "content": "pierwsze"},
            {"role": "assistant", "content": "odpowiedź"},
        ),
    )
    with pytest.raises(ValidationFailed, match="not from user"):
        await container.chat.start(principal, request)


async def test_unknown_llm_id_rejected(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Walidacja: llm_id bez trafienia w rejestrze → NotFound "Cannot use specified model"."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    principal = principal_for(chat.tenant_id)
    with pytest.raises(NotFound, match=re.escape("Cannot use specified model nie-ma-takiego.")):
        await container.chat.start(principal, _req(chat.id, _QUESTION, llm_id="nie-ma-takiego"))


async def test_posthoc_citations_when_model_omits_markers(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Post-hoc (R0 p. 11): scenariusz no_citations → znacznik [ID:0] dopisany finalize."""
    chat, ds, _doc = await chat_with_doc(container, sm, _DOC)
    use_scenario(container, "no_citations")
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    events = await collect(stream)
    finals = [e for e in events if isinstance(e, Final)]
    assert len(finals) == 1 and not finals[0].empty
    deltas = [e for e in events if isinstance(e, AnswerDelta)]
    raw = "".join(d.text for d in deltas)
    assert "[ID:" not in raw, "scenariusz no_citations nie może zwrócić znacznika"
    async with transaction(sm) as session:
        chunk_id = str(
            (
                await session.execute(
                    text("SELECT id FROM chunks WHERE dataset_id = :d"), {"d": ds.id}
                )
            ).scalar_one()
        )
    assert "[ID:0]" in finals[0].final_answer
    assert finals[0].reference["chunks"][0]["id"] == chunk_id
    assert len(finals[0].reference["doc_aggs"]) == 1


async def test_error_midstream_saves_partial_and_emits_error(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """K4 §1.5: błąd LLM w strumieniu → ErrorEvent + zapis odpowiedzi z **ERROR**."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    use_scenario(container, "error_500")
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    events = await collect(stream)  # strumień nie rzuca — błąd jako ErrorEvent
    assert [type(e) for e in events] == [ErrorEvent]
    assert events[0].message  # komunikat WDError z bramki (bez wewnętrznych szczegółów)
    async with transaction(sm) as session:
        msgs = await chat_messages_repo.list_by_session(session, stream.ids.session_id or "")
    assert [m.role for m in msgs] == ["assistant", "user", "assistant"]  # prologue + zapis błędu
    assert msgs[2].content.startswith("**ERROR**: ")
    assert msgs[2].reference is None


async def test_refine_multiturn_uses_full_question(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Refine (≥ 2 pytania user): pytanie po full_question trafia do promptu pustej odpowiedzi."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    chat = await seed_chat(
        sm,
        dataset.tenant_id,
        [dataset.id],
        prompt_config={},
        similarity_threshold=0.99,
        vector_similarity_weight=0.0,
    )
    principal = principal_for(chat.tenant_id)
    request = CompletionRequest(
        chat_id=chat.id,
        session_id=None,
        messages=(
            {"role": "user", "content": "Poprzednie pytanie o smoku?"},
            {"role": "assistant", "content": "Mieszkał pod Wawelem."},
            {"role": "user", "content": _NO_HITS_QUESTION},
        ),
        pass_all_history_messages=True,
    )
    events = await collect(await container.chat.start(principal, request))
    final = next(e for e in events if isinstance(e, Final))
    assert final.empty is True  # fake-refine zwraca "Odpowiedź testowa: Output: " → brak trafień
    # refine zwraca echo z końcową spacją, pole prompt przycina ją (dług E2-1 D1)
    assert final.prompt == "\n\n### Query:\nOdpowiedź testowa: Output:"


async def test_keywords_appended_to_question(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """prompt_config.keyword=True: słowa kluczowe dopisane przecinkiem do pytania."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    chat = await seed_chat(
        sm,
        dataset.tenant_id,
        [dataset.id],
        prompt_config={"keyword": True},
        similarity_threshold=0.99,
        vector_similarity_weight=0.0,
    )
    principal = principal_for(chat.tenant_id)
    events = await collect(await container.chat.start(principal, _req(chat.id, _QUESTION)))
    final = next(e for e in events if isinstance(e, Final))
    assert final.empty is False  # oryginalne pytanie zostaje — retrieval trafia w dokument
    # pytanie po keywords: oryginał + "," + słowa kluczowe od modelu fake
    assert _QUESTION + ",Odpowiedź testowa: Output:" in final.prompt
    assert "[ID:0]" in final.final_answer


async def test_empty_llm_answer_no_final_but_session_saved(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """K4 §1.2/§5.3: scenariusz `empty` — brak Final, zapis sesji; complete_once wg R0 p. 4."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    use_scenario(container, "empty")
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    events = await collect(stream)
    assert events == []  # pusta odpowiedź: ani delt, ani ramki Final
    async with transaction(sm) as session:
        msgs = await chat_messages_repo.list_by_session(session, stream.ids.session_id or "")
    assert [m.role for m in msgs] == ["assistant", "user", "assistant"]  # prologue + zapis i tak
    assert msgs[2].content == ""
    assert msgs[2].reference is None
    result = await container.chat.complete_once(principal, _req(chat.id, _QUESTION))
    assert result.answer == ""
    assert result.reference == {"chunks": []}
    assert result.prompt == ""
    assert result.created_at > 0


async def test_complete_once_matches_stream(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przypadek complete_once dla (a): answer == Final.final_answer, created_at > 0, chunki."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    finals = [e for e in await collect(stream) if isinstance(e, Final)]
    assert len(finals) == 1
    result = await container.chat.complete_once(principal, _req(chat.id, _QUESTION))
    assert result.answer == finals[0].final_answer
    assert result.created_at > 0
    assert result.reference["chunks"]
    assert result.ids.chat_id == chat.id
    assert result.ids.session_id is not None
