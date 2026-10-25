"""Koperty uwierzytelnienia shimu v0.24 na trasach ragflow (brief T2, kontrakt C4, K11 §10d p. 14).

Złoto: ``backend/tests/contract/golden/v0.24.0/…/errors_access--36..41.json`` (HTTP 200, ``code``
0/109, ``data: false``). Bez profilu 0.24 albo przy 0.27 — dotychczasowa koperta 401.

Pokrycie łatki mutacji ``e2-2f-v024-auth-empty-passes.patch``: test braku nagłówka z profilem 0.24
(test (a)) musi być czerwony, gdy ``get_principal`` przepuszcza puste ``Authorization``.
"""

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.domain.policy import Principal
from app.main import create_app
from app.services.api_keys import ApiKeyService
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.integration.datasets.conftest import seed_default_models

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

_OK = 200
_UNAUTHORIZED = 401
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście

_OWNER_EMAIL = "v024@x.pl"

_COMPAT_HEADER = {"X-RAGFlow-Compat": "0.24"}

# Koperta 401 dosłownie ze złota v0.27.2 (datasets/errors_access--36.json).
_UNAUTHORIZED_BODY = {
    "code": 401,
    "data": None,
    "message": "<Unauthorized '401: Unauthorized'>",
}

# Koperty v0.24 dosłownie ze złota v0.24.0 (datasets/errors_access--36/37.json).
_EMPTY_AUTH_BODY = {
    "code": 0,
    "data": False,
    "message": "`Authorization` can't be empty",
}
_INVALID_KEY_BODY = {
    "code": 109,
    "data": False,
    "message": "Authentication error: API key is invalid!",
}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Any) -> Settings:
    """Ustawienia auth + storage_root w katalogu tymczasowym (wzór briefu)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
def users_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> UserService:
    return UserService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
def keys_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> ApiKeyService:
    return ApiKeyService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
async def models_seeded(sm: async_sessionmaker[AsyncSession]) -> None:
    """fake-embed-1024 (embedding, 1024, domyślny) i fake-chat (chat, domyślny)."""
    await seed_default_models(sm)


@pytest.fixture
async def owner_key(users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None) -> str:
    """Konto + jawny token klucza API (do testu (f): poprawny klucz w profilu 0.24)."""
    user = await users_svc.create(email=_OWNER_EMAIL, password=PASSWORD, is_superuser=False)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys_svc.create(principal)).token


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


def test_missing_authorization_compat_header_returns_v024_envelope(client: TestClient) -> None:
    """(a) Bez Authorization + nagłówek 0.24 → HTTP 200, code 0, data false (złoto --36)."""
    response = client.get("/api/v1/datasets", headers=_COMPAT_HEADER)
    assert response.status_code == _OK
    assert response.json() == _EMPTY_AUTH_BODY
    assert response.headers.get("X-Request-ID")


def test_invalid_api_key_compat_header_returns_v024_envelope(client: TestClient) -> None:
    """(b) Zły klucz + nagłówek 0.24 → HTTP 200, code 109, data false (złoto --37)."""
    headers = {**_bearer("not-a-real-key"), **_COMPAT_HEADER}
    response = client.get("/api/v1/datasets", headers=headers)
    assert response.status_code == _OK
    assert response.json() == _INVALID_KEY_BODY
    assert response.headers.get("X-Request-ID")


def test_missing_authorization_compat_query_returns_v024_envelope(client: TestClient) -> None:
    """(c) Bez Authorization + query ?compat=0.24 → HTTP 200, code 0, data false."""
    response = client.get("/api/v1/datasets?compat=0.24")
    assert response.status_code == _OK
    assert response.json() == _EMPTY_AUTH_BODY


def test_invalid_api_key_compat_query_returns_v024_envelope(client: TestClient) -> None:
    """(c) Zły klucz + query ?compat=0.24 → HTTP 200, code 109, data false."""
    response = client.get("/api/v1/datasets?compat=0.24", headers=_bearer("not-a-real-key"))
    assert response.status_code == _OK
    assert response.json() == _INVALID_KEY_BODY


def test_missing_authorization_without_profile_returns_401(client: TestClient) -> None:
    """(d) Bez profilu → dotychczasowa koperta 401 (bez zmian)."""
    response = client.get("/api/v1/datasets")
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == _UNAUTHORIZED_BODY


def test_missing_authorization_compat_0_27_returns_401(client: TestClient) -> None:
    """(e) Profil 0.27 → dotychczasowa koperta 401 (v0.24 tylko dla 0.24)."""
    response = client.get("/api/v1/datasets", headers={"X-RAGFlow-Compat": "0.27"})
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == _UNAUTHORIZED_BODY


def test_valid_key_with_compat_header_succeeds(client: TestClient, owner_key: str) -> None:
    """(f) Poprawny klucz + nagłówek 0.24 → code 0 (profil nie psuje sukcesu)."""
    headers = {**_bearer(owner_key), **_COMPAT_HEADER}
    response = client.get("/api/v1/datasets", headers=headers)
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert isinstance(body["data"], list)
