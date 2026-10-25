"""Testy HTTP dodatkowych tras dokumentów (fragment E2-1 DOC, scenariusz documents_extras).

PATCH …/documents/metadatas (kroki 13-14 złota) i POST …/documents/batch-update-status
(kroki 15-16): happy path, walidacja wejścia i dokument spoza datasetu.
Wzór: tests/integration/api/test_documents_routes.py.
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
_MISSING = "0" * 32

_OWNER_EMAIL = "extra-owner@x.pl"
_BOB_EMAIL = "extra-bob@x.pl"


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


def create_dataset(client: TestClient, token: str, name: str = "wd_extra") -> str:
    """POST /datasets z asercją code 0; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": name})
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
        files={"file": ("a.txt", b"hello")},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    document_id: str = body["data"][0]["id"]
    return document_id


def list_meta(client: TestClient, token: str, dataset_id: str) -> dict[str, Any]:
    """meta_fields pierwszego dokumentu listy (złoto --06/--09/--12)."""
    response = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    meta: dict[str, Any] = body["data"]["docs"][0]["meta_fields"]
    return meta


def test_metadatas_update_and_delete(client: TestClient, owner: tuple[str, str]) -> None:
    """Updaty i deletes zmieniają meta_fields; odpowiedź {updated, matched_docs} (złoto 13/14)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)

    added = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/metadatas",
        headers=_bearer(token),
        json={
            "selector": {"document_ids": [document_id]},
            "updates": [{"key": "author", "value": "wd_rec_e2"}],
            "deletes": [],
        },
    )
    assert added.status_code == _OK
    assert added.json()["code"] == 0
    assert added.json()["data"] == {"matched_docs": 1, "updated": 1}
    assert list_meta(client, token, dataset_id) == {"author": "wd_rec_e2"}

    removed = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/metadatas",
        headers=_bearer(token),
        json={
            "selector": {"document_ids": [document_id]},
            "updates": [],
            "deletes": [{"key": "author"}],
        },
    )
    assert removed.status_code == _OK
    assert removed.json()["data"] == {"matched_docs": 1, "updated": 1}
    assert list_meta(client, token, dataset_id) == {}


def test_metadatas_unchanged_and_unknown_key(client: TestClient, owner: tuple[str, str]) -> None:
    """Ten sam klucz + obcy dokument: updated 0 i kod 102 (DOC:1420-1432)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    body = {
        "selector": {"document_ids": [document_id]},
        "updates": [{"key": "author", "value": "x"}],
        "deletes": [],
    }
    assert client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/metadatas", headers=_bearer(token), json=body
    ).json()["data"] == {"matched_docs": 1, "updated": 1}
    again = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/metadatas", headers=_bearer(token), json=body
    )
    assert again.json()["data"] == {"matched_docs": 1, "updated": 0}

    foreign = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/metadatas",
        headers=_bearer(token),
        json={"selector": {"document_ids": [_MISSING]}, "updates": [], "deletes": []},
    )
    assert foreign.status_code == _OK
    assert foreign.json()["code"] == int(RetCode.DATA_ERROR)


def test_metadatas_foreign_dataset(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy dataset → 108 „You don't own the dataset …" (K11 §10c p. 9: brak złota błędu)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    response = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/metadatas",
        headers=_bearer(bob_key),
        json={"selector": {"document_ids": []}, "updates": [], "deletes": []},
    )
    assert response.status_code == _OK
    assert response.json()["code"] == int(RetCode.PERMISSION_ERROR)
    assert "You don't own the dataset" in response.json()["message"]


def test_put_meta_fields_v024(client: TestClient, owner: tuple[str, str]) -> None:
    """PUT w profilu 0.24 (nagłówek X-RAGFlow-Compat): zapis i pusty słownik.

    Złoto ``documents_extras--08/--09`` (``{"author": "x"}`` zapisane) i ``--11/--12``
    (``{"meta_fields": {}}`` nie zmienia metadanych — częściowa aktualizacja ES scala
    obiekty rekurencyjnie). PATCH w profilu 0.27 czyści (złoto --12 v0.27.2).
    """
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    url = f"/api/v1/datasets/{dataset_id}/documents/{document_id}"
    v024 = {**_bearer(token), "X-RAGFlow-Compat": "0.24"}

    saved = client.put(url, headers=v024, json={"meta_fields": {"author": "x"}})
    assert saved.status_code == _OK
    assert saved.json()["code"] == 0, saved.text
    assert list_meta(client, token, dataset_id) == {"author": "x"}

    unchanged = client.put(url, headers=v024, json={"meta_fields": {}})
    assert unchanged.status_code == _OK
    assert unchanged.json()["code"] == 0, unchanged.text
    assert list_meta(client, token, dataset_id) == {"author": "x"}

    patched = client.patch(url, headers=_bearer(token), json={"meta_fields": {}})
    assert patched.status_code == _OK
    assert patched.json()["code"] == 0, patched.text
    assert list_meta(client, token, dataset_id) == {}


def test_batch_update_status_toggle(client: TestClient, owner: tuple[str, str]) -> None:
    """status '0' wyłącza, '1' włącza dokument; odpowiedź mapą doc_id → status (złoto 15/16)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    for status in ("0", "1"):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/documents/batch-update-status",
            headers=_bearer(token),
            json={"doc_ids": [document_id], "status": status},
        )
        assert response.status_code == _OK
        assert response.json()["code"] == 0
        assert response.json()["data"] == {document_id: {"status": status}}
    listed = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert listed.json()["data"]["docs"][0]["status"] == "1"


def test_batch_update_status_validation(client: TestClient, owner: tuple[str, str]) -> None:
    """Puste doc_ids → 101; status spoza '0'/'1' → 101 (DOC:2013-2019)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    empty = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/batch-update-status",
        headers=_bearer(token),
        json={"doc_ids": [], "status": "1"},
    )
    assert empty.json()["code"] == int(RetCode.ARGUMENT_ERROR)
    bad = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/batch-update-status",
        headers=_bearer(token),
        json={"doc_ids": [_MISSING], "status": "2"},
    )
    assert bad.json()["code"] == int(RetCode.ARGUMENT_ERROR)
    assert bad.json()["message"] == '"Status" must be either 0 or 1:2!'


def test_batch_update_status_foreign_dataset(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy dataset → 108 i nietknięty status dokumentu (K11 §10c p. 9, _common.md p. 8)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/batch-update-status",
        headers=_bearer(bob_key),
        json={"doc_ids": [document_id], "status": "0"},
    )
    assert response.status_code == _OK
    assert response.json()["code"] == int(RetCode.PERMISSION_ERROR)
    assert "You don't own the dataset" in response.json()["message"]
    listed = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert listed.json()["data"]["docs"][0]["status"] == "1"


def test_batch_update_status_unknown_document(client: TestClient, owner: tuple[str, str]) -> None:
    """Nieznany dokument → wpis error i „Partial failure" z kodem 500 (DOC:2020-2064)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/batch-update-status",
        headers=_bearer(token),
        json={"doc_ids": [_MISSING], "status": "0"},
    )
    assert response.status_code == _OK
    assert response.json()["code"] == int(RetCode.SERVER_ERROR)
    assert response.json()["data"] == {_MISSING: {"error": "Document not found"}}
