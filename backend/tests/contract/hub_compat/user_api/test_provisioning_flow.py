"""Przepływ auto-provisioningu hub-compat (03 §7.3, K7 §1.11; brief T6b).

Test odtwarza sekwencję klienta hub-compat: brak konta → `POST /api/users` (losowe 32-znakowe hasło,
`role:"user"`, `nickname` = część lokalna), rozwiązanie nazw asystentów przez `GET /api/v1/chats`
(trim, case-insensitive), `POST /api/access` z `actor:"hub-compat-auto-provisioning"`, ręczny grant
admina przez `PUT /api/access`, rekoncyliację przez `DELETE /api/access`. Na końcu użytkownik
z grantem widzi na `GET /api/v1/chats` dokładnie czat z grantem.
"""

import secrets
import uuid
from urllib.parse import quote

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories import chats as chats_repo
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from tests.integration.ingest.conftest import TIME_MS

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

_OK = 200
_CREATED = 201

# Hasło atrapy konta serwisowego (nie jest prawdziwym sekretem).
_SVC_PASSWORD = "Service-pass1"  # noqa: S105

_SVC_EMAIL = "hub-compat-service@example.com"
_TARGET_EMAIL = "rezerwator@example.com"
_TARGET_NICKNAME = "rezerwator"
_ACTOR = "hub-compat-auto-provisioning"
_ADMIN_ACTOR = "admin@x"
_CHAT_SALES = "Asystent Sprzedaży"
_CHAT_MARKETING = "Asystent Marketingu"


async def _insert_chat(
    sm: async_sessionmaker[AsyncSession], *, chat_id: str, name: str, tenant_id: str
) -> None:
    """Wstawia czat o zadanej nazwie przez repozytorium (wzorzec `seed_chat` z conftest T5a)."""
    row = ChatRow(
        id=chat_id,
        tenant_id=tenant_id,
        created_by=tenant_id,
        name=name,
        language="Polish",
        llm_id="fake-chat",
        llm_setting={"temperature": 0.1, "max_tokens": 512},
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


async def _chats(svc: httpx.AsyncClient, token: str) -> list[dict[str, object]]:
    """Czaty z `/api/v1/chats` kluczem Bearer.

    Profil 0.24 (klucz z `POST /api/keys`): `data` jest listą. Profil 0.27 (klucz serwisowy
    bez `compat_profile`): `data` to koperta `{"chats": [...]}`, więc bierzemy `data.chats`.
    """
    response = await svc.get("/api/v1/chats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == _OK
    data = response.json()["data"]
    return data if isinstance(data, list) else data["chats"]


async def _access(svc: httpx.AsyncClient, prefix: str, email: str) -> list[dict[str, object]]:
    """Wiersze `access[]` z `GET /api/access?email=`."""
    got = await svc.get(f"{prefix}/api/access", params={"email": email})
    assert got.status_code == _OK
    return got.json()["data"]["access"]


def _by_dialog(rows: list[dict[str, object]]) -> dict[str, object]:
    """Mapa `dialog_id → created_by` (kolejność nieistotna)."""
    return {str(row["dialog_id"]): row["created_by"] for row in rows}


def _resolve(chats: list[dict[str, object]], wanted: str) -> str:
    """Rozwiązanie nazwy asystenta: trim + case-insensitive (03 §7.3 p. 2)."""
    target = wanted.strip().casefold()
    for chat in chats:
        name = chat["name"]
        assert isinstance(name, str)
        if name.strip().casefold() == target:
            return str(chat["id"])
    raise AssertionError(f"brak czatu o nazwie {wanted!r}: {[c['name'] for c in chats]}")


async def test_provisioning_flow(
    svc: httpx.AsyncClient,
    prefix: str,
    container: Container,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Sekwencja hub-compat (03 §7.3): konto → czaty → granty → rekoncyliacja → widoczność."""
    assert container.users is not None
    assert container.api_keys is not None
    service = await container.users.create(
        email=_SVC_EMAIL, password=_SVC_PASSWORD, is_superuser=True, is_service=True
    )
    service_key = await container.api_keys.create(container.users.principal_of(service))

    sales = uuid.uuid4().hex
    marketing = uuid.uuid4().hex
    await _insert_chat(sm, chat_id=sales, name=_CHAT_SALES, tenant_id=service.id)
    await _insert_chat(sm, chat_id=marketing, name=_CHAT_MARKETING, tenant_id=service.id)

    # (1) konto jeszcze nie istnieje → zakładamy je losowym hasłem (32 znaki)
    listed = await svc.get(f"{prefix}/api/users")
    assert listed.status_code == _OK
    assert _TARGET_EMAIL not in [item["email"] for item in listed.json()["data"]]

    created = await svc.post(
        f"{prefix}/api/users",
        json={
            "email": _TARGET_EMAIL,
            "password": secrets.token_urlsafe(24),
            "nickname": _TARGET_NICKNAME,
            "role": "user",
        },
    )
    assert created.status_code == _CREATED
    detail = created.json()["data"]
    assert detail["email"] == _TARGET_EMAIL
    assert detail["nickname"] == _TARGET_NICKNAME
    assert detail["is_superuser"] is False

    # (2) rozwiązanie nazw asystentów kluczem serwisowym (superuser widzi wszystkie czaty)
    chats = await _chats(svc, service_key.token)
    names = [chat["name"] for chat in chats]
    assert _CHAT_SALES in names
    assert _CHAT_MARKETING in names
    sales_id = _resolve(chats, _CHAT_SALES)
    marketing_id = _resolve(chats, _CHAT_MARKETING)
    assert [sales_id, marketing_id] == [sales, marketing]
    # trim + case-insensitive po stronie klienta (03 §7.3 p. 2)
    assert _resolve(chats, f"  {_CHAT_SALES.upper()}  ") == sales

    # (3) auto-granty dla obu czatów; powtórzenie POST nie nadpisuje created_by
    access_url = f"{prefix}/api/access"
    for chat_id in (sales_id, marketing_id):
        granted = await svc.post(
            access_url, json={"email": _TARGET_EMAIL, "dialog_id": chat_id, "actor": _ACTOR}
        )
        assert granted.status_code == _CREATED
        assert granted.json() == {"data": {"ok": True}}
    for chat_id in (sales_id, marketing_id):
        repeated = await svc.post(
            access_url, json={"email": _TARGET_EMAIL, "dialog_id": chat_id, "actor": _ACTOR}
        )
        assert repeated.status_code == _CREATED
    assert _by_dialog(await _access(svc, prefix, _TARGET_EMAIL)) == {
        sales_id: _ACTOR,
        marketing_id: _ACTOR,
    }

    # (4) ręczny grant admina zastępuje cały zbiór; potem auto-grant drugiego czatu
    replaced = await svc.put(
        access_url, json={"email": _TARGET_EMAIL, "dialog_ids": [sales_id], "actor": _ADMIN_ACTOR}
    )
    assert replaced.status_code == _OK
    assert replaced.json() == {"data": {"email": _TARGET_EMAIL, "count": 1}}
    assert _by_dialog(await _access(svc, prefix, _TARGET_EMAIL)) == {sales_id: _ADMIN_ACTOR}

    regrant = await svc.post(
        access_url, json={"email": _TARGET_EMAIL, "dialog_id": marketing_id, "actor": _ACTOR}
    )
    assert regrant.status_code == _CREATED

    # (5) rekoncyliacja: usuwamy wiersze zostawione przez auto-provisioning
    for row in await _access(svc, prefix, _TARGET_EMAIL):
        if row["created_by"] == _ACTOR:
            deleted = await svc.request(
                "DELETE",
                access_url,
                json={"email": _TARGET_EMAIL, "dialog_id": row["dialog_id"]},
            )
            assert deleted.status_code == _OK
    remaining = await svc.get(f"{prefix}/api/access", params={"email": _TARGET_EMAIL})
    assert remaining.json()["data"]["access"] == [
        {"dialog_id": sales_id, "created_by": _ADMIN_ACTOR}
    ]

    # (6) użytkownik z grantem widzi dokładnie czat z grantem
    key = await svc.post(f"{prefix}/api/keys/{quote(_TARGET_EMAIL, safe='')}")
    assert key.status_code == _CREATED
    token = key.json()["data"]["token"]
    visible = await _chats(svc, token)
    assert [chat["id"] for chat in visible] == [sales_id]
