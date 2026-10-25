"""Testy HTTP tras /api/v1/datasets (brief E1-9a T1b; wzór: test_users_models.py)."""

import json
from collections.abc import Iterator
from pathlib import Path
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
from app.services.datasets import DEFAULT_PARSER_CONFIG
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.integration.datasets.conftest import seed_default_models

pytestmark = pytest.mark.db

_OK = 200
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście

_OWNER_EMAIL = "owner@x.pl"
_ALICE_EMAIL = "alice@x.pl"
_GOLDEN_CREATE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "contract"
    / "golden"
    / "v0.27.2"
    / "datasets"
    / "datasets_crud--01.json"
)


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


async def make_key(users_svc: UserService, keys_svc: ApiKeyService, email: str) -> tuple[str, str]:
    """Konto + jawny token klucza API; zwraca (token, user_id)."""
    user = await users_svc.create(email=email, password=PASSWORD, is_superuser=False)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys_svc.create(principal)).token, user.id


@pytest.fixture
async def owner(
    users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None
) -> tuple[str, str]:
    """Właściciel datasetów: (token, user_id)."""
    return await make_key(users_svc, keys_svc, _OWNER_EMAIL)


@pytest.fixture
async def alice_key(users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None) -> str:
    """Drugi użytkownik (Alice) z własnym kluczem API."""
    return (await make_key(users_svc, keys_svc, _ALICE_EMAIL))[0]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
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


async def test_create_dataset_golden_shape(client: TestClient, owner: tuple[str, str]) -> None:
    """POST {"name": "wd_rec_ds"} → kształt złota --01 (klucze, parser_config, llm_id)."""
    token, _user_id = owner
    data = create_dataset(client, token, {"name": "wd_rec_ds"})
    golden = json.loads(_GOLDEN_CREATE.read_text(encoding="utf-8"))["body"]["data"]
    assert sorted(data.keys()) == sorted(golden.keys())
    assert data["name"] == "wd_rec_ds"
    assert data["language"] == "English"
    assert data["permission"] == "me"
    assert data["status"] == "1"
    assert data["embedding_model"] == "fake-embed-1024"
    assert data["parser_config"] == {**DEFAULT_PARSER_CONFIG, "llm_id": "fake-chat"}
    assert data["created_by"] == data["tenant_id"]


async def test_create_dataset_unsupported_chunk_method(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """chunk_method=tag → code 101 z komunikatem WD (tabela briefu)."""
    token, _user_id = owner
    response = client.post(
        "/api/v1/datasets", headers=_bearer(token), json={"name": "x", "chunk_method": "tag"}
    )
    assert response.status_code == _OK
    assert response.json()["code"] == RetCode.ARGUMENT_ERROR
    assert response.json()["message"] == "`chunk_method` tag is not supported by Wawelsky Dragon"


async def test_create_dataset_missing_name(client: TestClient, owner: tuple[str, str]) -> None:
    """POST {} → code 101, komunikat Field: <name> - Message: <Field required>…."""
    token, _user_id = owner
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={})
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"].startswith("Field: <name> - Message: <Field required>")


async def test_list_datasets_page(client: TestClient, owner: tuple[str, str]) -> None:
    """GET ?page=1&page_size=30 → 1 element z nickname/tenant_avatar/embedding_model_name."""
    token, _user_id = owner
    created = create_dataset(client, token, {"name": "wd_rec_ds"})
    response = client.get(
        "/api/v1/datasets", headers=_bearer(token), params={"page": 1, "page_size": 30}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["total_datasets"] == 1
    assert len(body["data"]) == 1
    listed = body["data"][0]
    assert listed["id"] == created["id"]
    assert {"nickname", "tenant_avatar", "embedding_model_name"} <= set(listed)
    assert listed["embedding_model_name"] == ""


async def test_list_datasets_missing_name_not_found(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """GET ?name=nieistnieje → code 102 „User ... lacks permission for dataset 'nieistnieje'"."""
    token, user_id = owner
    response = client.get(
        "/api/v1/datasets", headers=_bearer(token), params={"name": "nieistnieje"}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == (f"User '{user_id}' lacks permission for dataset 'nieistnieje'")


async def test_list_datasets_invalid_orderby(client: TestClient, owner: tuple[str, str]) -> None:
    """GET ?orderby=name → code 101 z komunikatem parse_page (tabela briefu)."""
    token, _user_id = owner
    response = client.get("/api/v1/datasets", headers=_bearer(token), params={"orderby": "name"})
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"] == (
        "Field: <orderby> - Message: <Input should be 'create_time' or 'update_time'>"
        " - Value: <name>"
    )


async def test_get_dataset_detail(client: TestClient, owner: tuple[str, str]) -> None:
    """GET /datasets/{id} → code 0, data.connectors == [], data.size == 0 (bez dokumentów)."""
    token, _user_id = owner
    created = create_dataset(client, token, {"name": "wd_rec_ds"})
    response = client.get(f"/api/v1/datasets/{created['id']}", headers=_bearer(token))
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["id"] == created["id"]
    assert body["data"]["connectors"] == []
    assert body["data"]["size"] == 0  # suma rozmiarów dokumentów (DAS:276, brak dokumentów)


async def test_update_dataset_explicit_null_clears_nullable_field(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """D2: PUT {"description": null} → kolumna wyzerowana (upstream: exclude_unset + UPDATE NULL).

    Semantyka upstream (DAS:300, `validation_utils.validate_and_parse_json_request`):
    jawne ``null`` jest „ustawione", więc jedzie do usługi i zeruje kolumnę; pole
    pominięte nie zmienia wiersza. Sprawdzone na przykładach z briefu (description, avatar).
    """
    token, _user_id = owner
    avatar = "data:image/png;base64,AA"
    created = create_dataset(
        client, token, {"name": "wd_rec_ds", "description": "opis", "avatar": avatar}
    )
    assert created["description"] == "opis"
    response = client.put(
        f"/api/v1/datasets/{created['id']}",
        headers=_bearer(token),
        json={"description": None},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["description"] is None
    assert body["data"]["avatar"] == "data:image/png;base64,AA"  # pominięte pole bez zmian
    response = client.put(
        f"/api/v1/datasets/{created['id']}", headers=_bearer(token), json={"avatar": None}
    )
    assert response.status_code == _OK
    assert response.json()["data"]["avatar"] is None


async def test_update_dataset_explicit_null_name_is_argument_error(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """D2: PUT {"name": null} → 101 jak upstream (name nie-nullowalne), nie 500 z usługi."""
    token, _user_id = owner
    created = create_dataset(client, token, {"name": "wd_rec_ds"})
    response = client.put(
        f"/api/v1/datasets/{created['id']}", headers=_bearer(token), json={"name": None}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert "Field: <name>" in body["message"]


async def test_update_dataset_name(client: TestClient, owner: tuple[str, str]) -> None:
    """PUT {"name": "wd_rec_ds_renamed"} → code 0, nowa nazwa, connectors []."""
    token, _user_id = owner
    created = create_dataset(client, token, {"name": "wd_rec_ds"})
    response = client.put(
        f"/api/v1/datasets/{created['id']}",
        headers=_bearer(token),
        json={"name": "wd_rec_ds_renamed"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "wd_rec_ds_renamed"
    assert body["data"]["connectors"] == []


async def test_update_dataset_empty_body(client: TestClient, owner: tuple[str, str]) -> None:
    """PUT {} → code 102 „no properties were modified" (tabela briefu)."""
    token, _user_id = owner
    created = create_dataset(client, token, {"name": "wd_rec_ds"})
    response = client.put(f"/api/v1/datasets/{created['id']}", headers=_bearer(token), json={})
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "no properties were modified"


async def test_delete_dataset_by_ids(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE {"ids": [...]} → code 0, success_count 1 (tabela briefu)."""
    token, _user_id = owner
    created = create_dataset(client, token, {"name": "wd_rec_ds"})
    response = client.request(
        "DELETE", "/api/v1/datasets", headers=_bearer(token), json={"ids": [created["id"]]}
    )
    assert response.status_code == _OK
    assert response.json()["data"] == {"success_count": 1}


async def test_delete_datasets_null_ids(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE {"ids": null} → code 0, success_count 0 (Q14)."""
    token, _user_id = owner
    response = client.request(
        "DELETE", "/api/v1/datasets", headers=_bearer(token), json={"ids": None}
    )
    assert response.status_code == _OK
    assert response.json()["data"] == {"success_count": 0}


async def test_get_dataset_foreign_user_denied(
    client: TestClient, owner: tuple[str, str], alice_key: str
) -> None:
    """Alice czyta cudzy dataset → code 102 „lacks permission" (K11 §10c p. 9, złoto --11)."""
    _token, _user_id = owner
    created = create_dataset(client, _token, {"name": "wd_rec_ds"})
    response = client.get(f"/api/v1/datasets/{created['id']}", headers=_bearer(alice_key))
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert "lacks permission for dataset" in body["message"]
    assert created["id"] in body["message"]
    assert "data" not in body
