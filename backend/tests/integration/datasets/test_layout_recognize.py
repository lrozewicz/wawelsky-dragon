"""Testy kontraktowe walidacji ``parser_config.layout_recognize`` (kontrakt E5-H6b C3).

Trasa ``POST/PUT /api/v1/datasets`` z ``layout_recognize`` nierozwiązywalnym jako model
``image2text`` zwraca kopertę ``code 101`` z komunikatem C3 (w przestrzeni ragflow HTTP 200,
``RetCode.ARGUMENT_ERROR``) i nie zmienia datasetu. Wartości ``DeepDOC``/``Plain Text``
oraz nazwa modelu ``image2text`` z stosu testowego (``fake-vision``) przechodzą z ``code 0``.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
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
from tests.integration.datasets.conftest import seed_default_models, seed_model

pytestmark = pytest.mark.db

_OK = 200
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
_OWNER_EMAIL = "owner@x.pl"
_VISION_MODEL = "fake-vision"  # model image2text zasiewany w stosie testowym (K9 §3)
_UNKNOWN = "VLM"
_MSG_UNKNOWN = (
    f"layout_recognize '{_UNKNOWN}' is not a known image2text model"
    " (allowed: DeepDOC, Plain Text or an image2text model name)"
)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def settings(migrated_db: Settings, tmp_path: Path) -> Settings:
    """Ustawienia z sekretami testowymi + storage_root w katalogu tymczasowym."""
    return migrated_db.model_copy(
        update={
            "storage_root": str(tmp_path),
            "secret_key": SecretStr("s" * 48),
            "crypto_key": SecretStr("ab" * 32),
        }
    )


@pytest.fixture
def users_svc(sm: async_sessionmaker[AsyncSession], settings: Settings) -> UserService:
    return UserService(sm, settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
def keys_svc(sm: async_sessionmaker[AsyncSession], settings: Settings) -> ApiKeyService:
    return ApiKeyService(sm, settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
async def models_seeded(sm: async_sessionmaker[AsyncSession]) -> None:
    """Modele domyślne + ``fake-vision`` jako ``image2text`` (K9 §3)."""
    await seed_default_models(sm)
    await seed_model(sm, _VISION_MODEL, "image2text")


async def _make_key(users_svc: UserService, keys_svc: ApiKeyService, email: str) -> tuple[str, str]:
    """Konto + jawny token klucza API; zwraca (token, user_id)."""
    user = await users_svc.create(email=email, password=PASSWORD, is_superuser=False)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys_svc.create(principal)).token, user.id


@pytest.fixture
async def owner(
    users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None
) -> tuple[str, str]:
    """Właściciel datasetów: (token, user_id)."""
    return await _make_key(users_svc, keys_svc, _OWNER_EMAIL)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


def _create(client: TestClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /datasets z asercją ``code 0``; zwraca ``data``."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json=body)
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    data: dict[str, Any] = payload["data"]
    return data


async def test_create_dataset_unknown_layout_recognize(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """POST layout_recognize="VLM" → code 101 z komunikatem C3; dataset nie powstał."""
    token, _user_id = owner
    response = client.post(
        "/api/v1/datasets",
        headers=_bearer(token),
        json={"name": "lr", "parser_config": {"layout_recognize": _UNKNOWN}},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"] == _MSG_UNKNOWN
    listed = client.get("/api/v1/datasets", headers=_bearer(token)).json()
    assert listed["total_datasets"] == 0


@pytest.mark.parametrize("value", ["DeepDOC", "Plain Text", _VISION_MODEL])
async def test_create_dataset_allowed_layout_recognize(
    client: TestClient, owner: tuple[str, str], value: str
) -> None:
    """POST z wartością dozwoloną (DeepDOC, Plain Text, model image2text) → code 0."""
    token, _user_id = owner
    data = _create(client, token, {"name": "lr", "parser_config": {"layout_recognize": value}})
    assert data["parser_config"]["layout_recognize"] == value


async def test_update_dataset_unknown_layout_recognize_keeps_dataset(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """PUT layout_recognize="VLM" → code 101 z komunikatem C3; dataset niezmieniony."""
    token, _user_id = owner
    created = _create(
        client, token, {"name": "lr", "parser_config": {"layout_recognize": "DeepDOC"}}
    )
    response = client.put(
        f"/api/v1/datasets/{created['id']}",
        headers=_bearer(token),
        json={"parser_config": {"layout_recognize": _UNKNOWN}},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"] == _MSG_UNKNOWN
    got = client.get(f"/api/v1/datasets/{created['id']}", headers=_bearer(token)).json()
    assert got["data"]["parser_config"]["layout_recognize"] == "DeepDOC"


async def test_update_dataset_allowed_layout_recognize(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """PUT layout_recognize="fake-vision" → code 0, wartość zapisana."""
    token, _user_id = owner
    created = _create(
        client, token, {"name": "lr", "parser_config": {"layout_recognize": "DeepDOC"}}
    )
    response = client.put(
        f"/api/v1/datasets/{created['id']}",
        headers=_bearer(token),
        json={"parser_config": {"layout_recognize": _VISION_MODEL}},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["parser_config"]["layout_recognize"] == _VISION_MODEL
