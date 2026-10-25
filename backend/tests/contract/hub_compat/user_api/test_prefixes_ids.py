"""Prefiksy montażu, health i id z migracji: AG-29, AG-30, AG-32 (brief T6b, K7 §1.8).

Każda trasa user-api musi odpowiadać pod `""` i `/user-api` (AG-29); `/api/health` działa
bez uwierzytelniania pod oboma prefiksami (AG-30); id czatów w formacie migracji RAGFlow
(32 znaki hex) przechodzą przez user-api i `/api/v1/chats` bez mapowania (AG-32).
Testy kolekcji tras są parametryzowane fixture'em `prefix`.
"""

from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories import chats as chats_repo
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from tests.integration.ingest.conftest import TIME_MS

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

SeedChat = Callable[[str | None], Awaitable[str]]

_OK = 200
_CREATED = 201
_NOT_FOUND = 404

# Hasło atrapy konta zakładanego w teście (nie jest prawdziwym sekretem).
_PASSWORD = "Secret-pass1"  # noqa: S105
_EMAIL = "ann@x.pl"
_EMAIL_PATH = "ann%40x.pl"
_GHOST_PATH = "ghost%40nowhere.test"
_BOSS_EMAIL = "boss@x.pl"

# Czat o id w formacie migracji RAGFlow (32 hex) — AG-32 (K7 §1.8).
_MIGRATED_ID = "0123456789abcdef0123456789abcdef"
_MIGRATED_NAME = "Asystent po migracji"
_MIGRATOR = "migration"


async def _insert_chat(
    sm: async_sessionmaker[AsyncSession], *, chat_id: str, name: str, tenant_id: str
) -> None:
    """Wstawia czat o zadanym id przez repozytorium (wzorzec `seed_chat` z conftest T5a)."""
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


def _route_cases(chat_id: str) -> list[tuple[str, str, dict[str, object] | None]]:
    """Wszystkie trasy user-api: `(metoda, ścieżka, body)` (C8 — users 8, keys 3, access 4).

    `users` liczy 7 typów operacji (lista, szczegół, create, update, hasło, activate/deactivate,
    delete), tu rozpisanych na 8 wpisów razem z osobnymi trasami `activate` i `deactivate`.
    """
    return [
        ("GET", "/api/users", None),
        ("POST", "/api/users", {"email": _EMAIL, "password": _PASSWORD}),
        ("GET", f"/api/users/{_EMAIL_PATH}", None),
        ("PUT", f"/api/users/{_EMAIL_PATH}", {"nickname": "Ann"}),
        ("PUT", f"/api/users/{_EMAIL_PATH}/password", {"new_password": _PASSWORD}),
        ("PUT", f"/api/users/{_EMAIL_PATH}/activate", None),
        ("PUT", f"/api/users/{_EMAIL_PATH}/deactivate", None),
        ("GET", f"/api/keys/{_EMAIL_PATH}", None),
        ("POST", f"/api/keys/{_EMAIL_PATH}", None),
        ("DELETE", f"/api/keys/{_EMAIL_PATH}/missing-token", None),
        ("GET", f"/api/access?email={_EMAIL_PATH}", None),
        ("PUT", "/api/access", {"email": _EMAIL, "dialog_ids": []}),
        ("POST", "/api/access", {"email": _EMAIL, "dialog_id": chat_id}),
        ("DELETE", "/api/access", {"email": _EMAIL, "dialog_id": chat_id}),
        ("DELETE", f"/api/users/{_EMAIL_PATH}", None),
    ]


async def test_ag29_every_route_under_both_prefixes(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """AG-29: każda trasa user-api odpowiada pod `""` i `/user-api` kopertą SVC, nie fallbackiem.

    Fallback Tras nieznanych pod `""` zwraca kopertę Starlette (`{"detail": ...}`), a pod
    `/user-api` `{"error": "Not found"}` — żadna z tych odpowiedzi nie może się trafić.
    """
    chat_id = await seed_chat(None)
    for method, path, body in _route_cases(chat_id):
        url = f"{prefix}{path}"
        response = await svc.request(method, url, json=body)
        payload = response.json()
        assert payload.get("error") != "Not found", (
            f"{method} {url} trafił w fallback user-api: {response.status_code} {payload!r}"
        )
        assert isinstance(payload, dict) and ("error" in payload or "data" in payload), (
            f"{method} {url} nie trafił w trasę user-api: {response.status_code} {payload!r}"
        )


async def test_ag29_unknown_resource_gives_specific_404(
    svc: httpx.AsyncClient, prefix: str
) -> None:
    """AG-29: nieistniejący zasób daje 404 `User not found`, nie ogólne `Not found`."""
    user = await svc.get(f"{prefix}/api/users/{_GHOST_PATH}")
    assert user.status_code == _NOT_FOUND
    assert user.json() == {"error": "User not found"}
    keys = await svc.get(f"{prefix}/api/keys/{_GHOST_PATH}")
    assert keys.status_code == _NOT_FOUND
    assert keys.json() == {"error": "User not found"}


async def test_ag30_health_both_prefixes_no_auth(anon: httpx.AsyncClient, prefix: str) -> None:
    """AG-30: `/api/health` bez auth i bez koperty → `{"status": "ok"}` (K7 §1.6)."""
    response = await anon.get(f"{prefix}/api/health")
    assert response.status_code == _OK
    assert response.json() == {"status": "ok"}


async def test_ag32_migrated_ids_work(
    svc: httpx.AsyncClient,
    prefix: str,
    container: Container,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """AG-32: czat o id 32-hex z migracji działa w access i `/api/v1/chats` bez mapowania."""
    assert container.users is not None
    assert container.api_keys is not None
    boss = await container.users.create(email=_BOSS_EMAIL, password=_PASSWORD, is_superuser=True)
    key = await container.api_keys.create(container.users.principal_of(boss))
    await _insert_chat(sm, chat_id=_MIGRATED_ID, name=_MIGRATED_NAME, tenant_id=boss.id)

    put = await svc.put(
        f"{prefix}/api/access",
        json={"email": _EMAIL, "dialog_ids": [_MIGRATED_ID], "actor": _MIGRATOR},
    )
    assert put.status_code == _OK
    assert put.json() == {"data": {"email": _EMAIL, "count": 1}}

    got = await svc.get(f"{prefix}/api/access", params={"email": _EMAIL})
    assert got.json()["data"] == {
        "dialog_ids": [_MIGRATED_ID],
        "access": [{"dialog_id": _MIGRATED_ID, "created_by": _MIGRATOR}],
    }

    chats = await svc.get("/api/v1/chats", headers={"Authorization": f"Bearer {key.token}"})
    assert chats.status_code == _OK
    migrated = [item for item in chats.json()["data"]["chats"] if item["id"] == _MIGRATED_ID]
    assert [item["id"] for item in migrated] == [_MIGRATED_ID]

    deleted = await svc.request(
        "DELETE", f"{prefix}/api/access", json={"email": _EMAIL, "dialog_id": _MIGRATED_ID}
    )
    assert deleted.status_code == _OK
    after = await svc.get(f"{prefix}/api/access", params={"email": _EMAIL})
    assert after.json()["data"] == {"dialog_ids": [], "access": []}
