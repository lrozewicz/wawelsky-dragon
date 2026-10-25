"""Testy integracyjne scenariuszy czatu (brief T5, K4 §5 p. 3): myślenie, błędy, SSE, anulowanie."""

import asyncio
import contextlib
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.ragflow.sse import TERMINATOR, sse_native
from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories.chat_messages import MessageRow
from app.db.uow import transaction
from app.domain.chat.events import (
    AnswerDelta,
    ErrorEvent,
    Final,
    ThinkDelta,
    ThinkEnd,
    ThinkStart,
)
from app.domain.chat.kb_text import kb_text
from app.llm.tokens import count_tokens
from app.services.chat import CompletionRequest
from tests.integration.chat.conftest import (
    chat_with_doc,
    collect,
    register_think_model,
    seed_chat,
    seed_user,
    use_scenario,
)
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

# Dokument o smoku wawelskim; pytanie zawiera jego słowa (tryb termowy).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_QUESTION = "Gdzie mieszkał smok wawelski?"
_REFINED = "Odpowiedź testowa: Output: "  # fake-chat bez bloków wiedzy (refine/keywords, K10 §4)
_MIN_SSE_FRAMES = 4  # delty + ramka finalna + terminator (scenariusz a)


def _req(
    chat_id: str | None,
    question: str,
    *,
    session_id: str | None = None,
    llm_id: str | None = None,
) -> CompletionRequest:
    """CompletionRequest jednego pytania user (K4 §3.3, jak w testach usługi)."""
    return CompletionRequest(
        chat_id=chat_id,
        session_id=session_id,
        messages=({"role": "user", "content": question},),
        llm_id=llm_id,
    )


async def _expected_answer(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> str:
    """Surowa odpowiedź fake-chat (K10 §4): "Na podstawie źródeł: " + blok ID:0 + " [ID:0]".

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
    return "Na podstawie źródeł: " + body.strip()[:80].rstrip() + " [ID:0]"


async def _messages(
    sm: async_sessionmaker[AsyncSession], session_id: str | None
) -> list[MessageRow]:
    """Wiadomości sesji wg seq (asercje zapisu K4 §3.4)."""
    async with transaction(sm) as session:
        return await chat_messages_repo.list_by_session(session, session_id or "")


async def test_think_model_emits_think_frames_and_stores_think(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(b) fake-chat-think: ramki myślenia, Final.thinking, zapis <think>…</think>."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    await register_think_model(sm)
    stream = await container.chat.start(
        principal_for(chat.tenant_id), _req(chat.id, _QUESTION, llm_id="fake-chat-think")
    )
    events = await collect(stream)
    kinds = [type(e) for e in events]
    assert kinds[0] is ThinkStart and kinds[1] is ThinkDelta
    assert "".join(e.text for e in events if isinstance(e, ThinkDelta)) == "Rozważam pytanie."
    assert kinds.index(ThinkEnd) < kinds.index(AnswerDelta) < kinds.index(Final)
    finals = [e for e in events if isinstance(e, Final)]
    assert len(finals) == 1
    assert finals[0].thinking == "Rozważam pytanie."
    assert "<think>" not in finals[0].final_answer
    msgs = await _messages(sm, stream.ids.session_id)
    assert msgs[2].role == "assistant"
    assert msgs[2].content.startswith("<think>Rozważam pytanie.</think>")


async def test_error_500_yields_error_event_and_saves_session(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(d) error_500: ErrorEvent bez Final, zapis **ERROR**:; bajty: ramka 500 + terminator."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    use_scenario(container, "error_500")
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    events = await collect(stream)
    assert not any(isinstance(e, Final) for e in events)
    error = events[-1]
    assert isinstance(error, ErrorEvent) and error.message  # komunikat LLMError (str niepusty)
    msgs = await _messages(sm, stream.ids.session_id)
    assert [m.role for m in msgs] == ["assistant", "user", "assistant"]
    assert msgs[1].content == _QUESTION
    assert msgs[2].content.endswith("**ERROR**: " + error.message)
    assert msgs[2].reference is None
    stream2 = await container.chat.start(principal, _req(chat.id, _QUESTION))
    frames = [f async for f in sse_native(stream2.events, stream2.ids)]
    assert frames[-2].startswith(b'data:{"code":500,')
    assert frames[-1] == TERMINATOR


async def test_empty_llm_answer_has_no_final(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(e) scenariusz empty: brak Final i delt, zapis pustej treści, SSE = sam terminator."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    use_scenario(container, "empty")
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    events = await collect(stream)
    assert not any(isinstance(e, Final | AnswerDelta) for e in events)
    msgs = await _messages(sm, stream.ids.session_id)
    assert [m.role for m in msgs] == ["assistant", "user", "assistant"]
    assert msgs[2].content == ""
    assert msgs[2].reference is None
    stream2 = await container.chat.start(principal, _req(chat.id, _QUESTION))
    out = b"".join([f async for f in sse_native(stream2.events, stream2.ids)])
    assert out == TERMINATOR
    result = await container.chat.complete_once(principal, _req(chat.id, _QUESTION))
    assert result.answer == ""
    assert result.reference == {"chunks": []}
    assert result.prompt == ""


async def test_no_citations_gets_posthoc_citation(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    migrated_db: Settings,
    tmp_path: Path,
) -> None:
    """(f) no_citations: post-hoc [ID:0] w complete_once, delt bez znacznika; flaga wyłącza."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    # waga 0.3 (nie 0.0): post-hoc liczy hybrydę tokenu i wektora (R0 p. 11)
    chat = await seed_chat(
        sm,
        dataset.tenant_id,
        [dataset.id],
        similarity_threshold=0.0,
        vector_similarity_weight=0.3,
    )
    use_scenario(container, "no_citations")
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    events = await collect(stream)
    raw = "".join(e.text for e in events if isinstance(e, AnswerDelta))
    assert "[ID:" not in raw, "post-hoc trafia tylko do final_answer/sesji"
    result = await container.chat.complete_once(principal, _req(chat.id, _QUESTION))
    assert "[ID:0]" in result.answer
    # WD_POSTHOC_CITATIONS=false: finalize nie dopisuje znaczników. Ten sam per-test
    # fixtures, więc modele są już zarejestrowane — kontener bez register_models.
    instance = Container(
        migrated_db.model_copy(update={"posthoc_citations": False, "storage_root": str(tmp_path)})
    )
    await instance.start()
    try:
        ds2 = await seed_dataset(instance.sessionmaker)
        await ingest_text(instance, ds2, "wawel.txt", _DOC)
        chat2 = await seed_chat(
            instance.sessionmaker,
            ds2.tenant_id,
            [ds2.id],
            similarity_threshold=0.0,
            vector_similarity_weight=0.3,
        )
        use_scenario(instance, "no_citations")
        result2 = await instance.chat.complete_once(
            principal_for(chat2.tenant_id), _req(chat2.id, _QUESTION)
        )
        assert "[ID:" not in result2.answer
    finally:
        await instance.aclose()


async def test_chat_use_without_dataset_read_retrieves(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(l, R0 p. 2) USE czatu bez READ datasetu (permission='me') → retrieval działa."""
    user_b = await seed_user(sm)
    chat, dataset, _doc = await chat_with_doc(container, sm, _DOC, owner=user_b)
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET permission = 'me' WHERE id = :i"), {"i": dataset.id}
        )
    stream = await container.chat.start(principal_for(user_b), _req(chat.id, _QUESTION))
    finals = [e for e in await collect(stream) if isinstance(e, Final)]
    assert len(finals) == 1
    assert finals[0].reference["chunks"], "retrieve_trusted bez pętli require"


async def test_cancel_after_first_delta_saves_partial(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(K4 §3.4, rozstrzygnięcie 6) aclose po 1. delcie: zapis częściowy bez referencji."""
    chat, ds, _doc = await chat_with_doc(container, sm, _DOC)
    use_scenario(container, "slow_stream")
    stream = await container.chat.start(principal_for(chat.tenant_id), _req(chat.id, _QUESTION))
    async with contextlib.aclosing(stream.events) as events:
        async for event in events:
            if isinstance(event, AnswerDelta):
                break
    # GeneratorExit trafia do run_events przy finalizacji wewnętrznego generatora
    # (hook GC asyncio planuje aclose w następnym ticku pętli) — czekamy na zapis.
    await asyncio.sleep(0.2)
    msgs = await _messages(sm, stream.ids.session_id)
    assert [m.role for m in msgs] == ["assistant", "user", "assistant"]
    full = await _expected_answer(sm, ds.id)
    assert msgs[2].content and len(msgs[2].content) < len(full)
    assert msgs[2].reference is None


async def test_complete_once_equals_finalized_stream(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(K4 §5 p. 3) complete_once.answer == Final.final_answer; delty == surowa odpowiedź."""
    chat, ds, _doc = await chat_with_doc(container, sm, _DOC)
    principal = principal_for(chat.tenant_id)
    stream = await container.chat.start(principal, _req(chat.id, _QUESTION))
    events = await collect(stream)
    finals = [e for e in events if isinstance(e, Final)]
    assert len(finals) == 1
    deltas = "".join(e.text for e in events if isinstance(e, AnswerDelta))
    assert deltas == await _expected_answer(sm, ds.id)
    result = await container.chat.complete_once(principal, _req(chat.id, _QUESTION))
    assert result.answer == finals[0].final_answer


async def test_prompt_matches_upstream_layout(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    migrated_db: Settings,
    tmp_path: Path,
) -> None:
    """(rozstrzygnięcie 3) prompt = system + Query + czasy + tokeny (maska); expose_prompt=False."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    stream = await container.chat.start(principal_for(chat.tenant_id), _req(chat.id, _QUESTION))
    final = next(e for e in await collect(stream) if isinstance(e, Final))
    masked = re.sub(r"\d+/s", "X/s", re.sub(r"\d+\.\dms", "Xms", final.prompt))
    n = count_tokens(final.final_answer)
    tail = (
        "  \n  \n### Query:  \n"
        + _QUESTION
        + "  \n  \n## Time elapsed:  \n  - Total: Xms  \n  - Check LLM: Xms  \n"
        "  - Check Langfuse tracer: Xms  \n  - Bind models: Xms  \n"
        "  - Query refinement(LLM): Xms  \n  - Retrieval: Xms  \n  - Generate answer: Xms  \n  \n"
        "## Token usage:  \n  - Generated tokens(approximately): "
        + str(n)
        + "  \n  - Token speed: X/s"
    )
    assert masked.endswith(tail)
    assert masked.startswith("You are an assistant grounded in the dataset below")
    assert "ID: 0" in final.prompt
    instance = Container(
        migrated_db.model_copy(update={"expose_prompt": False, "storage_root": str(tmp_path)})
    )
    await instance.start()
    try:
        chat2, _d2, _doc2 = await chat_with_doc(instance, instance.sessionmaker, _DOC)
        stream2 = await instance.chat.start(
            principal_for(chat2.tenant_id), _req(chat2.id, _QUESTION)
        )
        final2 = next(e for e in await collect(stream2) if isinstance(e, Final))
        assert final2.prompt == ""
    finally:
        await instance.aclose()


async def test_sse_end_to_end_frames(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """SSE end-to-end (a): koperty data:{, final z total, delty z chunks:[] i chat_id."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)
    stream = await container.chat.start(principal_for(chat.tenant_id), _req(chat.id, _QUESTION))
    frames = [f async for f in sse_native(stream.events, stream.ids)]
    assert len(frames) >= _MIN_SSE_FRAMES
    assert all(f.startswith(b"data:{") for f in frames)
    assert frames[-1] == TERMINATOR
    assert b'"final":true' in frames[-2]
    assert b'"reference":{"total":' in frames[-2]
    assert all(b'"reference":{"chunks":[]}' in f for f in frames[:-2])
    assert all(b'"chat_id":' in f for f in frames[:-2])


async def test_refine_multiturn_uses_history(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Refine drugiej tury z historii sesji: pytanie po refine w Query, bez błędu."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC)  # refine_multiturn domyślnie True
    principal = principal_for(chat.tenant_id)
    first = await container.chat.start(principal, _req(chat.id, _QUESTION))
    await collect(first)
    second_question = "Czym karmił się smok wawelski?"
    stream = await container.chat.start(
        principal, _req(chat.id, second_question, session_id=first.ids.session_id)
    )
    events = await collect(stream)
    assert not any(isinstance(e, ErrorEvent) for e in events)
    final = next(e for e in events if isinstance(e, Final))
    assert "### Query:" in final.prompt
    # pole prompt przycina końcową spację echa refine (dług E2-1 D1)
    assert _REFINED.rstrip() in final.prompt, "refine przepisał pytanie (fake-chat)"
    assert second_question not in final.prompt


async def test_keyword_prompt_config_appends_keywords(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """prompt_config.keyword=True: pytanie w Query z dopisanym przecinkiem i słowami kluczowymi."""
    chat, _ds, _doc = await chat_with_doc(container, sm, _DOC, prompt_config={"keyword": True})
    stream = await container.chat.start(principal_for(chat.tenant_id), _req(chat.id, _QUESTION))
    events = await collect(stream)
    assert not any(isinstance(e, ErrorEvent) for e in events)
    final = next(e for e in events if isinstance(e, Final))
    assert "### Query:" in final.prompt
    assert _QUESTION + "," in final.prompt  # po pytaniu dopisano "," + słowa kluczowe modelu
