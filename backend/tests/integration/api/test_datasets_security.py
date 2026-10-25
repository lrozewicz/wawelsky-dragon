"""Negatywne testy bezpieczeństwa datasetów/dokumentów (brief E1-9a T5, kontrakt C5).

Każda łatka z tests/mutations/ (dataset-read-policy, document-download-scope,
upload-size-limit) musi zostać wykryta przez co najmniej jeden z tych testów
(wyrocznia: tools/dev/mutation-check.sh).
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.domain.policy import Principal
from app.main import create_app
from app.services.api_keys import ApiKeyService
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.integration.datasets.conftest import seed_default_models

pytestmark = pytest.mark.db

_OK = 200
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
LIMIT_MB = 1  # nadpisane max_upload_mb w aplikacji limitowanej (tabela C5)
_BIG = 1024 * 1024 + 102400  # 1,1 MiB — ponad LIMIT_MB (tabela C5)
_SMALL = 10 * 1024  # 10 KiB — pod limitem (tabela C5)

_ALICE_EMAIL = "alice@x.pl"
_BOB_EMAIL = "bob@x.pl"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Any) -> Settings:
    """Ustawienia auth + storage_root w katalogu tymczasowym (wzór briefu)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
def limited_settings(auth_settings: Settings, tmp_path: Any) -> Settings:
    """Jak settings, ale z max_upload_mb=1 (tabela C5: łatka upload-size-limit)."""
    return auth_settings.model_copy(
        update={"storage_root": str(tmp_path), "max_upload_mb": LIMIT_MB}
    )


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
async def alice(
    users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None
) -> tuple[str, str]:
    """Właścicielka datasetu A: (token, user_id)."""
    return await make_key(users_svc, keys_svc, _ALICE_EMAIL)


@pytest.fixture
async def bob_key(users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None) -> str:
    """Drugi użytkownik (Bob) z własnym kluczem API — dostęp obcy."""
    return (await make_key(users_svc, keys_svc, _BOB_EMAIL))[0]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


@pytest.fixture
def limited_client(limited_settings: Settings) -> Iterator[TestClient]:
    """Aplikacja z max_upload_mb=1 (testy limitu rozmiaru wg tabeli C5)."""
    with TestClient(
        create_app(limited_settings, Container(limited_settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


def create_dataset(client: TestClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /datasets z asercją code 0; zwraca data."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json=body)
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    data: dict[str, Any] = payload["data"]
    return data


def upload(client: TestClient, token: str, dataset_id: str, name: str, content: bytes) -> Any:
    """POST multipart z jednym plikiem; zwraca pełną odpowiedź JSON."""
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        files={"file": (name, content)},
    )
    assert response.status_code == _OK
    return response.json()


async def test_list_hides_foreign_private_dataset(
    client: TestClient, alice: tuple[str, str], bob_key: str
) -> None:
    """Alice: dataset permission="me"; lista Boba (code 0) bez id datasetu Alice (C5)."""
    alice_token, _user_id = alice
    created = create_dataset(client, alice_token, {"name": "private-a", "permission": "me"})
    response = client.get("/api/v1/datasets", headers=_bearer(bob_key))
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert created["id"] not in [item["id"] for item in body["data"]]


async def test_get_foreign_private_dataset_denied(
    client: TestClient, alice: tuple[str, str], bob_key: str
) -> None:
    """Bob czyta prywatny dataset Alice → code 102 „lacks permission" (K11 §10c p. 9, --11)."""
    alice_token, _user_id = alice
    created = create_dataset(client, alice_token, {"name": "private-a", "permission": "me"})
    response = client.get(f"/api/v1/datasets/{created['id']}", headers=_bearer(bob_key))
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert "lacks permission for dataset" in body["message"]
    assert "data" not in body


async def test_download_foreign_document_denied(
    client: TestClient, alice: tuple[str, str], bob_key: str
) -> None:
    """Bob pobiera dokument z cudzego datasetu → koperta 102, bez bajtów pliku (--15)."""
    alice_token, _user_id = alice
    created = create_dataset(client, alice_token, {"name": "private-a", "permission": "me"})
    payload = upload(client, alice_token, created["id"], "a.txt", b"secret")
    assert payload["code"] == 0, payload
    doc_id = payload["data"][0]["id"]
    response = client.get(
        f"/api/v1/datasets/{created['id']}/documents/{doc_id}", headers=_bearer(bob_key)
    )
    assert response.status_code == _OK
    assert response.json()["code"] == RetCode.DATA_ERROR
    assert response.json()["message"] == "document not found"
    assert b"secret" not in response.content


async def test_upload_over_limit_rejected(
    limited_client: TestClient, alice: tuple[str, str]
) -> None:
    """big.txt 1,1 MiB przy max_upload_mb=1 → 101; lista dokumentów pusta (C5)."""
    alice_token, _user_id = alice
    created = create_dataset(limited_client, alice_token, {"name": "limit-a"})
    payload = upload(limited_client, alice_token, created["id"], "big.txt", b"a" * _BIG)
    assert payload["code"] == RetCode.ARGUMENT_ERROR, payload
    listing = limited_client.get(
        f"/api/v1/datasets/{created['id']}/documents", headers=_bearer(alice_token)
    )
    assert listing.status_code == _OK
    assert listing.json()["data"]["total"] == 0


async def test_upload_under_limit_accepted(
    limited_client: TestClient, alice: tuple[str, str]
) -> None:
    """Plik 10 KiB przy max_upload_mb=1 → code 0 (limit nie blokuje wszystkiego; C5)."""
    alice_token, _user_id = alice
    created = create_dataset(limited_client, alice_token, {"name": "limit-b"})
    payload = upload(limited_client, alice_token, created["id"], "small.txt", b"a" * _SMALL)
    assert payload["code"] == 0, payload
