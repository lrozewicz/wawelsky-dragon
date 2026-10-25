"""Odtworzenie wywołania hub-compat ``listSessions`` (R2) na trasie WD (brief E2-5 T3).

hub-compat czyta historię rozmów przez ``GET /chats/{chatId}/sessions?page_size=100``
(``hub-compat/src/utils/ragflow.ts:25-30``) i mapuje ``reference`` wiadomości asystenta na
``RagflowChunk[]`` (``hub-compat/src/types/ragflow.ts:40-56``), gdzie ``similarity`` jest
opcjonalne (``types/ragflow.ts:52``) — historia WD go nie emituje (7 kluczy ``ChunkReference``).
Testy pokrywają kontrakt WP E2-5: A4 (domyślne sortowanie po ``update_time DESC`` dla konta
serwisowego 0.24), A5 (``update_time`` w ms), A6 (``reference`` przy właściwej wiadomości
asystenta) oraz A8 (treść z myśleniem jako ``<think>…</think>odpowiedź`` w historii).
"""

import asyncio
import re
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.contract.hub_compat.ragflow_calls.conftest import (
    QUESTION,
    HubAccount,
    HubChat,
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
_CODE_SUCCESS = 0
# Odmowa cudzego czatu w v0.24 (złoto chats___sessions/errors_access--29.json).
_CODE_DATA_ERROR = 102
# ``user_id`` z ciała żądania (AG-01) — upstream ``create`` wpisuje je do sesji.
_SESSION_USER_ID = "ai@hub.test"
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
# A8: treść z myśleniem jako ``<think>…</think>odpowiedź`` (spec 03 §8 A8).
_THINK_RE = re.compile(r"^\s*<think>([\s\S]*?)</think>\s*([\s\S]*)$")
# fake-llm: ``_THINK_PREFIX`` modelu ``fake-chat-think`` (``tools/fake-llm/fake_llm/answers.py``).
_THINK_TEXT = "Rozważam pytanie."
# Prolog czatu pomocniczego A6 (materiał na ``messages[0]``).
_PROLOGUE = "Prolog A6: witaj!"
# Liczba wymian Q/A w teście A6 (i odpowiadających im referencji w historii).
_EXCHANGES = 2


async def _tick() -> None:
    """Odstęp większy niż rozdzielczość zegara (ms) — ścisła kolejność czasów w teście A4."""
    await asyncio.sleep(0.003)


async def _sessions(
    client: httpx.AsyncClient, token: str, chat_id: str, query: str = ""
) -> list[dict[str, Any]]:
    """``listSessions`` (``ragflow.ts:26``): ``data`` to lista sesji (v0.24)."""
    listed = ok_data(
        await client.get(
            f"/api/v1/chats/{chat_id}/sessions?page_size=100{query}",
            headers=hub_headers(token),
        )
    )
    assert isinstance(listed, list)
    return listed


async def _create_session(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    *,
    name: str = "x",
    user_id: str = _SESSION_USER_ID,
) -> dict[str, Any]:
    """``createSession`` (``ragflow.ts:32-40``) — zwraca payload nowej sesji."""
    created = ok_data(
        await client.post(
            f"/api/v1/chats/{chat_id}/sessions",
            headers=hub_headers(token),
            json={"name": name, "user_id": user_id},
        )
    )
    assert isinstance(created, dict)
    return created


async def _complete(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    *,
    session_id: str,
    reasoning: bool = False,
) -> dict[str, Any]:
    """``getCompletion`` (``ragflow.ts:50-67``) w trybie niestrumieniowym na istniejącej sesji."""
    body: dict[str, Any] = {
        "question": QUESTION,
        "session_id": session_id,
        "stream": False,
        "reasoning": reasoning,
    }
    data = ok_data(
        await client.post(
            f"/api/v1/chats/{chat_id}/completions", headers=hub_headers(token), json=body
        )
    )
    assert isinstance(data, dict)
    return data


def _by_id(sessions: list[dict[str, Any]], session_id: str) -> dict[str, Any]:
    """Sesja o danym id z listy ``listSessions``."""
    return next(entry for entry in sessions if entry["id"] == session_id)


async def test_a4_sessions_default_sorted_by_update_time_desc(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """A4: bez ``orderby`` konto serwisowe 0.24 dostaje ``update_time DESC``.

    Trzy sesje (R3) na cudzym czacie, rozmowa (R5) w pierwszej z nich podnosi jej
    ``update_time`` — ta sesja stoi na czele listy, a czasy są niemalejące malejąco.
    """
    first = await _create_session(client, hub.token, hub_chat.chat_id, name="pierwsza")
    await _tick()
    await _create_session(client, hub.token, hub_chat.chat_id, name="druga")
    await _tick()
    await _create_session(client, hub.token, hub_chat.chat_id, name="trzecia")
    await _tick()
    await _complete(client, hub.token, hub_chat.chat_id, session_id=first["id"])

    listed = await _sessions(client, hub.token, hub_chat.chat_id)
    # ``user_id`` z ciała żądania (AG-01) nie jest owner-em: superuser ``hub`` widzi cudzy czat.
    assert listed[0]["id"] == first["id"]
    times = [entry["update_time"] for entry in listed]
    assert times == sorted(times, reverse=True)


async def test_a4_page_size_1000_accepted(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """A4: ``page_size`` do 1000 przechodzi z ``code 0`` (kontrakt WP E2-5 A4)."""
    await _create_session(client, hub.token, hub_chat.chat_id)
    response = await client.get(
        f"/api/v1/chats/{hub_chat.chat_id}/sessions?page_size=1000",
        headers=hub_headers(hub.token),
    )
    assert response.status_code == _HTTP_OK, response.text
    assert response.json()["code"] == _CODE_SUCCESS, response.json()


async def test_a4_explicit_orderby_wins(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """A4: jawne ``orderby=create_time&desc=false`` wygrywa z domyślnym profilem 0.24."""
    created_ids: list[str] = []
    for index in range(3):
        created_ids.append(
            (await _create_session(client, hub.token, hub_chat.chat_id, name=f"s{index}"))["id"]
        )
        await _tick()
    await _complete(client, hub.token, hub_chat.chat_id, session_id=created_ids[0])

    default = await _sessions(client, hub.token, hub_chat.chat_id)
    ascending = await _sessions(
        client, hub.token, hub_chat.chat_id, "&orderby=create_time&desc=false"
    )
    assert [entry["id"] for entry in ascending] == created_ids
    assert [entry["id"] for entry in ascending] != [entry["id"] for entry in default]
    create_times = [entry["create_time"] for entry in ascending]
    assert create_times == sorted(create_times)


async def test_a5_update_time_in_ms(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """A5: ``update_time`` każdej sesji w milisekundach (``types/ragflow.ts:37``)."""
    await _create_session(client, hub.token, hub_chat.chat_id)
    listed = await _sessions(client, hub.token, hub_chat.chat_id)
    assert listed
    for entry in listed:
        assert isinstance(entry["update_time"], int)
        assert entry["update_time"] > 10**12


async def test_a6_prologue_without_reference_and_reference_on_right_message(
    client: httpx.AsyncClient,
    hub: HubAccount,
    hub_chat: HubChat,
    owner: HubAccount,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """A6: prolog bez ``reference``, referencja przy WŁAŚCIWEJ wiadomości asystenta.

    Dwie wymiany Q/A w jednej sesji: każda odpowiedź asystenta nosi SWOJĄ niepustą listę
    chunków o dokładnie 7 kluczach (``types/ragflow.ts:40-56``; ``similarity`` opcjonalne,
    ``types/ragflow.ts:52`` — historia go nie emituje), a prolog i wiadomości user nie mają
    ``reference`` (żadnego przesunięcia o jeden).

    Czat pomocniczy na tym samym datasecie z ``refine_multiturn`` wyłączonym: fake-llm nie
    umie przepisać pytania z historią (na wieloturowe ``refine`` zwraca tekst spoza dokumentu),
    więc przy refinie druga wymiana nie znajduje chunków — to własność R5, nie A6.
    """
    chat = await seed_chat(
        sm,
        owner.user_id,
        [hub_chat.dataset_id],
        prompt_config={"prologue": _PROLOGUE, "refine_multiturn": False},
    )
    created = await _create_session(client, hub.token, chat.id, name="refs")
    await _complete(client, hub.token, chat.id, session_id=created["id"])
    await _complete(client, hub.token, chat.id, session_id=created["id"])

    session = _by_id(await _sessions(client, hub.token, chat.id), created["id"])
    assert "reference" not in session
    messages = session["messages"]
    assert messages[0] == {"role": "assistant", "content": _PROLOGUE}
    assert [message["role"] for message in messages] == [
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    for message in messages:
        if message["role"] == "user":
            assert "reference" not in message
    answers = [message for message in messages[1:] if message["role"] == "assistant"]
    references = [message["reference"] for message in answers]
    assert len(references) == _EXCHANGES
    for chunks in references:
        assert isinstance(chunks, list) and chunks
        for chunk in chunks:
            assert set(chunk) == _SESSION_CHUNK_KEYS
            assert "similarity" not in chunk


async def test_ag01_a3_user_id_in_list_for_service_account(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-01/A3: lista sesji niesie ``user_id``, a filtr ``?user_id=`` go zawęża.

    hub-compat zakłada sesje per użytkownik (``ragflow.ts:32``) i czyta ``user_id`` z listy.
    """
    first = await _create_session(client, hub.token, hub_chat.chat_id, name="a", user_id="a@x.pl")
    second = await _create_session(client, hub.token, hub_chat.chat_id, name="b", user_id="b@x.pl")
    listed = await _sessions(client, hub.token, hub_chat.chat_id)
    assert _by_id(listed, first["id"])["user_id"] == "a@x.pl"
    assert _by_id(listed, second["id"])["user_id"] == "b@x.pl"

    filtered = await _sessions(client, hub.token, hub_chat.chat_id, "&user_id=a@x.pl")
    assert [entry["id"] for entry in filtered] == [first["id"]]


async def test_ag05_a8_reasoning_history_think_block_regex(
    client: httpx.AsyncClient,
    hub: HubAccount,
    reasoning_llm: HubChat,
) -> None:
    """AG-05/A8: odpowiedź modelu myślącego trafia do historii jako ``<think>…</think>treść``.

    Spec 03 §8 A8: regex ``^\\s*<think>([\\s\\S]*?)</think>\\s*([\\s\\S]*)$``; grupa 1 to
    treść myślenia, grupa 2 niepusta odpowiedź. fake-llm ``fake-chat-think`` emituje
    ``<think>Rozważam pytanie.</think>…`` (``tools/fake-llm/fake_llm/answers.py``).
    """
    created = await _create_session(client, hub.token, reasoning_llm.chat_id, name="think")
    await _complete(
        client, hub.token, reasoning_llm.chat_id, session_id=created["id"], reasoning=True
    )

    session = _by_id(await _sessions(client, hub.token, reasoning_llm.chat_id), created["id"])
    answer = session["messages"][-1]
    assert answer["role"] == "assistant"
    matched = _THINK_RE.match(answer["content"])
    assert matched is not None, answer["content"]
    assert matched.group(1) == _THINK_TEXT
    assert matched.group(2).strip()


async def test_r2_stranger_denied_on_foreign_chat(
    client: httpx.AsyncClient, stranger: HubAccount, hub_chat: HubChat
) -> None:
    """R2: cudzy czat dla zwykłego konta → odmowa kopertą, nie ``{detail}``.

    Kod i komunikat ze złota v0.24.0 ``chats___sessions/errors_access--29.json``
    (102; komunikat listy niesie ``chat_id`` — ``refusals_v024`` ``sessions_list``).
    """
    response = await client.get(
        f"/api/v1/chats/{hub_chat.chat_id}/sessions?page_size=100",
        headers=hub_headers(stranger.token),
    )
    assert response.status_code == _HTTP_OK
    body = response.json()
    assert body["code"] == _CODE_DATA_ERROR
    assert body["message"] == f"You don't own the assistant {hub_chat.chat_id}."
    assert "detail" not in body
