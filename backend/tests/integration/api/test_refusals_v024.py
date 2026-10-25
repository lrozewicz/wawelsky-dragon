"""Odmowy na trasach dokumentów w profilu 0.24 (brief E2-2f T1b).

Ten sam kod tras obsługuje dwa profile zgodności wybrane nagłówkiem ``X-RAGFlow-Compat``
(kontrakt E2-2f C1/C2): bez nagłówka działa mapa ``PROFILES`` v0.27, z nagłówkiem ``0.24``
mapa ``PROFILES_V024``. Dzięki temu komunikat odmowy przy cudzym dokumencie zależy od profilu
(``document not found`` vs ``You do not own the dataset <id>.``; złoto v0.24.0
``datasets___documents___/errors_access--15.json``).

Upload do cudzego datasetu w 0.24 daje 109 ``no authorization`` i nie dodaje dokumentu
(K11 §10d p. 15; złoto v0.24.0 ``datasets___documents/errors_access--13.json`` to sukces
upstream — pominięty w teście tablicowym, tutaj sprawdzany jako odmowa).
"""

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

pytestmark = pytest.mark.db

_OK = 200
_CODE_DATA_ERROR = 102
_CODE_AUTHENTICATION_ERROR = 109
V024_HEADER = "0.24"
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście

_OWNER_EMAIL = "owner@x.pl"
_BOB_EMAIL = "bob@x.pl"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _v024(token: str) -> dict[str, str]:
    """Nagłówki klucza API wymuszające profil zgodności 0.24 (C7)."""
    return {**_bearer(token), "X-RAGFlow-Compat": V024_HEADER}


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


async def make_key(users_svc: UserService, keys_svc: ApiKeyService, email: str) -> tuple[str, str]:
    """Konto + jawny token klucza API; zwraca (token, user_id)."""
    user = await users_svc.create(email=email, password=PASSWORD, is_superuser=False)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys_svc.create(principal)).token, user.id


@pytest.fixture
async def owner(
    users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None
) -> tuple[str, str]:
    """Właściciel datasetu: (token, user_id)."""
    return await make_key(users_svc, keys_svc, _OWNER_EMAIL)


@pytest.fixture
async def bob_key(users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None) -> str:
    """Drugi użytkownik (Bob) z własnym kluczem API."""
    return (await make_key(users_svc, keys_svc, _BOB_EMAIL))[0]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


def create_dataset(client: TestClient, token: str) -> str:
    """POST /datasets z asercją code 0; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": "wd_v024"})
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    dataset_id: str = payload["data"]["id"]
    return dataset_id


def upload(client: TestClient, token: str, dataset_id: str) -> str:
    """POST multipart z jednym plikiem; zwraca id dokumentu."""
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        files={"file": ("d.txt", b"hello")},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    document_id: str = body["data"][0]["id"]
    return document_id


async def test_upload_foreign_dataset_v024_refused(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Upload do cudzego datasetu w 0.24 → 109 „no authorization" i brak nowego dokumentu."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_v024(bob_key),
        files={"file": ("d.txt", b"hello")},
    )
    assert response.status_code == _OK
    assert response.json() == {"code": _CODE_AUTHENTICATION_ERROR, "message": "no authorization"}
    listed = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert listed.status_code == _OK
    assert listed.json()["data"]["total"] == 0


async def test_refusal_uses_profile(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy dokument: bez nagłówka 102 „document not found", w 0.24 102 „You do not own …"."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    url = f"/api/v1/datasets/{dataset_id}/documents/{document_id}"
    without_header = client.get(url, headers=_bearer(bob_key))
    assert without_header.status_code == _OK
    assert without_header.json() == {"code": _CODE_DATA_ERROR, "message": "document not found"}
    with_v024 = client.get(url, headers=_v024(bob_key))
    assert with_v024.status_code == _OK
    assert with_v024.json() == {
        "code": _CODE_DATA_ERROR,
        "message": f"You do not own the dataset {dataset_id}.",
    }
