"""Scenariusz przepływu hub-compat na jednym czacie i dokumencie (brief E2-5 T5; 03-hub-compat §9).

Odtwarza pełną ścieżkę R1→R3→R5→R2→R6→R2→R7→R4 klienta
``hub-compat/src/utils/ragflow.ts`` na czacie z modelem ``fake-chat-think`` (właściciel
``owner``, cudzy dla serwisowego ``hub``); wszystkie żądania niosą ``hub_headers`` (A9),
a pobranie dokumentu (R7) idzie z ``doc_headers`` (tylko ``Authorization``):

1. R1 ``listAssistants`` (l. 18-23) — ``GET /chats?page_size=100``,
2. R3 ``createSession`` (l. 32-40) — ``POST /chats/{id}/sessions``,
3. R5 ``getCompletion`` (l. 65-71) — ``stream:false``; znaczniki ``[ID:N]`` i referencje,
4. R2 ``listSessions`` (l. 25-30) — historia z ``reference`` przy właściwej wiadomości,
5. R6 ``getReasoningCompletion`` (l. 78-156) — sekwencja ramek SSE z myśleniem,
6. R2 ponownie — ``<think>…</think>odpowiedź`` (A8) i referencja przy TEJ wiadomości,
7. R7 ``downloadDocument`` (l. 158-165) — bajty pliku z ``Content-Disposition: attachment``,
8. R4 ``deleteSessions`` (l. 42-48) — ``DELETE`` z JSON-em; sesja znika z listy.

**Odstępstwo od briefu (DEC-049).** Czat scenariusza powstaje w tym pliku przez
``seed_chat`` (ten sam dataset i dokument co fixture ``reasoning_llm``, ten sam model
``fake-chat-think``), ale z ``refine_multiturn: False`` — R6 jest drugim completion w sesji
``sid``, a fake-llm nie przepisuje pytania z historią (refine → pusty retrieval). Fixture
``reasoning_llm`` pozostaje zależnością testu (rejestracja modelu, dataset, dokument,
właściciel). Luka:ścieżka ``refine`` w wielotur nie jest tu pokryta.
"""

import json
import re
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.contract.hub_compat.ragflow_calls.conftest import (
    QUESTION,
    HubAccount,
    HubChat,
    doc_headers,
    hub_headers,
    ok_data,
)
from tests.integration.chat.conftest import seed_chat

pytestmark = [
    pytest.mark.hub_compat,
    pytest.mark.contract,
    pytest.mark.db,
    pytest.mark.fakellm,
]

_HTTP_OK = 200
# ``user_id`` sesji zakładanej przez hub-compat (ragflow.ts:32-40).
_SESSION_USER_ID = "ai@hub.test"
# Nazwa rozmowy nadana przez hub-compat (03-hub-compat §3, R3).
_SESSION_NAME = "Rozmowa"
# Myślenie modelu ``fake-chat-think`` (``tools/fake-llm/fake_llm/answers.py``) po rozdzieleniu.
_THINKING = "Rozważam pytanie."
# Terminator profilu ragflow_0_24 (app/api/ragflow/sse.py) — dosłownie ostatnia linia SSE.
_TERMINATOR_V024 = 'data:{"code":0,"data":true}'
# A8: treść z myśleniem jako ``<think>…</think>odpowiedź`` (spec 03 §8).
_THINK_BLOCK_RE = re.compile(r"^\s*<think>([\s\S]*?)</think>\s*([\s\S]*)$")
# Liczba wymian Q/A w sesji po krokach R5 i R6 (krok 6 briefu).
_EXCHANGES = 2
# 7 kluczy ``ChunkReference`` wiadomości sesji v0.24 (C3; ``present/references.py``).
_SESSION_CHUNK_KEYS = {
    "id",
    "content",
    "document_id",
    "document_name",
    "dataset_id",
    "image_id",
    "positions",
}


def _sse_payloads(response: httpx.Response) -> list[object]:
    """Pola ``data`` ramek SSE — parser hub-compat (ragflow.ts:139-146)."""
    payloads: list[object] = []
    for line in response.text.splitlines():
        stripped = line.strip()
        if stripped.startswith("data:"):
            payloads.append(json.loads(stripped[5:].strip()).get("data"))
    return payloads


def _sse_frames(response: httpx.Response) -> list[dict[str, Any]]:
    """Ramki, których ``data`` jest obiektem; sentinel ``data:true`` pomijany (ragflow.ts:98-99)."""
    return [payload for payload in _sse_payloads(response) if isinstance(payload, dict)]


async def _list_sessions(
    client: httpx.AsyncClient, token: str, chat_id: str
) -> list[dict[str, Any]]:
    """``listSessions`` (ragflow.ts:25-30): ``data`` to lista sesji v0.24."""
    listed = ok_data(
        await client.get(
            f"/api/v1/chats/{chat_id}/sessions?page_size=100", headers=hub_headers(token)
        )
    )
    assert isinstance(listed, list)
    return listed


def _by_id(sessions: list[dict[str, Any]], session_id: str) -> dict[str, Any]:
    """Sesja o danym id z listy ``listSessions``."""
    return next(entry for entry in sessions if entry["id"] == session_id)


def _answers(messages: list[Any]) -> list[dict[str, Any]]:
    """Wiadomości assistant z parą pytanie/odpowiedź (v0.24: ``created_at``; prolog go nie ma)."""
    return [
        message
        for message in messages
        if message["role"] == "assistant" and "created_at" in message
    ]


# Scenariusz 8 kroków briefu: 6 fixture'ów i ~71 instrukcji w jednej funkcji liniowej (T5).
async def test_chat_flow_ai_hub(  # noqa: PLR0913, PLR0915, PLR0917
    client: httpx.AsyncClient,
    hub: HubAccount,
    hub_chat: HubChat,
    reasoning_llm: HubChat,
    owner: HubAccount,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Pełna ścieżka R1→R3→R5→R2→R6→R2→R7→R4 na czacie z ``fake-chat-think``."""
    # DEC-049: czat scenariusza = ten sam dataset/dokument/model co ``reasoning_llm``, ale
    # ``refine_multiturn: False`` — R6 to drugie completion w sesji sid, a fake-llm nie umie
    # przepisać pytania z historią (refine → pusty retrieval). Precedens: T3
    # ``test_r2_sessions_history.py``. Fixture ``reasoning_llm`` rejestruje model i daje
    # dataset/dokument/właściciela.
    dataset_id = reasoning_llm.dataset_id
    row = await seed_chat(
        sm,
        owner.user_id,
        [dataset_id],
        prompt_config={"refine_multiturn": False},
        llm_id="fake-chat-think",
    )
    flow_chat = HubChat(row.id, dataset_id, reasoning_llm.document_id, reasoning_llm.document_name)
    # 1. R1 — ``GET /chats?page_size=100`` (ragflow.ts:19); superuser ``hub`` widzi cudzy czat.
    listing = ok_data(
        await client.get("/api/v1/chats?page_size=100", headers=hub_headers(hub.token))
    )
    assert isinstance(listing, list)
    item = next(entry for entry in listing if entry["id"] == flow_chat.chat_id)
    assert isinstance(item["prompt"]["opener"], str)
    assert flow_chat.dataset_id in [entry["id"] for entry in item["datasets"]]
    assert "dataset_ids" not in item

    # 2. R3 — ``POST /chats/{id}/sessions`` (ragflow.ts:32-40).
    created = ok_data(
        await client.post(
            f"/api/v1/chats/{flow_chat.chat_id}/sessions",
            headers=hub_headers(hub.token),
            json={"name": _SESSION_NAME, "user_id": _SESSION_USER_ID},
        )
    )
    session_id = str(created["id"])
    assert created["user_id"] == _SESSION_USER_ID
    assert isinstance(created["update_time"], int) and created["update_time"] > 10**12
    assert created["messages"][0]["role"] == "assistant"
    assert "reference" not in created["messages"][0]

    # 3. R5 — ``POST completions`` ``stream:false`` (ragflow.ts:65-71).
    r5 = ok_data(
        await client.post(
            f"/api/v1/chats/{flow_chat.chat_id}/completions",
            headers=hub_headers(hub.token),
            json={"question": QUESTION, "session_id": session_id, "stream": False},
        )
    )
    assert r5["session_id"] == session_id
    answer = str(r5["answer"])
    assert "[ID:0]" in answer
    chunks = r5["reference"]["chunks"]
    assert isinstance(chunks, list) and chunks
    required = {"id", "content", "document_id", "document_name", "dataset_id", "similarity"}
    for chunk in chunks:
        assert required <= set(chunk)
        assert chunk["document_id"] == hub_chat.document_id

    # 4. R2 — ``GET sessions?page_size=100`` (ragflow.ts:25-30); A4: tylko ta sesja → 1. miejsce.
    listed = await _list_sessions(client, hub.token, flow_chat.chat_id)
    session = _by_id(listed, session_id)
    assert listed[0]["id"] == session_id
    assert session["user_id"] == _SESSION_USER_ID
    messages = session["messages"]
    assert "reference" not in messages[0]
    # Model ``fake-chat-think`` opakowuje myślenie w treści zapisanej wiadomości (A8).
    r5_answers = _answers(messages)
    assert len(r5_answers) == 1, r5_answers
    assert str(r5_answers[0]["content"]).endswith(answer)
    assert isinstance(r5_answers[0]["reference"], list) and r5_answers[0]["reference"]

    # 5. R6 — ``POST completions`` ``stream:true, reasoning:true`` (ragflow.ts:78-156).
    response = await client.post(
        f"/api/v1/chats/{flow_chat.chat_id}/completions",
        headers=hub_headers(hub.token),
        json={"question": QUESTION, "session_id": session_id, "stream": True, "reasoning": True},
    )
    assert response.status_code == _HTTP_OK, response.text
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    frames = _sse_frames(response)
    starts = [index for index, frame in enumerate(frames) if frame.get("start_to_think")]
    ends = [index for index, frame in enumerate(frames) if frame.get("end_to_think")]
    finals = [index for index, frame in enumerate(frames) if frame.get("final")]
    assert len(starts) == len(ends) == len(finals) == 1
    start, end, final = starts[0], ends[0], finals[0]
    assert start == 0 and start < end < final == len(frames) - 1
    thinking = "".join(str(frame.get("answer") or "") for frame in frames[start + 1 : end])
    assert thinking == _THINKING
    streamed = "".join(str(frame.get("answer") or "") for frame in frames[end + 1 : final])
    assert "[ID:0]" in streamed
    r6_chunks = frames[final]["reference"]["chunks"]
    assert isinstance(r6_chunks, list) and r6_chunks
    assert _sse_payloads(response)[-1] is True
    assert response.text.strip().splitlines()[-1] == _TERMINATOR_V024

    # 6. R2 ponownie — A8: ``<think>…</think>odpowiedź`` i referencja przy TEJ wiadomości.
    session = _by_id(await _list_sessions(client, hub.token, flow_chat.chat_id), session_id)
    answers = _answers(session["messages"])
    assert len(answers) == _EXCHANGES, answers
    matched = _THINK_BLOCK_RE.match(str(answers[1]["content"]))
    assert matched is not None, answers[1]["content"]
    assert matched.group(1) == _THINKING
    assert matched.group(2).strip()
    for entry in answers:
        assert isinstance(entry["reference"], list) and entry["reference"]
        for chunk in entry["reference"]:
            assert set(chunk) == _SESSION_CHUNK_KEYS

    # 7. R7 — ``downloadDocument`` (ragflow.ts:158-165): tylko ``Authorization`` (bez Content-Type).
    document_id = r6_chunks[0]["document_id"]
    download = await client.get(
        f"/api/v1/datasets/{flow_chat.dataset_id}/documents/{document_id}",
        headers=doc_headers(hub.token),
    )
    assert download.status_code == _HTTP_OK, download.text
    assert "Wawelski" in download.content.decode()
    assert download.headers["content-disposition"].startswith("attachment")

    # 8. R4 — ``DELETE /chats/{id}/sessions`` z JSON-em (ragflow.ts:42-48); sesja znika.
    deleted = await client.request(
        "DELETE",
        f"/api/v1/chats/{flow_chat.chat_id}/sessions",
        headers=hub_headers(hub.token),
        json={"ids": [session_id]},
    )
    assert deleted.status_code == _HTTP_OK, deleted.text
    remaining = await _list_sessions(client, hub.token, flow_chat.chat_id)
    assert session_id not in [entry["id"] for entry in remaining]
