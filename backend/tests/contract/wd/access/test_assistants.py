"""Trasy grantów asystentów WD ``/api/wd/v1/access/assistants`` (brief T4, kontrakt §2, §3, §4).

Wszystkie wiersze tabeli „Przykłady wejście → wyjście" briefu: lista bez grantów i z grantem
(``created_by`` = e-mail administratora), 201 przy nadaniu, 400 dla nieznanego ``chat_id``,
deduplikacja przy ``PUT``, opróżnienie zbioru, idempotentne ``DELETE`` (204 również drugi raz),
400 przy braku ``email``, 401/403 straży administratora oraz wpisy audytu ``access_*``
z ``target_type="access"`` i ``target_id`` = e-mail, bez sekretów.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import chats as chats_repo
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from tests.contract.wd.admin_support import ADMIN_EMAIL, AuditRows, MakeUser
from tests.integration.chat.conftest import seed_user

pytestmark = pytest.mark.contract

OK = 200
CREATED = 201
NO_CONTENT = 204
BAD_REQUEST = 400
UNAUTHORIZED = 401
FORBIDDEN = 403

PATH = "/api/wd/v1/access/assistants"
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
EMAIL = "A@X.com"
NORMALIZED = "a@x.com"
TIME_MS = 1790157600000
_REVOKES = 2  # oba DELETE w teście idempotencji zostawiają wpis audytu


async def _seed_chat(sm: async_sessionmaker[AsyncSession], tenant_id: str) -> str:
    """Wstawia czat przez ``chats_repo.insert``; zwraca jego id (FK ``access.chat_id``)."""
    chat_id = uuid.uuid4().hex
    row = ChatRow(
        id=chat_id,
        tenant_id=tenant_id,
        created_by=tenant_id,
        name=f"Czat testowy {chat_id[:8]}",
        language="Polish",
        llm_id="fake-chat",
        llm_setting={},
        prompt_config={},
        similarity_threshold=0.0,
        vector_similarity_weight=0.3,
        top_n=6,
        top_k=1024,
        rerank_candidates_count=64,
        rerank_id="",
        meta_data_filter=None,
        status="1",
    )
    async with transaction(sm) as session:
        await chats_repo.insert(session, row, now_ms=TIME_MS)
    return chat_id


async def _seed_chats(sm: async_sessionmaker[AsyncSession], count: int = 2) -> list[str]:
    """Zakłada konto-właściciela (FK ``chats.tenant_id``) i ``count`` czatów."""
    owner = await seed_user(sm)
    return [await _seed_chat(sm, owner) for _ in range(count)]


async def _listed(admin: httpx.AsyncClient, email: str = EMAIL) -> list[dict[str, Any]]:
    """``items`` listy grantów e-maila (asercje w testach czytają z tego)."""
    response = await admin.get(PATH, params={"email": email})
    assert response.status_code == OK, response.text
    return response.json()["data"]["items"]


def _body(response: httpx.Response) -> dict[str, Any]:
    """``data`` odpowiedzi (kształt koperty ``{"data": …}`` kontraktu §0 p. 1)."""
    return response.json()["data"]


async def test_list_without_grants_is_empty(admin: httpx.AsyncClient) -> None:
    """E-mail bez grantów → 200 ``{"data": {"items": []}}`` (brief, przykład 1)."""
    response = await admin.get(PATH, params={"email": EMAIL})

    assert response.status_code == OK, response.text
    assert response.json() == {"data": {"items": []}}


async def test_grant_then_list_returns_the_admin_as_created_by(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST nadaje grant (e-mail znormalizowany), GET zwraca ``created_by`` administratora."""
    (chat_id,) = await _seed_chats(sm, 1)

    created = await admin.post(PATH, json={"email": EMAIL, "chat_id": chat_id})
    assert created.status_code == CREATED, created.text
    assert _body(created) == {"email": NORMALIZED, "chat_id": chat_id}

    (item,) = await _listed(admin)
    assert item["chat_id"] == chat_id
    assert item["created_by"] == ADMIN_EMAIL
    assert ISO_RE.match(item["created_at"])


async def test_grant_unknown_chat_is_validation_failed(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieznany ``chat_id`` → 400 ``validation_failed`` (brief, przykład 3)."""
    await _seed_chats(sm, 1)

    response = await admin.post(PATH, json={"email": EMAIL, "chat_id": "nie-ma-takiego"})

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "validation_failed"


async def test_replace_dedupes_and_clears(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT deduplikuje ``chat_ids`` (count = liczba unikalnych), a pusty zbiór czyści granty."""
    chat_1, chat_2 = await _seed_chats(sm, 2)

    replaced = await admin.put(PATH, json={"email": EMAIL, "chat_ids": [chat_1, chat_2, chat_1]})
    assert replaced.status_code == OK, replaced.text
    assert _body(replaced) == {"email": NORMALIZED, "count": 2}
    assert {item["chat_id"] for item in await _listed(admin)} == {chat_1, chat_2}

    cleared = await admin.put(PATH, json={"email": EMAIL, "chat_ids": []})
    assert cleared.status_code == OK, cleared.text
    assert _body(cleared) == {"email": NORMALIZED, "count": 0}
    assert await _listed(admin) == []


async def test_replace_unknown_chat_is_validation_failed(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``PUT`` z nieznanym ``chat_id`` → 400 i stan bez zmian (kontrakt §4)."""
    (chat_1,) = await _seed_chats(sm, 1)
    await admin.put(PATH, json={"email": EMAIL, "chat_ids": [chat_1]})

    response = await admin.put(PATH, json={"email": EMAIL, "chat_ids": [chat_1, "brak"]})

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "validation_failed"
    assert [item["chat_id"] for item in await _listed(admin)] == [chat_1]


async def test_revoke_is_idempotent_and_audits(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession], audit_rows: AuditRows
) -> None:
    """DELETE (204), drugi raz też 204, a wpisy ``access_revoked`` wskazują e-mail i czat."""
    (chat_id,) = await _seed_chats(sm, 1)
    await admin.post(PATH, json={"email": EMAIL, "chat_id": chat_id})
    body = {"email": EMAIL, "chat_id": chat_id}

    first = await admin.request("DELETE", PATH, json=body)
    assert first.status_code == NO_CONTENT, first.text
    assert await _listed(admin) == []

    again = await admin.request("DELETE", PATH, json=body)
    assert again.status_code == NO_CONTENT, again.text

    # Audyt zapisuje każdą próbę odebrania (tak jak SVC), więc oba DELETE zostawiają wpis.
    revoked = await audit_rows("access_revoked")
    assert len(revoked) == _REVOKES
    for entry in revoked:
        assert entry.target_type == "access"
        assert entry.target_id == NORMALIZED
        assert entry.details == {"email": NORMALIZED, "dialog_id": chat_id}
        assert entry.actor_label == ADMIN_EMAIL


async def test_mutations_leave_access_audit_entries(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession], audit_rows: AuditRows
) -> None:
    """``access_granted`` i ``access_replaced`` mają ``target_type="access"`` i ``details`` SVC."""
    chat_1, chat_2 = await _seed_chats(sm, 2)

    await admin.post(PATH, json={"email": EMAIL, "chat_id": chat_1})
    await admin.put(PATH, json={"email": EMAIL, "chat_ids": [chat_2, chat_1]})

    (granted,) = await audit_rows("access_granted")
    assert granted.target_type == "access"
    assert granted.target_id == NORMALIZED
    assert granted.details == {"email": NORMALIZED, "dialog_id": chat_1}

    (replaced,) = await audit_rows("access_replaced")
    assert replaced.target_type == "access"
    assert replaced.target_id == NORMALIZED
    assert replaced.details == {"email": NORMALIZED, "count": 2, "dialog_ids": [chat_2, chat_1]}


async def test_missing_email_in_query_is_validation_failed(admin: httpx.AsyncClient) -> None:
    """``GET`` bez ``email`` → 400 ``validation_failed``, nigdy 422 (brief, przykład 7)."""
    response = await admin.get(PATH)

    assert response.status_code == BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "validation_failed"


async def test_empty_email_in_body_is_validation_failed(admin: httpx.AsyncClient) -> None:
    """Puste ``email``/``chat_id`` w ciele → 400 z modelu żądania (kontrakt §3)."""
    for payload in ({"email": "", "chat_id": "c1"}, {"email": EMAIL, "chat_id": ""}):
        response = await admin.post(PATH, json=payload)
        assert response.status_code == BAD_REQUEST, (payload, response.text)
        assert response.json()["error"]["code"] == "validation_failed"


async def test_routes_require_admin(
    anon: httpx.AsyncClient, member: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Bez nagłówka → 401, zwykły użytkownik → 403 na każdej z czterech tras (kontrakt §0 p. 2)."""
    await make_user("access-guard@example.com")
    body: dict[str, object] = {"email": EMAIL, "chat_id": "c1"}
    routes: Sequence[tuple[str, dict[str, object] | None]] = (
        ("GET", None),
        ("PUT", {"email": EMAIL, "chat_ids": ["c1"]}),
        ("POST", body),
        ("DELETE", body),
    )
    for method, payload in routes:
        unauth = await anon.request(method, PATH, json=payload)
        assert unauth.status_code == UNAUTHORIZED, (method, unauth.text)
        forbidden = await member.request(method, PATH, json=payload)
        assert forbidden.status_code == FORBIDDEN, (method, forbidden.text)
