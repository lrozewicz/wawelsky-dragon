"""Testy GET/PATCH /api/v1/users/me/models (brief T2, kontrakt C10)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.core.errors import PermissionDenied
from app.db.repositories import models as models_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.llm.registry import ModelRegistry
from app.main import create_app
from app.services.api_keys import ApiKeyService
from app.services.default_models import DefaultModelsService
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

pytestmark = pytest.mark.db

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
NOW_MS = 1790157600000

# Stałe statusów HTTP (ruff PLR2004 nie pozwala na dosłowniki w porównaniu).
_OK = 200
_UNAUTHORIZED = 401

_ADMIN_EMAIL = "admin@x.pl"
_USER_EMAIL = "jan@x.pl"

# Klucze odpowiedzi w kolejności z kontraktu C10.
_KEY_ORDER = ("llm_id", "embd_id", "img2txt_id", "rerank_id", "asr_id", "tts_id")


async def seed_models(sm: async_sessionmaker[AsyncSession]) -> dict[str, str]:
    """Modele z tabeli briefu (T2); zwraca nazwa → id (32 hex)."""
    specs = (
        ("fake-chat", "chat", True),
        ("fake-chat-think", "chat", False),
        ("fake-embed-1024", "embedding", True),
        ("fake-rerank", "rerank", True),
        ("fake-vision", "image2text", True),
        ("off-chat", "chat", False),
    )
    id_gen = SeqIdGenerator()
    ids: dict[str, str] = {}
    async with transaction(sm) as session:
        for name, model_type, is_default in specs:
            model_id = id_gen.new_id()
            await models_repo.insert(
                session,
                id=model_id,
                name=name,
                model_type=model_type,
                is_default=is_default,
                now_ms=NOW_MS,
            )
            ids[name] = model_id
        await session.execute(text("UPDATE models SET is_active = 0 WHERE name = 'off-chat'"))
    return ids


async def make_key(
    users_svc: UserService, keys_svc: ApiKeyService, email: str, *, is_superuser: bool
) -> str:
    """Konto w bazie + jawny token klucza API (nagłówek Authorization)."""
    user = await users_svc.create(email=email, password=PASSWORD, is_superuser=is_superuser)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys_svc.create(principal)).token


async def assert_chat_default(
    sm: async_sessionmaker[AsyncSession], name: str, *, is_default: bool
) -> None:
    """Flaga is_default modelu chat w bazie po operacji."""
    async with transaction(sm) as session:
        row = await models_repo.get_by_name(session, name, "chat")
    assert row is not None
    assert row.is_default is is_default


def expected_data(llm: str, embd: str, img2txt: str, rerank: str) -> dict[str, str]:
    """Oczekiwane data GET/PATCH wg C10: 4 typy + puste asr_id/tts_id."""
    return {
        "llm_id": llm,
        "embd_id": embd,
        "img2txt_id": img2txt,
        "rerank_id": rerank,
        "asr_id": "",
        "tts_id": "",
    }


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def settings(auth_settings: Settings, tmp_path) -> Settings:
    """Ustawienia auth + storage_root w katalogu tymczasowym (wskazówka briefu)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
def users_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> UserService:
    return UserService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
def keys_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> ApiKeyService:
    return ApiKeyService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
async def models_ids(sm: async_sessionmaker[AsyncSession]) -> dict[str, str]:
    return await seed_models(sm)


@pytest.fixture
async def admin_key(users_svc: UserService, keys_svc: ApiKeyService) -> str:
    return await make_key(users_svc, keys_svc, _ADMIN_EMAIL, is_superuser=True)


@pytest.fixture
async def user_key(users_svc: UserService, keys_svc: ApiKeyService) -> str:
    return await make_key(users_svc, keys_svc, _USER_EMAIL, is_superuser=False)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


async def test_get_models_returns_active_defaults(
    client: TestClient,
    user_key: str,
    models_ids: dict[str, str],
) -> None:
    """Zwykły użytkownik: GET zwraca domyślne aktywne modele (wiersz 1 tabeli)."""
    response = client.get("/api/v1/users/me/models", headers=_bearer(user_key))
    assert response.status_code == _OK
    body = response.json()
    assert body == {
        "code": 0,
        "message": "success",
        "data": expected_data("fake-chat", "fake-embed-1024", "fake-vision", "fake-rerank"),
    }
    assert tuple(body["data"]) == _KEY_ORDER


async def test_get_models_without_default_rerank_returns_empty(
    client: TestClient,
    admin_key: str,
    models_ids: dict[str, str],
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Brak domyślnego rerank w bazie → rerank_id == "" (wiersz 2)."""
    async with transaction(sm) as session:
        await session.execute(text("DELETE FROM models WHERE name = 'fake-rerank'"))
    response = client.get("/api/v1/users/me/models", headers=_bearer(admin_key))
    assert response.status_code == _OK
    assert response.json()["data"]["rerank_id"] == ""


async def test_get_models_inactive_default_chat_returns_empty(
    client: TestClient,
    admin_key: str,
    models_ids: dict[str, str],
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Domyślny chat nieaktywny → llm_id == "" (wiersz 3)."""
    async with transaction(sm) as session:
        await session.execute(text("UPDATE models SET is_active = 0 WHERE name = 'fake-chat'"))
    response = client.get("/api/v1/users/me/models", headers=_bearer(admin_key))
    assert response.status_code == _OK
    assert response.json()["data"]["llm_id"] == ""


def test_get_models_requires_auth(client: TestClient, models_ids: dict[str, str]) -> None:
    """GET bez nagłówka Authorization → HTTP 401, koperta ragflow jak /users/me."""
    response = client.get("/api/v1/users/me/models")
    assert response.status_code == _UNAUTHORIZED
    assert response.json()["code"] == _UNAUTHORIZED


async def test_patch_models_superuser_switches_default(
    client: TestClient,
    admin_key: str,
    models_ids: dict[str, str],
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Superuser: PATCH llm_id → code 0, nowy domyślny w odpowiedzi i w bazie (wiersz 5)."""
    response = client.patch(
        "/api/v1/users/me/models",
        headers=_bearer(admin_key),
        json={"llm_id": "fake-chat-think"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["llm_id"] == "fake-chat-think"
    await assert_chat_default(sm, "fake-chat", is_default=False)
    await assert_chat_default(sm, "fake-chat-think", is_default=True)


async def test_patch_models_accepts_name_with_suffix(
    client: TestClient,
    admin_key: str,
    models_ids: dict[str, str],
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Sufiks @Fabryka odcinany w resolve (wiersz 6)."""
    response = client.patch(
        "/api/v1/users/me/models",
        headers=_bearer(admin_key),
        json={"llm_id": "fake-chat-think@Fabryka"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["llm_id"] == "fake-chat-think"
    await assert_chat_default(sm, "fake-chat", is_default=False)
    await assert_chat_default(sm, "fake-chat-think", is_default=True)


async def test_patch_models_accepts_model_id(
    client: TestClient,
    admin_key: str,
    models_ids: dict[str, str],
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Referencja 32 hex (id modelu) rozwiązywana z wymaganym typem (wiersz 7)."""
    response = client.patch(
        "/api/v1/users/me/models",
        headers=_bearer(admin_key),
        json={"llm_id": models_ids["fake-chat-think"]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["llm_id"] == "fake-chat-think"
    await assert_chat_default(sm, "fake-chat", is_default=False)
    await assert_chat_default(sm, "fake-chat-think", is_default=True)


async def test_patch_models_non_superuser_denied(
    client: TestClient,
    user_key: str,
    models_ids: dict[str, str],
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Zwykły użytkownik: code 108, „No authorization.", baza bez zmian (wiersz 8)."""
    response = client.patch(
        "/api/v1/users/me/models",
        headers=_bearer(user_key),
        json={"llm_id": "fake-chat-think"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.PERMISSION_ERROR
    assert body["message"] == "No authorization."
    await assert_chat_default(sm, "fake-chat", is_default=True)
    await assert_chat_default(sm, "fake-chat-think", is_default=False)


async def test_patch_models_unknown_model_not_found(
    client: TestClient, admin_key: str, models_ids: dict[str, str]
) -> None:
    """Nieznana nazwa → code 102, „model not found: nope" (wiersz 9)."""
    response = client.patch(
        "/api/v1/users/me/models", headers=_bearer(admin_key), json={"llm_id": "nope"}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "model not found: nope"


async def test_patch_models_wrong_type_not_found(
    client: TestClient, admin_key: str, models_ids: dict[str, str]
) -> None:
    """Model istnieje, ale innego typu → code 102 (wiersz 10)."""
    response = client.patch(
        "/api/v1/users/me/models",
        headers=_bearer(admin_key),
        json={"llm_id": "fake-embed-1024"},
    )
    assert response.status_code == _OK
    assert response.json()["code"] == RetCode.DATA_ERROR


async def test_patch_models_inactive_model_rejected(
    client: TestClient, admin_key: str, models_ids: dict[str, str]
) -> None:
    """Model nieaktywny → code 101 (C4 E5-H6b / DEC-257; zastępuje wiersz 11 C10, było 102)."""
    response = client.patch(
        "/api/v1/users/me/models", headers=_bearer(admin_key), json={"llm_id": "off-chat"}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"] == "llm_id: model 'off-chat' is inactive"


async def test_patch_models_invalid_value(
    client: TestClient, admin_key: str, models_ids: dict[str, str]
) -> None:
    """Wartość nie-str albo pusta → code 101 z komunikatem C10 (wiersz 12)."""
    for value in (5, ""):
        response = client.patch(
            "/api/v1/users/me/models", headers=_bearer(admin_key), json={"llm_id": value}
        )
        assert response.status_code == _OK
        body = response.json()
        assert body["code"] == RetCode.ARGUMENT_ERROR
        assert body["message"] == "llm_id must be a non-empty string"


async def test_patch_models_atomic_all_or_nothing(
    client: TestClient,
    admin_key: str,
    models_ids: dict[str, str],
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Błąd drugiego pola → code 102 i nic nie zmienione (wiersz 13)."""
    response = client.patch(
        "/api/v1/users/me/models",
        headers=_bearer(admin_key),
        json={"llm_id": "fake-chat-think", "embd_id": "nope"},
    )
    assert response.status_code == _OK
    assert response.json()["code"] == RetCode.DATA_ERROR
    await assert_chat_default(sm, "fake-chat", is_default=True)
    await assert_chat_default(sm, "fake-chat-think", is_default=False)


async def test_patch_models_ignores_unknown_keys(
    client: TestClient, admin_key: str, models_ids: dict[str, str]
) -> None:
    """asr_id/tts_id/inne klucze ignorowane; dane jak GET (wiersz 14)."""
    response = client.patch(
        "/api/v1/users/me/models",
        headers=_bearer(admin_key),
        json={"asr_id": "x", "tts_id": "y", "foo": 1},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"] == expected_data(
        "fake-chat", "fake-embed-1024", "fake-vision", "fake-rerank"
    )


async def test_service_set_non_superuser_denied(
    settings: Settings,
    sm: async_sessionmaker[AsyncSession],
    models_ids: dict[str, str],
) -> None:
    """DefaultModelsService.set wprost: Principal bez superusera → PermissionDenied."""
    container = Container(settings)
    container.sessionmaker = sm
    container.clock = FrozenClock()
    container.models = ModelRegistry(sm, settings, FrozenClock(), SeqIdGenerator())
    service = DefaultModelsService(container)
    principal = Principal("u1", "jan@x.pl", False, False, "jwt")
    with pytest.raises(PermissionDenied):
        await service.set(principal, {"llm_id": "fake-chat-think"})
