"""Testy uwierzytelnienia ``POST /api/v1/sessions/related_questions`` (brief T6b p. 4, K11 §10d).

Wzorzec: ``tests/integration/api/test_chats_routes.py`` (trasa) i ``test_auth_v024.py`` (koperty
shimu v0.24). Trasa ma ``PrincipalDep`` (CONTRACT C4): bez uwierzytelnienia → 401, a z nagłówkiem
``X-RAGFlow-Compat: 0.24`` → koperta v0.24 (code 0 / 109, ``data: false``). Test (a) jest wyrocznią
dla łatki mutacji ``e2-2b-related-questions-no-auth.patch`` — po jej nałożeniu musi być czerwony.
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
_OWNER_EMAIL = "related-questions@x.pl"
_COMPAT_HEADER = {"X-RAGFlow-Compat": "0.24"}
_PATH = "/api/v1/sessions/related_questions"
_BODY = {"question": "smokwawelski"}

# Koperty dosłownie ze złota v0.24.0 (datasets/errors_access--36/37.json), jak test_auth_v024.py.
_UNAUTHORIZED_BODY = {
    "code": 401,
    "data": None,
    "message": "<Unauthorized '401: Unauthorized'>",
}
_EMPTY_AUTH_BODY = {"code": 0, "data": False, "message": "`Authorization` can't be empty"}
_INVALID_KEY_BODY = {
    "code": 109,
    "data": False,
    "message": "Authentication error: API key is invalid!",
}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Any) -> Settings:
    """Ustawienia auth + storage_root w katalogu tymczasowym (wzór test_auth_v024)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
def users_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> UserService:
    return UserService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
def keys_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> ApiKeyService:
    return ApiKeyService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
async def models_seeded(sm: async_sessionmaker[AsyncSession]) -> None:
    """fake-embed-1024 (embedding) i fake-chat (chat, domyślny)."""
    await seed_default_models(sm)


@pytest.fixture
async def owner_key(users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None) -> str:
    """Konto + jawny token klucza API (test (b))."""
    user = await users_svc.create(email=_OWNER_EMAIL, password=PASSWORD, is_superuser=False)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys_svc.create(principal)).token


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    app = create_app(settings, Container(settings))
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def test_related_questions_requires_auth(client: TestClient) -> None:
    """(a) bez auth → 401; profil 0.24 bez auth → 200 code 0 data false; zły klucz → 109."""
    no_auth = client.post(_PATH, json=_BODY)
    assert no_auth.status_code == _UNAUTHORIZED
    assert no_auth.json() == _UNAUTHORIZED_BODY
    v024_empty = client.post(_PATH, json=_BODY, headers=_COMPAT_HEADER)
    assert v024_empty.status_code == _OK
    assert v024_empty.json() == _EMPTY_AUTH_BODY
    bad_headers = {**_bearer("not-a-real-key"), **_COMPAT_HEADER}
    v024_invalid = client.post(_PATH, json=_BODY, headers=bad_headers)
    assert v024_invalid.status_code == _OK
    assert v024_invalid.json() == _INVALID_KEY_BODY


def test_related_questions_with_key_ok(client: TestClient, owner_key: str) -> None:
    """(b) poprawny klucz → HTTP 200, code 0, ``data`` jest listą."""
    headers = {**_bearer(owner_key), **_COMPAT_HEADER}
    response = client.post(_PATH, json=_BODY, headers=headers)
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert isinstance(body["data"], list)
