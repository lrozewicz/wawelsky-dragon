"""Grant czatu przez HTTP (brief T6a, K7 §1.11, 07 §7.2).

A jest właścicielem czatu (klucz Bearer), B drugim użytkownikiem (klucz Bearer).
Bez grantu B nie widzi czatu A i nie rozmawia; po `POST /api/access` widzi i rozmawia
(fake-llm), ale nadal nie może czatu zmienić ani usunąć; po `DELETE /api/access` traci dostęp.
"""

from urllib.parse import quote

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from tests.integration.chat.conftest import chat_with_doc

pytestmark = [
    pytest.mark.db,
    pytest.mark.contract,
    pytest.mark.hub_compat,
    pytest.mark.fakellm,
]

_OK = 200
_CREATED = 201
# Dokument o smoku wawelskim; pytanie zawiera jego słowa (tryb termowy, w=0.0).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_QUESTION = "Gdzie mieszkał smok wawelski?"
# Hasło atrapy (nie jest prawdziwym sekretem), ≥ 8 znaków wg validate_new_password.
_PASSWORD = "Sup3r-secret-pw"  # noqa: S105

# Klucze z POST /api/keys mają compat_profile=ragflow_0_24 (K7 §1.12) — odmowy wg refusals_v024
# (K11 §10d p. 13): chats_completions → 102 "You don't own the chat <id>", chats_update → 102.


async def _user_with_key(svc: httpx.AsyncClient, prefix: str, email: str) -> tuple[str, str]:
    """Konto + klucz SVC; zwraca (token Bearer, id użytkownika)."""
    created = await svc.post(f"{prefix}/api/users", json={"email": email, "password": _PASSWORD})
    assert created.status_code == _CREATED, created.text
    record = (await svc.post(f"{prefix}/api/keys/{quote(email, safe='')}")).json()["data"]
    return str(record["token"]), str(record["tenant_id"])


def _bearer(token: str) -> dict[str, str]:
    """Nagłówek Bearer klucza API."""
    return {"Authorization": f"Bearer {token}"}


def _chat_ids(envelope: httpx.Response) -> list[str]:
    """Id czatów z koperty listy RF (profil 0.24: `data` to lista, nie `data.chats`)."""
    data = envelope.json()["data"]
    return [item["id"] for item in data]


async def test_grant_policy_http(
    svc: httpx.AsyncClient,
    prefix: str,
    container: Container,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """K7 §1.11: grant daje B READ+USE czatu A (lista, sesja, completion), nie UPDATE/DELETE."""
    owner_token, owner_id = await _user_with_key(svc, prefix, "owner@x.pl")
    guest_token, _guest_id = await _user_with_key(svc, prefix, "guest@x.pl")
    chat, _dataset, _doc_id = await chat_with_doc(container, sm, _DOC, owner=owner_id)
    guest_headers = _bearer(guest_token)

    before = await svc.get("/api/v1/chats", headers=guest_headers)
    assert before.status_code == _OK
    assert chat.id not in _chat_ids(before)

    denied = await svc.post(
        f"/api/v1/chats/{chat.id}/completions",
        headers=guest_headers,
        json={"question": _QUESTION, "stream": False},
    )
    assert denied.status_code == _OK
    assert denied.json() == {"code": 102, "message": f"You don't own the chat {chat.id}"}

    granted = await svc.post(
        f"{prefix}/api/access", json={"email": "guest@x.pl", "dialog_id": chat.id}
    )
    assert granted.status_code == _CREATED
    assert granted.json() == {"data": {"ok": True}}

    visible = await svc.get("/api/v1/chats", headers=guest_headers)
    assert chat.id in _chat_ids(visible)

    session = await svc.post(
        f"/api/v1/chats/{chat.id}/sessions", headers=guest_headers, json={"name": "grant"}
    )
    assert session.status_code == _OK
    assert session.json()["code"] == 0
    session_id = str(session.json()["data"]["id"])

    completion = await svc.post(
        f"/api/v1/chats/{chat.id}/completions",
        headers=guest_headers,
        json={"question": _QUESTION, "session_id": session_id, "stream": False},
    )
    assert completion.status_code == _OK
    assert completion.json()["code"] == 0
    assert completion.json()["data"]["session_id"] == session_id

    patched = await svc.patch(
        f"/api/v1/chats/{chat.id}", headers=guest_headers, json={"name": "intruder"}
    )
    assert patched.status_code == _OK
    assert patched.json() == {"code": 102, "message": "You do not own the chat"}

    deleted = await svc.request("DELETE", f"/api/v1/chats/{chat.id}", headers=guest_headers)
    assert deleted.status_code == _OK
    assert deleted.json()["code"] != 0
    owned = await svc.get(f"/api/v1/chats/{chat.id}", headers=_bearer(owner_token))
    assert owned.json()["code"] == 0

    revoked = await svc.request(
        "DELETE", f"{prefix}/api/access", json={"email": "guest@x.pl", "dialog_id": chat.id}
    )
    assert revoked.status_code == _OK
    after = await svc.get("/api/v1/chats", headers=guest_headers)
    assert chat.id not in _chat_ids(after)
