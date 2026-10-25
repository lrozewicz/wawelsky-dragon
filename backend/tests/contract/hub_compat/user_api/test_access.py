"""Trasy `/api/access` powierzchni hub-compat: AG-12, AG-13, AG-14, AG-17 (kontrakt C8, K7 §1).

Każdy test parametryzowany po prefiksie montażu (`""`, `"/user-api"`).
"""

from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import audit_log as audit_repo
from app.db.uow import transaction

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

SeedChat = Callable[[str | None], Awaitable[str]]

_OK = 200
_CREATED = 201
_BAD_REQUEST = 400
_METHOD_NOT_ALLOWED = 405

_EMAIL = "a@x.pl"
_UNKNOWN_EMAIL = "ghost@nowhere.test"
_MISSING_DIALOG = "f" * 32


def _url(prefix: str) -> str:
    """Adres kolekcji grantów pod danym prefiksem."""
    return f"{prefix}/api/access"


async def _audit(sm: async_sessionmaker[AsyncSession], action: str) -> list[audit_repo.AuditRow]:
    """Wpisy audytu danej akcji, kolejność wstawienia (kontrakt C3)."""
    async with transaction(sm) as session:
        return await audit_repo.list_by_action(session, action)


async def test_put_then_get_returns_access_rows(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """AG-12: PUT zastępuje zbiór (`count` po deduplikacji), GET zwraca `access[]`."""
    chat_id = await seed_chat(None)
    put = await svc.put(
        _url(prefix), json={"email": _EMAIL, "dialog_ids": [chat_id, chat_id], "actor": "adm"}
    )
    assert put.status_code == _OK
    assert put.json() == {"data": {"email": _EMAIL, "count": 1}}
    got = await svc.get(_url(prefix), params={"email": _EMAIL})
    assert got.status_code == _OK
    assert got.json() == {
        "data": {
            "dialog_ids": [chat_id],
            "access": [{"dialog_id": chat_id, "created_by": "adm"}],
        }
    }


async def test_put_lowercases_email_and_get_finds_it(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """AG-17 (access): `A@B.PL` zapisany lowercase, GET `?email=a%40B.pl` go znajduje."""
    chat_id = await seed_chat(None)
    put = await svc.put(_url(prefix), json={"email": "A@B.PL", "dialog_ids": [chat_id]})
    assert put.json() == {"data": {"email": "a@b.pl", "count": 1}}
    got = await svc.get(f"{_url(prefix)}?email=a%40B.pl")
    assert got.status_code == _OK
    assert got.json()["data"]["dialog_ids"] == [chat_id]


async def test_email_without_account_works(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """AG-13: GET/PUT/POST/DELETE działają dla e-maila bez konta w `users`."""
    chat_id = await seed_chat(None)
    put = await svc.put(_url(prefix), json={"email": _UNKNOWN_EMAIL, "dialog_ids": [chat_id]})
    assert put.status_code == _OK
    got = await svc.get(_url(prefix), params={"email": _UNKNOWN_EMAIL})
    assert got.json()["data"]["dialog_ids"] == [chat_id]
    post = await svc.post(_url(prefix), json={"email": _UNKNOWN_EMAIL, "dialog_id": chat_id})
    assert post.status_code == _CREATED
    deleted = await svc.request(
        "DELETE", _url(prefix), json={"email": _UNKNOWN_EMAIL, "dialog_id": chat_id}
    )
    assert deleted.status_code == _OK
    assert deleted.json() == {"data": {"ok": True}}
    after = await svc.get(_url(prefix), params={"email": _UNKNOWN_EMAIL})
    assert after.json()["data"] == {"dialog_ids": [], "access": []}


async def test_post_is_idempotent_and_keeps_created_by(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """AG-14: POST zawsze 201, powtórzenie nie nadpisuje `created_by`."""
    chat_id = await seed_chat(None)
    await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": [chat_id], "actor": "adm"})
    payload = {"email": _EMAIL, "dialog_id": chat_id, "actor": "o"}
    first = await svc.post(_url(prefix), json=payload)
    second = await svc.post(_url(prefix), json=payload)
    assert first.status_code == _CREATED
    assert first.json() == {"data": {"ok": True}}
    assert second.status_code == _CREATED
    got = await svc.get(_url(prefix), params={"email": _EMAIL})
    assert got.json()["data"]["access"] == [{"dialog_id": chat_id, "created_by": "adm"}]


async def test_unknown_dialog_id_rejected_and_nothing_saved(
    svc: httpx.AsyncClient, prefix: str
) -> None:
    """AG-12/K7 §1.3: nieistniejący czat → 400 i brak zapisu (PUT oraz POST)."""
    put = await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": [_MISSING_DIALOG]})
    assert put.status_code == _BAD_REQUEST
    assert put.json() == {"error": f"Unknown dialog_ids: {_MISSING_DIALOG}"}
    got = await svc.get(_url(prefix), params={"email": _EMAIL})
    assert got.json()["data"] == {"dialog_ids": [], "access": []}
    post = await svc.post(_url(prefix), json={"email": _EMAIL, "dialog_id": _MISSING_DIALOG})
    assert post.status_code == _BAD_REQUEST
    assert post.json() == {"error": f"Unknown dialog_ids: {_MISSING_DIALOG}"}


async def test_put_replaces_whole_set(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """K7 §1.1: PUT zastępuje cały zbiór, także wiersze już istniejące."""
    first_chat = await seed_chat(None)
    second_chat = await seed_chat(None)
    await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": [first_chat, second_chat]})
    replaced = await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": [second_chat]})
    assert replaced.json() == {"data": {"email": _EMAIL, "count": 1}}
    got = await svc.get(_url(prefix), params={"email": _EMAIL})
    assert got.json()["data"]["dialog_ids"] == [second_chat]


async def test_put_empty_list_clears_set(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """K7 §1.1: PUT z pustą listą czyści zbiór grantów."""
    chat_id = await seed_chat(None)
    await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": [chat_id]})
    cleared = await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": []})
    assert cleared.json() == {"data": {"email": _EMAIL, "count": 0}}
    got = await svc.get(_url(prefix), params={"email": _EMAIL})
    assert got.json()["data"] == {"dialog_ids": [], "access": []}


async def test_delete_missing_grant_is_ok(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """K7 §1.3/C3: DELETE nieistniejącego grantu → 200 (bez błędu)."""
    chat_id = await seed_chat(None)
    deleted = await svc.request(
        "DELETE", _url(prefix), json={"email": _UNKNOWN_EMAIL, "dialog_id": chat_id}
    )
    assert deleted.status_code == _OK
    assert deleted.json() == {"data": {"ok": True}}


async def test_unknown_method_on_access_is_405(svc: httpx.AsyncClient, prefix: str) -> None:
    """K7 §1.6: zła metoda na `/api/access` → 405 `{"error": "Method not allowed"}`."""
    response = await svc.patch(_url(prefix))
    assert response.status_code == _METHOD_NOT_ALLOWED
    assert response.json() == {"error": "Method not allowed"}


async def test_get_without_email_is_400(svc: httpx.AsyncClient, prefix: str) -> None:
    """C8: brak `email` w GET → 400 `email is required`."""
    response = await svc.get(_url(prefix))
    assert response.status_code == _BAD_REQUEST
    assert response.json() == {"error": "email is required"}


async def test_put_without_email_is_400(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """Wymaganie 3: brak `email` w PUT → 400 z komunikatem o wymaganych polach."""
    chat_id = await seed_chat(None)
    response = await svc.put(_url(prefix), json={"dialog_ids": [chat_id]})
    assert response.status_code == _BAD_REQUEST
    assert response.json() == {"error": "email and dialog_ids (array) are required"}


@pytest.mark.parametrize("dialog_ids", [[""], [7], [{"a": 1}], "abc", None])
async def test_put_requires_string_dialog_ids(
    svc: httpx.AsyncClient, prefix: str, dialog_ids: object
) -> None:
    """Wymaganie 3: nie-string albo pusty string w `dialog_ids` → 400."""
    response = await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": dialog_ids})
    assert response.status_code == _BAD_REQUEST
    assert response.json() == {"error": "email and dialog_ids (array) are required"}


@pytest.mark.parametrize("body", [{"email": _EMAIL}, {"dialog_id": "x"}, {}])
async def test_post_and_delete_require_fields(
    svc: httpx.AsyncClient, prefix: str, body: dict[str, object]
) -> None:
    """C8: POST/DELETE bez `email` lub `dialog_id` → 400."""
    post = await svc.post(_url(prefix), json=body)
    assert post.status_code == _BAD_REQUEST
    assert post.json() == {"error": "email and dialog_id are required"}
    deleted = await svc.request("DELETE", _url(prefix), json=body)
    assert deleted.status_code == _BAD_REQUEST
    assert deleted.json() == {"error": "email and dialog_id are required"}


async def test_audit_rows_for_replace_grant_revoke(
    svc: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession], prefix: str, seed_chat: SeedChat
) -> None:
    """Wymaganie 2: każda mutacja zapisuje wpis audytu z aktorem z body (C3, C8)."""
    first_chat = await seed_chat(None)
    second_chat = await seed_chat(None)
    await svc.put(
        _url(prefix), json={"email": "A@X.pl", "dialog_ids": [first_chat], "actor": "adm"}
    )
    await svc.post(_url(prefix), json={"email": "A@X.pl", "dialog_id": second_chat, "actor": "adm"})
    await svc.request(
        "DELETE", _url(prefix), json={"email": "A@X.pl", "dialog_id": second_chat, "actor": "adm"}
    )
    replaced = await _audit(sm, "access_replaced")
    granted = await _audit(sm, "access_granted")
    revoked = await _audit(sm, "access_revoked")
    assert replaced[0].actor_label == "adm"
    assert replaced[0].target_type == "access"
    assert replaced[0].target_id == _EMAIL
    assert replaced[0].details == {"email": _EMAIL, "count": 1, "dialog_ids": [first_chat]}
    assert granted[0].target_id == _EMAIL
    assert granted[0].details == {"email": _EMAIL, "dialog_id": second_chat}
    assert revoked[0].details == {"email": _EMAIL, "dialog_id": second_chat}


async def test_audit_actor_defaults_to_secret_header(
    svc: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession], prefix: str, seed_chat: SeedChat
) -> None:
    """K7 §1.10: brak `actor` w body → `actor_label` = `X-API-Secret`."""
    chat_id = await seed_chat(None)
    await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": [chat_id]})
    replaced = await _audit(sm, "access_replaced")
    assert replaced[0].actor_label == "X-API-Secret"


async def test_failed_mutation_writes_no_audit(
    svc: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession], prefix: str
) -> None:
    """C8: audyt zapisywany po udanej mutacji — błąd nie zostawia wpisu."""
    await svc.put(_url(prefix), json={"email": _EMAIL, "dialog_ids": [_MISSING_DIALOG]})
    assert await _audit(sm, "access_replaced") == []
