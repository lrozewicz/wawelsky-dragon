"""Testy kontraktowe tras `/api/keys*` (brief T6a, kontrakt C8; AG-11).

Pełny token z `GET`, działanie jako Bearer, usuwanie po tokenie (URL-encoded) i po `id`
oraz ochrona klucza innego użytkownika. Prefiks montażu parametryzuje trasy SVC.
"""

from urllib.parse import quote

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.uow import transaction

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

_OK = 200
_CREATED = 201
_NOT_FOUND = 404
_UNAUTHORIZED = 401

_ANN = "ann%40x.pl"
_BOB = "bob%40x.pl"
# Hasło atrapy (nie jest prawdziwym sekretem), ≥ 8 znaków wg validate_new_password.
_PASSWORD = "Sup3r-secret-pw"  # noqa: S105


async def _create(svc: httpx.AsyncClient, prefix: str, email: str) -> None:
    """POST /api/users z asercją 201 (konto dla trasy kluczy)."""
    response = await svc.post(f"{prefix}/api/users", json={"email": email, "password": _PASSWORD})
    assert response.status_code == _CREATED, response.text


async def _active_key_id(sm: async_sessionmaker[AsyncSession], email: str) -> str:
    """Id jedynego aktywnego klucza konta o danym e-mailu."""
    async with transaction(sm) as session:
        result = await session.execute(
            text(
                "SELECT k.id FROM api_keys k JOIN users u ON u.id = k.user_id"
                " WHERE u.email = :email AND k.revoked_at IS NULL"
            ),
            {"email": email},
        )
    return str(result.scalar_one())


async def test_ag11_full_token_list_and_delete_by_full_token(
    svc: httpx.AsyncClient, prefix: str, sm: async_sessionmaker[AsyncSession]
) -> None:
    """AG-11: pełny token z listy działa jako Bearer; usuwanie po tokenie i po `id`."""
    await _create(svc, prefix, "ann@x.pl")
    created = await svc.post(f"{prefix}/api/keys/{_ANN}")
    assert created.status_code == _CREATED
    token = str(created.json()["data"]["token"])
    assert token.startswith("ragflow-")

    listed = await svc.get(f"{prefix}/api/keys/{_ANN}")
    assert listed.status_code == _OK
    assert [item["token"] for item in listed.json()["data"]] == [token]

    bearer = {"Authorization": f"Bearer {token}"}
    alive = await svc.get("/api/v1/chats", headers=bearer)
    assert alive.status_code == _OK
    assert alive.json()["code"] == 0

    removed = await svc.request("DELETE", f"{prefix}/api/keys/{_ANN}/{quote(token, safe='')}")
    assert removed.status_code == _OK
    assert removed.json() == {"data": {"message": "Key deleted"}}
    assert (await svc.get(f"{prefix}/api/keys/{_ANN}")).json() == {"data": []}
    dead = await svc.get("/api/v1/chats", headers=bearer)
    assert dead.status_code == _UNAUTHORIZED

    await svc.post(f"{prefix}/api/keys/{_ANN}")
    by_id = await svc.request(
        "DELETE", f"{prefix}/api/keys/{_ANN}/{await _active_key_id(sm, 'ann@x.pl')}"
    )
    assert by_id.status_code == _OK
    assert by_id.json() == {"data": {"message": "Key deleted"}}
    assert (await svc.get(f"{prefix}/api/keys/{_ANN}")).json() == {"data": []}


async def test_key_delete_foreign_token_404(svc: httpx.AsyncClient, prefix: str) -> None:
    """AG-11/K7 §1.5: klucz użytkownika B nie da się usunąć przez `/api/keys/{A}/{tokenB}`."""
    await _create(svc, prefix, "ann@x.pl")
    await _create(svc, prefix, "bob@x.pl")
    foreign = str((await svc.post(f"{prefix}/api/keys/{_BOB}")).json()["data"]["token"])

    response = await svc.request("DELETE", f"{prefix}/api/keys/{_ANN}/{quote(foreign, safe='')}")
    assert response.status_code == _NOT_FOUND
    assert response.json() == {"error": "Key not found"}
    still_there = await svc.get(f"{prefix}/api/keys/{_BOB}")
    assert [item["token"] for item in still_there.json()["data"]] == [foreign]
