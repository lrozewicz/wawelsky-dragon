"""Odtworzenie wywołań hub-compat R5/R6 na trasie completions WD (brief E2-5 T2).

Docstringi cytują ``hub-compat/src/utils/ragflow.ts``: ``getCompletion`` (l. 50-72)
i ``getReasoningCompletion`` (l. 78-156). Wszystkie żądania idą przez HTTP z nagłówkami
``hub_headers`` (A9); profil 0.24 bierze się z klucza API (T1 conftest). Ramki SSE
parsujemy jak hub-compat: tylko linie ``data:``, ``JSON.parse`` po ``trim``, pomijamy ramki
z ``data`` nie-obiektem (``ragflow.ts:98-99, 139-146``).
"""

import json
import re
from collections.abc import Mapping
from itertools import pairwise
from typing import Any

import httpx
import pytest

from tests.contract.hub_compat.ragflow_calls.conftest import (
    QUESTION,
    HubAccount,
    HubChat,
    hub_headers,
    ok_data,
)

pytestmark = [
    pytest.mark.hub_compat,
    pytest.mark.contract,
    pytest.mark.db,
    pytest.mark.fakellm,
]

_HTTP_OK = 200
# Myślenie modelu ``fake-chat-think`` (tools/fake-llm/fake_llm/answers.py:13) po rozdzieleniu.
_THINKING = "Rozważam pytanie."
# ``user_id`` sesji zakładanej przez hub-compat (ragflow.ts:32-40).
_SESSION_USER_ID = "ai@hub.test"
# Terminator profilu ragflow_0_24 (app/api/ragflow/sse.py:36) — dosłownie ostatnia linia SSE.
_TERMINATOR_V024 = 'data:{"code":0,"data":true}'
_ID_MARKER_RE = re.compile(r"\[ID:(\d+)\]")
_BARE_MARKER_RE = re.compile(r"(?<!ID:)\[\d+\]")
_THINK_BLOCK_RE = re.compile(r"^\s*<think>([\s\S]*?)</think>\s*([\s\S]*)$")


def _sse_payloads(response: httpx.Response) -> list[object]:
    """Pola ``data`` ramek SSE — parser hub-compat (ragflow.ts:139-146)."""
    payloads: list[object] = []
    for line in response.text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        parsed = json.loads(stripped[5:].strip())
        payloads.append(parsed.get("data"))
    return payloads


def _sse_frames(response: httpx.Response) -> list[dict[str, Any]]:
    """Ramki, których ``data`` jest obiektem; sentinel ``data:true`` pomijany (ragflow.ts:98-99)."""
    return [payload for payload in _sse_payloads(response) if isinstance(payload, dict)]


def _last_data_line(response: httpx.Response) -> str:
    """Ostatnia niepusta linia ciała SSE (asercja terminatora)."""
    return response.text.strip().splitlines()[-1]


def _answers(messages: list[Any]) -> list[dict[str, Any]]:
    """Wiadomości assistant z pary pytanie/odpowiedź (v0.24: ``created_at``; prolog go nie ma)."""
    return [
        message
        for message in messages
        if message["role"] == "assistant" and "created_at" in message
    ]


async def _create_session(client: httpx.AsyncClient, token: str, chat_id: str, *, name: str) -> str:
    """``createSession`` (ragflow.ts:32-40) → id sesji."""
    created = ok_data(
        await client.post(
            f"/api/v1/chats/{chat_id}/sessions",
            headers=hub_headers(token),
            json={"name": name, "user_id": _SESSION_USER_ID},
        )
    )
    assert isinstance(created, dict)
    return str(created["id"])


async def _session(
    client: httpx.AsyncClient, token: str, chat_id: str, session_id: str
) -> dict[str, Any]:
    """``listSessions`` (ragflow.ts:25-30) → szczegół sesji z ``messages``."""
    listed = ok_data(
        await client.get(
            f"/api/v1/chats/{chat_id}/sessions?page_size=100", headers=hub_headers(token)
        )
    )
    assert isinstance(listed, list)
    found = next(entry for entry in listed if entry["id"] == session_id)
    assert isinstance(found, dict)
    return found


async def _complete(
    client: httpx.AsyncClient, token: str, chat_id: str, body: Mapping[str, object]
) -> dict[str, Any]:
    """``getCompletion`` bez strumienia (ragflow.ts:65-71) → ``data`` koperty."""
    data = ok_data(
        await client.post(
            f"/api/v1/chats/{chat_id}/completions", headers=hub_headers(token), json=body
        )
    )
    assert isinstance(data, dict)
    return data


async def _stream(
    client: httpx.AsyncClient, token: str, chat_id: str, body: Mapping[str, object]
) -> httpx.Response:
    """Strumień SSE completions (ragflow.ts:79-83): 200 i ``text/event-stream``."""
    response = await client.post(
        f"/api/v1/chats/{chat_id}/completions", headers=hub_headers(token), json=body
    )
    assert response.status_code == _HTTP_OK, response.text
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    return response


async def test_ag03_r5_answer_uses_zero_based_id_markers(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-03/A1/A2: ``getCompletion`` (ragflow.ts:65-71) — ``[ID:N]`` od 0, nigdy ``[N]``.

    Każdy indeks N wskazuje chunk w ``reference.chunks`` (UI: ``reference[N]``); brak
    samotnych nawiasów ``[N]`` (03-hub-compat §8 A2).
    """
    session_id = await _create_session(client, hub.token, hub_chat.chat_id, name="r5-markers")
    data = await _complete(
        client,
        hub.token,
        hub_chat.chat_id,
        {"question": QUESTION, "session_id": session_id, "stream": False},
    )
    answer = str(data["answer"])
    chunks = data["reference"]["chunks"]
    assert isinstance(chunks, list)
    indices = [int(match) for match in _ID_MARKER_RE.findall(answer)]
    assert indices
    assert all(index < len(chunks) for index in indices)
    assert _BARE_MARKER_RE.search(answer) is None


async def test_ag04_r5_chunk_reference_fields(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-04: chunk ``reference`` (ragflow.ts:123-127) ma pola i wartości dokumentu czatu."""
    data = await _complete(
        client,
        hub.token,
        hub_chat.chat_id,
        {"question": QUESTION, "stream": False},
    )
    chunks = data["reference"]["chunks"]
    assert isinstance(chunks, list)
    assert chunks
    required = {"id", "content", "document_id", "document_name", "dataset_id", "similarity"}
    for chunk in chunks:
        assert required <= set(chunk)
        assert isinstance(chunk["similarity"], float)
        assert 0.0 <= chunk["similarity"] <= 1.0
        assert chunk["document_id"] == hub_chat.document_id
        assert chunk["document_name"] == hub_chat.document_name
        assert chunk["dataset_id"] == hub_chat.dataset_id


async def test_r5_qa_saved_in_session(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """R5: po ``stream:false`` (ragflow.ts:65-71) Q&A trafia do sesji — bez myślenia."""
    session_id = await _create_session(client, hub.token, hub_chat.chat_id, name="r5-history")
    data = await _complete(
        client,
        hub.token,
        hub_chat.chat_id,
        {"question": QUESTION, "session_id": session_id, "stream": False},
    )
    session = await _session(client, hub.token, hub_chat.chat_id, session_id)
    messages = session["messages"]
    assert isinstance(messages, list)
    roles = [(str(message["role"]), str(message["content"])) for message in messages]
    assert ("user", QUESTION) in roles
    assert ("assistant", str(data["answer"])) in roles
    answers = _answers(messages)
    assert len(answers) == 1
    assert "<think>" not in str(answers[0]["content"])


async def test_ag02_r6_sse_reasoning_frame_sequence(
    client: httpx.AsyncClient, hub: HubAccount, reasoning_llm: HubChat
) -> None:
    """AG-02/A7: ``getReasoningCompletion`` (ragflow.ts:78-156) — kolejność ramek R6.

    ``start_to_think`` → delty myślenia → ``end_to_think`` → delty odpowiedzi (konkatenacja
    = pełna odpowiedź, nie kumulacja) → ``final:true`` z ``reference.chunks`` → terminator.
    """
    session_id = await _create_session(client, hub.token, reasoning_llm.chat_id, name="r6")
    response = await _stream(
        client,
        hub.token,
        reasoning_llm.chat_id,
        {"question": QUESTION, "session_id": session_id, "stream": True, "reasoning": True},
    )
    frames = _sse_frames(response)
    starts = [index for index, frame in enumerate(frames) if frame.get("start_to_think")]
    ends = [index for index, frame in enumerate(frames) if frame.get("end_to_think")]
    finals = [index for index, frame in enumerate(frames) if frame.get("final")]
    assert len(starts) == len(ends) == len(finals) == 1
    start, end, final = starts[0], ends[0], finals[0]
    assert start == 0
    assert start < end < final == len(frames) - 1
    think_deltas = [str(frame.get("answer") or "") for frame in frames[start + 1 : end]]
    assert think_deltas
    assert all(think_deltas)
    assert "".join(think_deltas) == _THINKING
    answer_deltas = [str(frame.get("answer") or "") for frame in frames[end + 1 : final]]
    assert answer_deltas
    assert all(answer_deltas)
    streamed = "".join(answer_deltas)
    assert "[ID:0]" in streamed
    assert all(not later.startswith(earlier) for earlier, later in pairwise(answer_deltas))
    # Ścieżka niestrumieniowa tego samego czatu i pytania (bez historii z tej sesji) —
    # konkatenacja delt SSE musi dać tę samą, pełną odpowiedź (K4 §1.3).
    single = await _complete(
        client,
        hub.token,
        reasoning_llm.chat_id,
        {"question": QUESTION, "stream": False, "reasoning": True},
    )
    assert streamed == single["answer"]
    assert frames[final]["answer"] == ""
    assert frames[final]["reference"]["chunks"]
    assert _sse_payloads(response)[-1] is True
    assert _last_data_line(response) == _TERMINATOR_V024


async def test_ag02_r6_sse_without_reasoning_delta_frames_and_terminator(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-02: ``stream:true`` bez ``reasoning`` (ragflow.ts:79-83) — delty + terminator.

    Brak ``start_to_think``; odpowiedź płynie deltami, na końcu ramka ``final:true``
    i sentinel ``data:true``.
    """
    response = await _stream(
        client, hub.token, hub_chat.chat_id, {"question": QUESTION, "stream": True}
    )
    frames = _sse_frames(response)
    assert frames
    assert all(not frame.get("start_to_think") for frame in frames)
    deltas = [str(frame.get("answer") or "") for frame in frames if frame.get("answer")]
    assert deltas
    assert "[ID:0]" in "".join(deltas)
    assert any(frame.get("final") for frame in frames)
    assert _sse_payloads(response)[-1] is True
    assert _last_data_line(response) == _TERMINATOR_V024


async def test_ag05_r6_reasoning_saved_as_think_block_in_history(
    client: httpx.AsyncClient, hub: HubAccount, reasoning_llm: HubChat
) -> None:
    """AG-05/A8: historia po R6 ma ``<think>…</think>odpowiedź`` (03-hub-compat §8 A8)."""
    session_id = await _create_session(client, hub.token, reasoning_llm.chat_id, name="r6-history")
    response = await _stream(
        client,
        hub.token,
        reasoning_llm.chat_id,
        {"question": QUESTION, "session_id": session_id, "stream": True, "reasoning": True},
    )
    assert _sse_payloads(response)[-1] is True
    session = await _session(client, hub.token, reasoning_llm.chat_id, session_id)
    messages = session["messages"]
    assert isinstance(messages, list)
    answers = _answers(messages)
    assert len(answers) == 1, answers
    match = _THINK_BLOCK_RE.match(str(answers[0]["content"]))
    assert match is not None, answers[0]["content"]
    assert match.group(1) == _THINKING
    assert match.group(2).strip()


async def test_r5_stream_false_reasoning_true_returns_thinking(
    client: httpx.AsyncClient,
    hub: HubAccount,
    hub_chat: HubChat,
    reasoning_llm: HubChat,
) -> None:
    """Ulepszenie kompatybilne (03 §3): ``stream:false, reasoning:true`` → ``data.thinking``.

    ``getCompletion`` z hub-compat w tym trybie woła SSE (ragflow.ts:56-63, 78-156), ale WD
    wspiera też wariant JSON: pełny ``answer`` + ``thinking``. Zwykły czat bez myślenia
    nie ma klucza ``thinking`` (K4 §1.7).
    """
    with_reasoning = await _complete(
        client,
        hub.token,
        reasoning_llm.chat_id,
        {"question": QUESTION, "stream": False, "reasoning": True},
    )
    assert with_reasoning["answer"]
    assert with_reasoning["thinking"] == _THINKING
    plain = await _complete(
        client, hub.token, hub_chat.chat_id, {"question": QUESTION, "stream": False}
    )
    assert "thinking" not in plain
