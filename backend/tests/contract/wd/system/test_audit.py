"""Trasa dziennika audytu WD ``/api/wd/v1/audit`` (brief T4, kontrakt §2, §4).

Wiersze tabeli „Przykłady wejście → wyjście" briefu: ``Page`` z najnowszym wpisem pierwszym
i ``actor`` = e-mail administratora, filtry ``action``/``actor`` (bez rozróżniania wielkości
liter), ``from``/``to`` (ISO, bez strefy = UTC; ``from`` > ``to`` → 400; śmieć → 400),
``page_size=101`` → 400 **bez clampu**, paginacja oraz redakcja ``details`` (klucze
``password|token|secret`` nie pojawiają się ani w kluczach, ani w treści odpowiedzi).
Każda odpowiedź 400 to ``validation_failed`` (nigdy 422; kontrakt §0 p. 3).
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import audit_log as audit_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from tests.contract.wd.admin_support import ADMIN_EMAIL, MakeUser
from tests.integration.chat.conftest import seed_user

pytestmark = pytest.mark.contract

OK = 200
CREATED = 201
NO_CONTENT = 204
BAD_REQUEST = 400
UNAUTHORIZED = 401
FORBIDDEN = 403

AUDIT_PATH = "/api/wd/v1/audit"
ACCESS_PATH = "/api/wd/v1/access/assistants"
ENTRY_KEYS = frozenset(
    {"id", "ts", "actor_id", "actor", "action", "target_type", "target_id", "details", "ip"}
)
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
EMAIL = "audit@x.com"
TIME_MS = 1790157600000
SECRET_VALUE = "tajne-haslo"  # noqa: S105 — wartość testowa sprawdzana w redakcji
MUTATIONS = 3  # tyle wpisów audytu zostawia `_mutations`
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
SECOND_PAGE = 2


async def _seed_chat(sm: async_sessionmaker[AsyncSession]) -> str:
    """Wstawia konto-właściciela i czat; zwraca id czatu (potrzebne do grantów)."""
    owner = await seed_user(sm)
    chat_id = uuid.uuid4().hex
    row = ChatRow(
        id=chat_id,
        tenant_id=owner,
        created_by=owner,
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


async def _mutations(admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]) -> None:
    """Trzy mutacje grantów: ``access_granted``, ``access_replaced`` i ``access_revoked``."""
    chat_id = await _seed_chat(sm)
    body = {"email": EMAIL, "chat_id": chat_id}
    assert (await admin.post(ACCESS_PATH, json=body)).status_code == CREATED
    assert (await admin.put(ACCESS_PATH, json={"email": EMAIL, "chat_ids": []})).status_code == OK
    assert (await admin.request("DELETE", ACCESS_PATH, json=body)).status_code == NO_CONTENT


async def _page(response: httpx.Response) -> dict[str, Any]:
    """``data`` odpowiedzi ``GET /audit`` (kształt ``Page`` kontraktu §3)."""
    assert response.status_code == OK, response.text
    return response.json()["data"]


async def test_audit_page_is_newest_first_and_attributed_to_the_admin(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Po mutacjach: ``Page``, najnowszy pierwszy, ``actor`` = e-mail administratora."""
    await _mutations(admin, sm)

    page = await _page(await admin.get(AUDIT_PATH))

    assert page["total"] == MUTATIONS
    assert page["page"] == 1
    assert page["page_size"] == DEFAULT_PAGE_SIZE
    ids = [item["id"] for item in page["items"]]
    assert ids == sorted(ids, reverse=True)
    assert [item["action"] for item in page["items"]] == [
        "access_revoked",
        "access_replaced",
        "access_granted",
    ]
    for item in page["items"]:
        assert set(item) == ENTRY_KEYS
        assert item["actor"] == ADMIN_EMAIL
        assert item["target_type"] == "access"
        assert item["target_id"] == EMAIL
        assert ISO_RE.match(item["ts"])


async def test_action_and_actor_filters(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``?action=`` i ``?actor=`` (bez wielkości liter) zawężają wynik do pasujących wpisów."""
    await _mutations(admin, sm)

    granted = await _page(await admin.get(AUDIT_PATH, params={"action": "access_granted"}))
    assert granted["total"] == 1
    assert [item["action"] for item in granted["items"]] == ["access_granted"]

    matching = await _page(await admin.get(AUDIT_PATH, params={"actor": ADMIN_EMAIL.upper()}))
    assert matching["total"] == MUTATIONS

    stranger = await _page(await admin.get(AUDIT_PATH, params={"actor": "ktos@inny.pl"}))
    assert stranger["total"] == 0
    assert stranger["items"] == []


async def test_from_to_window_and_invalid_values(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``from``/``to`` ISO zawężają przedział; śmieć i ``from`` > ``to`` → 400 (kontrakt §4)."""
    await _mutations(admin, sm)
    page = await _page(await admin.get(AUDIT_PATH))
    oldest_ts = page["items"][-1]["ts"]

    window = await _page(await admin.get(AUDIT_PATH, params={"from": oldest_ts, "to": oldest_ts}))
    assert window["total"] == 1
    assert window["items"][0]["id"] == page["items"][-1]["id"]

    invalid = await admin.get(AUDIT_PATH, params={"from": "zle"})
    assert invalid.status_code == BAD_REQUEST, invalid.text
    assert invalid.json()["error"]["code"] == "validation_failed"

    reversed_window = await admin.get(AUDIT_PATH, params={"from": "2999-01-01", "to": "2000-01-01"})
    assert reversed_window.status_code == BAD_REQUEST, reversed_window.text
    assert reversed_window.json()["error"]["code"] == "validation_failed"


async def test_page_size_is_not_clamped(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``page_size=101`` → 400 (bez clampu), ``page_size=100`` przechodzi, ``page=2`` stronicuje."""
    await _mutations(admin, sm)

    too_big = await admin.get(AUDIT_PATH, params={"page_size": MAX_PAGE_SIZE + 1})
    assert too_big.status_code == BAD_REQUEST, too_big.text
    assert too_big.json()["error"]["code"] == "validation_failed"

    boundary = await _page(await admin.get(AUDIT_PATH, params={"page_size": MAX_PAGE_SIZE}))
    assert boundary["page_size"] == MAX_PAGE_SIZE

    second = await _page(await admin.get(AUDIT_PATH, params={"page_size": 1, "page": SECOND_PAGE}))
    assert second["page"] == SECOND_PAGE
    assert second["page_size"] == 1
    assert second["total"] == MUTATIONS
    assert len(second["items"]) == 1
    assert second["items"][0]["action"] == "access_replaced"


async def test_sensitive_detail_keys_are_redacted_from_the_response(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wpis z ``new_password``/``token``/``api_secret`` nie ujawnia ich (kontrakt §4)."""
    details = {
        "email": EMAIL,
        "new_password": SECRET_VALUE,
        "API_Token": "tok-123",
        "nested": {"api_secret": "sekret", "count": 1},
    }
    async with transaction(sm) as session:
        await audit_repo.insert(
            session,
            ts=TIME_MS,
            actor_id=None,
            actor_label=ADMIN_EMAIL,
            action="access_granted",
            target_type="access",
            target_id=EMAIL,
            details_json=json.dumps(details),
            ip=None,
        )

    response = await admin.get(AUDIT_PATH, params={"action": "access_granted"})

    page = await _page(response)
    (item,) = page["items"]
    assert item["details"] == {"email": EMAIL, "nested": {"count": 1}}
    assert SECRET_VALUE not in response.text
    assert "tok-123" not in response.text
    assert "sekret" not in response.text


async def test_routes_require_admin(
    anon: httpx.AsyncClient, member: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """Bez nagłówka → 401, zwykły użytkownik → 403 (kontrakt §0 p. 2)."""
    await make_user("audit-guard@example.com")

    unauthorized = await anon.get(AUDIT_PATH)
    assert unauthorized.status_code == UNAUTHORIZED, unauthorized.text
    forbidden = await member.get(AUDIT_PATH)
    assert forbidden.status_code == FORBIDDEN, forbidden.text
