"""K14 §2 p. 1: wygasły klucz API jest nieodróżnialny od nieistniejącego na każdej ścieżce.

Rodziny uwierzytelniania kluczem z K14 §2 p. 1 — po jednej reprezentatywnej trasie:
``GET /api/v1/users/me`` (profil 0.27), ``GET /api/v1/datasets`` (klucz z profilem 0.24),
``GET /v1/system/version`` (legacy v0.24), ``GET /api/wd/v1/users/{id}/api-keys`` (WD)
oraz ``GET /api/v1/chats`` kluczem konta serwisowego hub-compat (K7 §1.12, 03 §7.3).

Dla każdej trasy ten sam podmiot ma cztery tokeny: wygasły (``expires_at`` w przeszłości),
z terminem w przyszłości, bezterminowy oraz **nieistniejący**. Wymagania: odpowiedź dla klucza
wygasłego jest identyczna (status i treść koperty) z odpowiedzią dla nieistniejącego, a klucz
z przyszłym terminem działa jak bezterminowy. Terminy ustawiamy przy tworzeniu klucza
(``ApiKeyService.create`` z T1) — bez ``sleep`` i bez przesuwania zegara.

Wzorce uwierzytelniania kluczem: ``tests/contract/wd/users/test_api_keys.py`` (klucz WD jako
Bearer) i ``tests/contract/hub_compat/user_api/test_provisioning_flow.py`` (klucz serwisowy).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from app.core.container import Container
from app.domain.policy import Principal

pytestmark = pytest.mark.contract

OK = 200
UNAUTHORIZED = 401
DAY_MS = 86_400_000
# 2001-09-09 — dowolny termin po epoce, na pewno w przeszłości (bez zależności od zegara).
PAST_MS = 1_000_000_000_000
# Token, którego nie ma w bazie; nie ma kształtu JWT WD, więc trafia na ścieżkę klucza API.
UNKNOWN_TOKEN = "ragflow-nie-ma-takiego-klucza"  # noqa: S105


@dataclass(frozen=True)
class Case:
    """Reprezentatywna trasa jednej rodziny uwierzytelniania kluczem (K14 §2 p. 1)."""

    path: str
    email: str
    superuser: bool = False
    service: bool = False
    compat: str | None = None


CASES = [
    pytest.param(Case("/api/v1/users/me", "k14-me@example.com"), id="api-v1-027"),
    pytest.param(
        Case("/api/v1/datasets", "k14-datasets@example.com", compat="ragflow_0_24"),
        id="api-v1-024",
    ),
    pytest.param(Case("/v1/system/version", "k14-legacy@example.com"), id="v1-legacy"),
    pytest.param(
        Case("/api/wd/v1/users/{user_id}/api-keys", "k14-wd@example.com", superuser=True),
        id="wd-admin",
    ),
    pytest.param(
        Case(
            "/api/v1/chats",
            "k14-hub-compat@example.com",
            superuser=True,
            service=True,
            compat="ragflow_0_24",
        ),
        id="hub-compat-k7-service-key",
    ),
]


async def _tokens(
    container: Container, principal: Principal, compat: str | None, now: int
) -> dict[str, str]:
    """Cztery tokeny podmiotu: wygasły, z przyszłym terminem, bezterminowy, nieistniejący."""
    keys = container.api_keys
    assert keys is not None

    async def make(expires_at: int | None) -> str:
        view = await keys.create(principal, compat_profile=compat, expires_at=expires_at)
        return view.token

    return {
        "expired": await make(PAST_MS),
        "future": await make(now + DAY_MS),
        "forever": await make(None),
        "unknown": UNKNOWN_TOKEN,
    }


async def _responses(app: FastAPI, path: str, tokens: dict[str, str]) -> dict[str, httpx.Response]:
    """Odpowiedzi trasy dla każdego tokenu; klient bezstanowy (ASGITransport, bez sieci)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return {
            name: await client.get(path, headers={"Authorization": f"Bearer {token}"})
            for name, token in tokens.items()
        }


@pytest.mark.parametrize("case", CASES)
async def test_expired_key_matches_the_unknown_token(
    app: FastAPI, container: Container, case: Case
) -> None:
    """Wygasły klucz → 401 identyczne z nieistniejącym tokenem; przyszły termin działa (K14 §2)."""
    users = container.users
    assert users is not None
    caller = await users.create(
        email=case.email, password=None, is_superuser=case.superuser, is_service=case.service
    )
    tokens = await _tokens(
        container, users.principal_of(caller), case.compat, container.clock.now_ms()
    )

    path = case.path
    if "{user_id}" in path:
        # Lista kluczy innego konta — odpowiedź nie zależy od ``last_used_at`` klucza wywołującego.
        target = await users.create(email=f"target-{case.email}", password=None)
        path = path.format(user_id=target.id)

    got = await _responses(app, path, tokens)
    expired, unknown = got["expired"], got["unknown"]
    assert unknown.status_code == UNAUTHORIZED, unknown.text
    assert (expired.status_code, expired.json()) == (unknown.status_code, unknown.json())

    future, forever = got["future"], got["forever"]
    assert future.status_code == OK, future.text
    assert (future.status_code, future.json()) == (forever.status_code, forever.json())
