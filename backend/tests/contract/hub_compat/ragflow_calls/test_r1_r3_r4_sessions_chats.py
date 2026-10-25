"""Odtworzenie wywołań hub-compat na trasach czatów i sesji WD (brief E2-5 T1: R1/R3/R4).

Docstringi cytują wywołania hub-compat (``hub-compat/src/utils/ragflow.ts``), które te testy
naśladują: ``listAssistants`` (R1), ``createSession``/``listSessions`` (R3), ``deleteSessions``
(R4), ``getCompletion`` (AG-07). Wszystkie nagłówki bierzemy z ``hub_headers`` — hub-compat dodaje
``Content-Type`` także przy GET/DELETE (A9; ``ragflow.ts:11-16``).
"""

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
_CODE_SUCCESS = 0
_CODE_DATA_ERROR = 102
# 32 zera: czat nieistniejący (AG-08) — odmowa kopertą, nie `{detail}`.
_MISSING_CHAT = "0" * 32
# `user_id` z ciała żądania (AG-01) — upstream `create` wpisuje je do sesji.
_SESSION_USER_ID = "ai@hub.test"


async def _sessions(client: httpx.AsyncClient, token: str, chat_id: str) -> list[dict[str, object]]:
    """Sesje czatu (v0.24: ``data`` to lista — ``ragflow.ts:26``)."""
    listed = ok_data(
        await client.get(
            f"/api/v1/chats/{chat_id}/sessions?page_size=100", headers=hub_headers(token)
        )
    )
    assert isinstance(listed, list)
    return listed


async def _create_session(
    client: httpx.AsyncClient, token: str, chat_id: str, *, name: str = "x"
) -> dict[str, object]:
    """POST sesji (R3; ``ragflow.ts:33``) i zwrócenie jej payloadu."""
    created = ok_data(
        await client.post(
            f"/api/v1/chats/{chat_id}/sessions",
            headers=hub_headers(token),
            json={"name": name, "user_id": _SESSION_USER_ID},
        )
    )
    assert isinstance(created, dict)
    return created


async def test_ag06_r1_superuser_sees_foreign_chat(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """R1/AG-06: GET /chats kluczem superusera (`ragflow.ts:19`) widzi CUDZY czat.

    Element listy v0.24: ``id, name, description, avatar, prompt.opener`` i ``datasets[].id``
    — bez ``dataset_ids`` (A12; ``present/chats_v024.py``).
    """
    listing = ok_data(
        await client.get("/api/v1/chats?page_size=100", headers=hub_headers(hub.token))
    )
    assert isinstance(listing, list)
    item = next(entry for entry in listing if entry["id"] == hub_chat.chat_id)
    for key in ("id", "name", "description", "avatar"):
        assert key in item
    assert "opener" in item["prompt"]
    assert item["datasets"][0]["id"] == hub_chat.dataset_id
    assert "dataset_ids" not in item


async def test_ag06_r1_non_superuser_does_not_see_foreign_chat(
    client: httpx.AsyncClient, stranger: HubAccount, hub_chat: HubChat
) -> None:
    """R1: ten sam GET kluczem zwykłego konta (``ragflow.ts:19``) nie widzi cudzego czatu."""
    listing = ok_data(
        await client.get("/api/v1/chats?page_size=100", headers=hub_headers(stranger.token))
    )
    assert isinstance(listing, list)
    assert hub_chat.chat_id not in [entry["id"] for entry in listing]


async def test_ag01_r3_create_returns_user_id_and_prologue(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-01/R3: ``createSession`` (``ragflow.ts:33``) zwraca ``user_id`` z ciała i prolog.

    Prolog (``messages[0]``) to wiadomość asystenta BEZ klucza ``reference``
    (złoto v0.24.0 ``chats___sessions/chat_session--03.json``).
    """
    created = await _create_session(client, hub.token, hub_chat.chat_id)
    assert created["user_id"] == _SESSION_USER_ID
    assert created["id"]
    assert created["name"] == "x"
    assert isinstance(created["update_time"], int)
    assert created["update_time"] > 10**12
    assert created["messages"][0]["role"] == "assistant"
    assert "reference" not in created["messages"][0]


async def test_ag01_list_returns_user_id(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-01/R3: ``listSessions`` (``ragflow.ts:26``) oddaje sesję z ``user_id`` (A3)."""
    created = await _create_session(client, hub.token, hub_chat.chat_id)
    listed = await _sessions(client, hub.token, hub_chat.chat_id)
    session = next(entry for entry in listed if entry["id"] == created["id"])
    assert session["user_id"] == _SESSION_USER_ID


async def test_ag07_completion_without_session_creates_session(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-07: ``getCompletion`` bez ``session_id`` (``ragflow.ts:65``) zakłada sesję.

    Odpowiedź niesie ``session_id`` i ``reference.chunks``; sesja jest widoczna w liście.
    """
    data = ok_data(
        await client.post(
            f"/api/v1/chats/{hub_chat.chat_id}/completions",
            headers=hub_headers(hub.token),
            json={"question": QUESTION, "stream": False},
        )
    )
    session_id = data["session_id"]
    assert session_id
    assert isinstance(data["reference"]["chunks"], list)
    listed = await _sessions(client, hub.token, hub_chat.chat_id)
    assert session_id in [entry["id"] for entry in listed]


async def test_ag08_errors_are_http_200_with_code(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-08: completion do nieistniejącego czatu → HTTP 200 i ``code != 0``, bez ``detail``.

    hub-compat czyta ``res.ok`` i ``json.code`` (``ragflow.ts:65-70``), nie status z ``detail``.
    """
    response = await client.post(
        f"/api/v1/chats/{_MISSING_CHAT}/completions",
        headers=hub_headers(hub.token),
        json={"question": QUESTION, "stream": False},
    )
    assert response.status_code == _HTTP_OK
    body = response.json()
    assert body["code"] != _CODE_SUCCESS
    assert "detail" not in body


async def test_r4_delete_with_json_content_type_only_res_ok(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """R4: ``deleteSessions`` (``ragflow.ts:43``) — DELETE z JSON-em i ``Content-Type``.

    hub-compat sprawdza tylko ``res.ok``; sesja po usunięciu znika z listy.
    """
    created = await _create_session(client, hub.token, hub_chat.chat_id)
    url = f"/api/v1/chats/{hub_chat.chat_id}/sessions"
    response = await client.request(
        "DELETE", url, headers=hub_headers(hub.token), json={"ids": [created["id"]]}
    )
    assert response.status_code == _HTTP_OK
    listed = await _sessions(client, hub.token, hub_chat.chat_id)
    assert created["id"] not in [entry["id"] for entry in listed]


async def test_r3_r4_stranger_denied_on_foreign_chat(
    client: httpx.AsyncClient, owner: HubAccount, stranger: HubAccount, hub_chat: HubChat
) -> None:
    """R3/R4: cudzy czat dla zwykłego konta → odmowa kopertą, nie ``{detail}``.

    Kody i komunikaty ze złota v0.24.0: ``chats___sessions/errors_access--28.json``
    (create: 102 „You do not own the assistant.") i ``--51.json``
    (delete: 102 „You don't own the chat"). Sesje właściciela zostają nietknięte.
    """
    owned = await _create_session(client, owner.token, hub_chat.chat_id, name="owner")
    create = await client.post(
        f"/api/v1/chats/{hub_chat.chat_id}/sessions",
        headers=hub_headers(stranger.token),
        json={"name": "obcy"},
    )
    assert create.status_code == _HTTP_OK
    assert create.json() == {"code": _CODE_DATA_ERROR, "message": "You do not own the assistant."}
    delete = await client.request(
        "DELETE",
        f"/api/v1/chats/{hub_chat.chat_id}/sessions",
        headers=hub_headers(stranger.token),
        json={"ids": [owned["id"]]},
    )
    assert delete.status_code == _HTTP_OK
    assert delete.json() == {"code": _CODE_DATA_ERROR, "message": "You don't own the chat"}
    listed = await _sessions(client, owner.token, hub_chat.chat_id)
    assert owned["id"] in [entry["id"] for entry in listed]


async def test_a9_get_with_content_type_and_empty_body(
    client: httpx.AsyncClient, hub: HubAccount
) -> None:
    """A9: GET z ``Content-Type: application/json`` i pustym ciałem → 200.

    ``hub_headers`` dokłada ``Content-Type`` także do GET (``ragflow.ts:11-16``);
    trasa nie może tego odrzucić.
    """
    response = await client.get("/api/v1/chats?page_size=100", headers=hub_headers(hub.token))
    assert response.status_code == _HTTP_OK
