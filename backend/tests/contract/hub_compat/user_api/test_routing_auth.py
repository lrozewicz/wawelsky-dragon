"""Montaż prefiksów, health i uwierzytelnianie SVC: AG-29, AG-30, AG-31 (K7 §1.6-1.8).

Testy kolekcji tras są parametryzowane po prefiksie fixture'em `prefix`.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.core.config import Settings
from app.core.container import Container
from app.main import create_app
from tests.integration.ingest.pipeline_helpers import make_container

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

SeedChat = Callable[[str | None], Awaitable[str]]

# Ten sam sekret co fixture `settings` w conftest.py (K7 §1.7).
SVC_SECRET = "test-secret"  # noqa: S105

_OK = 200
_CREATED = 201
_BAD_REQUEST = 400
_UNAUTHORIZED = 401
_NOT_FOUND = 404

# Hasło atrapy konta zakładanego w teście klucza RF (nie jest prawdziwym sekretem).
PASSWORD = "Secret-pass1"  # noqa: S105


async def _client(app: FastAPI, headers: dict[str, str]) -> httpx.AsyncClient:
    """Klient ASGI na aplikacji z podanymi nagłówkami domyślnymi."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)


@pytest.fixture
async def empty_secret_client(
    settings: Settings, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Aplikacja z pustym `WD_HUB_COMPAT_API_SECRET` (K7 §1.7: 401 wszędzie poza health)."""
    empty = settings.model_copy(update={"hub_compat_api_secret": SecretStr("")})
    container = await make_container(empty, tmp_path)
    try:
        async with await _client(create_app(empty, container), {"X-API-Secret": ""}) as client:
            yield client
    finally:
        await container.aclose()


@pytest.fixture
async def disabled_routes_client(
    settings: Settings, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Aplikacja z `hub_compat_routes=False` — trasy SVC nie są montowane (C7)."""
    disabled = settings.model_copy(update={"hub_compat_routes": False})
    container = await make_container(disabled, tmp_path)
    try:
        headers = {"X-API-Secret": SVC_SECRET}
        async with await _client(create_app(disabled, container), headers) as client:
            yield client
    finally:
        await container.aclose()


async def test_access_routes_available_under_both_prefixes(
    svc: httpx.AsyncClient, prefix: str, seed_chat: SeedChat
) -> None:
    """AG-29: trasy `/api/access` odpowiadają pod `""` i `/user-api` (nie 404)."""
    chat_id = await seed_chat(None)
    url = f"{prefix}/api/access"
    put = await svc.put(url, json={"email": "a@x.pl", "dialog_ids": [chat_id]})
    post = await svc.post(url, json={"email": "a@x.pl", "dialog_id": chat_id})
    got = await svc.get(url, params={"email": "a@x.pl"})
    deleted = await svc.request("DELETE", url, json={"email": "a@x.pl", "dialog_id": chat_id})
    assert [put.status_code, got.status_code, deleted.status_code] == [_OK, _OK, _OK]
    assert post.status_code == _CREATED


async def test_health_without_secret(anon: httpx.AsyncClient, prefix: str) -> None:
    """AG-30: `/api/health` → 200 `{"status": "ok"}` bez nagłówka i bez koperty."""
    response = await anon.get(f"{prefix}/api/health")
    assert response.status_code == _OK
    assert response.json() == {"status": "ok"}


async def test_health_ignores_wrong_secret(app: FastAPI, prefix: str) -> None:
    """AG-30/K7 §1.6: health nie sprawdza `X-API-Secret`."""
    async with await _client(app, {"X-API-Secret": "zly"}) as client:
        response = await client.get(f"{prefix}/api/health")
    assert response.status_code == _OK
    assert response.json() == {"status": "ok"}


async def test_access_requires_secret(anon: httpx.AsyncClient, prefix: str) -> None:
    """AG-31: `GET /api/access` bez nagłówka → 401 `{"error": "Unauthorized"}`."""
    response = await anon.get(f"{prefix}/api/access", params={"email": "x@x.pl"})
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == {"error": "Unauthorized"}


async def test_access_rejects_wrong_secret(app: FastAPI, prefix: str) -> None:
    """AG-31: `GET /api/access` ze złym sekretem → 401 koperty SVC."""
    async with await _client(app, {"X-API-Secret": "zly"}) as client:
        response = await client.get(f"{prefix}/api/access", params={"email": "x@x.pl"})
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == {"error": "Unauthorized"}


async def test_empty_secret_rejects_everything(
    empty_secret_client: httpx.AsyncClient, prefix: str
) -> None:
    """K7 §1.7: pusty sekret w Settings ⇒ 401 także z pustym nagłówkiem; health działa."""
    rejected = await empty_secret_client.get(f"{prefix}/api/access", params={"email": "x@x.pl"})
    assert rejected.status_code == _UNAUTHORIZED
    assert rejected.json() == {"error": "Unauthorized"}
    health = await empty_secret_client.get(f"{prefix}/api/health")
    assert health.status_code == _OK
    assert health.json() == {"status": "ok"}


async def test_unknown_route_under_user_api(
    svc: httpx.AsyncClient, anon: httpx.AsyncClient
) -> None:
    """AG-31: nieznana trasa pod `/user-api` → 404 z sekretem, 401 bez sekretu."""
    with_secret = await svc.get("/user-api/api/foo")
    assert with_secret.status_code == _NOT_FOUND
    assert with_secret.json() == {"error": "Not found"}
    without_secret = await anon.get("/user-api/api/foo")
    assert without_secret.status_code == _UNAUTHORIZED
    assert without_secret.json() == {"error": "Unauthorized"}


async def test_fallback_handles_every_method(svc: httpx.AsyncClient) -> None:
    """C7 „wszystkie metody": TRACE na nieznanej trasie daje kopertę SVC, nie 405 Starlette."""
    trace = await svc.request("TRACE", "/user-api/api/foo")
    assert trace.status_code == _NOT_FOUND
    assert trace.json() == {"error": "Not found"}
    without_secret = await svc.request("TRACE", "/user-api/api/bar", headers={"X-API-Secret": ""})
    assert without_secret.status_code == _UNAUTHORIZED
    assert without_secret.json() == {"error": "Unauthorized"}


async def test_users_and_keys_fallbacks(svc: httpx.AsyncClient, prefix: str) -> None:
    """C7: nieznane podtrasy users/keys → 404; `/api/keys` bez e-maila → 400."""
    users = await svc.get(f"{prefix}/api/users/x/unknown")
    assert users.status_code == _NOT_FOUND
    assert users.json() == {"error": "Not found"}
    keys = await svc.get(f"{prefix}/api/keys/a@x.pl/extra/segments")
    assert keys.status_code == _NOT_FOUND
    assert keys.json() == {"error": "Not found"}
    no_email = await svc.get(f"{prefix}/api/keys")
    assert no_email.status_code == _BAD_REQUEST
    assert no_email.json() == {"error": "email is required in path"}


async def test_hub_compat_routes_disabled_returns_non_svc_envelope(
    disabled_routes_client: httpx.AsyncClient,
) -> None:
    """C7: `hub_compat_routes=False` ⇒ `/api/access` nie istnieje (404, nie 200/401 SVC)."""
    response = await disabled_routes_client.get("/api/access", params={"email": "x@x.pl"})
    assert response.status_code == _NOT_FOUND
    body = response.json()
    assert body != {"error": "Not found"}
    assert "Not Found: /api/access" in str(body)


async def test_rf_routes_not_shadowed(container: Container, svc: httpx.AsyncClient) -> None:
    """AG-31: zły Bearer na `/api/v1/*` daje kopertę RF, ważny klucz działa."""
    assert container.users is not None
    assert container.api_keys is not None
    user = await container.users.create(email="rf@x.pl", password=PASSWORD, is_superuser=True)
    key = await container.api_keys.create(container.users.principal_of(user))
    bad = await svc.get("/api/v1/datasets", headers={"Authorization": "Bearer zly-klucz"})
    assert bad.json() != {"error": "Unauthorized"}
    assert bad.json()["code"] != 0
    good = await svc.get("/api/v1/chats", headers={"Authorization": f"Bearer {key.token}"})
    assert good.status_code == _OK
    assert good.json()["code"] == 0
