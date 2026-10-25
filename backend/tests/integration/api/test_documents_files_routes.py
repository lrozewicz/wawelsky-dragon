"""Testy HTTP tras plikowych dokumentów (fragment E2-1 DOC2, scenariusz documents_extras).

Kroki 19-33 złota: POST /documents/ingest, POST /documents/upload, GET /documents/{id},
GET /documents/{id}/preview, GET /thumbnails i GET /documents/images/{id} — happy path,
brak dokumentu i dokument cudzy (obowiązkowy test negatywny ingestu).
Wzór: tests/integration/api/test_documents_extra_routes.py.
"""

import sys
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.api_keys import ApiKeyService
from app.services.users import UserService
from app.storage.keys import image_key
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.integration.datasets.conftest import seed_default_models

pytestmark = pytest.mark.db

_OK = 200
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
_MISSING = "0" * 32
ID_LEN = 32  # identyfikatory WD: 32 znaki hex (K5 §1)
_TEXT = b"Legenda o smoku wawelskim.\n"
# Złoto --33: kompaktowa koperta błędu Quarta z końcowym newline (krok ``binary``).
_MISSING_IMAGE_BODY = b'{"code":102,"message":"Image not found."}\n'

_OWNER_EMAIL = "files-owner@x.pl"
_BOB_EMAIL = "files-bob@x.pl"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Any) -> Settings:
    """Ustawienia auth + storage_root w katalogu tymczasowym (wzór briefu)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
def container(settings: Settings) -> Container:
    """Kontener aplikacji — storage testu sięga po obraz dokumentu (``images/...``)."""
    return Container(settings)


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
def client(container: Container) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(container.settings, container), base_url="https://testserver"
    ) as test_client:
        yield test_client


def create_dataset(client: TestClient, token: str, name: str = "wd_files") -> str:
    """POST /datasets z asercją code 0; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": name})
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    dataset_id: str = payload["data"]["id"]
    return dataset_id


def upload(client: TestClient, token: str, dataset_id: str, content: bytes = _TEXT) -> str:
    """POST multipart datasetu; zwraca id dokumentu."""
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        files={"file": ("smok.txt", content, "text/plain")},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    document_id: str = body["data"][0]["id"]
    return document_id


def doc_run(client: TestClient, token: str, dataset_id: str) -> str:
    """``run`` pierwszego dokumentu listy datasetu (nazwa stanu, nie kod)."""
    response = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert response.status_code == _OK
    return str(response.json()["data"]["docs"][0]["run"])


def test_ingest_start_cancel_and_delete(client: TestClient, owner: tuple[str, str]) -> None:
    """run='1' start, '2' anulowanie, '1'+delete restart — zawsze data true (złoto 19/21/23)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    for body in (
        {"doc_ids": [document_id], "run": "1"},
        {"doc_ids": [document_id], "run": "2"},
        {"doc_ids": [document_id], "run": "1", "delete": True},
    ):
        response = client.post("/api/v1/documents/ingest", headers=_bearer(token), json=body)
        assert response.status_code == _OK
        assert response.json() == {"code": 0, "message": "success", "data": True}, response.json()


def test_ingest_foreign_document_denied_and_untouched(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Cudzy dokument → 108 i dokument nietknięty (K11 §10c p. 9-10, obowiązkowy negatywny)."""
    owner_token, _ = owner
    bob_dataset = create_dataset(client, bob_key, "wd_files_bob")
    bob_document = upload(client, bob_key, bob_dataset)
    before = doc_run(client, bob_key, bob_dataset)

    response = client.post(
        "/api/v1/documents/ingest",
        headers=_bearer(owner_token),
        json={"doc_ids": [bob_document], "run": "1", "delete": True},
    )
    assert response.status_code == _OK
    assert response.json()["code"] == int(RetCode.PERMISSION_ERROR)
    # Odmowę zgłasza DatasetService.load (jedno miejsce sprawdzania datasetu — C1.2).
    assert response.json()["message"].startswith("You don't own the dataset ")
    assert doc_run(client, bob_key, bob_dataset) == before == "UNSTART"


def test_upload_file_info(client: TestClient, owner: tuple[str, str]) -> None:
    """POST /documents/upload — 8 kluczy złota --25, size = sys.getsizeof (DOC:823)."""
    token, user_id = owner
    response = client.post(
        "/api/v1/documents/upload",
        headers=_bearer(token),
        files={"file": ("ragflow_intro.txt", _TEXT, "text/plain")},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert set(data) == {
        "id",
        "name",
        "size",
        "extension",
        "mime_type",
        "created_by",
        "created_at",
        "preview_url",
    }
    assert data["name"] == "ragflow_intro.txt"
    assert data["extension"] == "txt"
    assert data["mime_type"] == "text/plain"
    assert data["size"] == sys.getsizeof(_TEXT)
    assert data["created_by"] == user_id
    assert data["preview_url"] is None
    assert len(str(data["id"])) == ID_LEN


def test_upload_multiple_files_returns_list(client: TestClient, owner: tuple[str, str]) -> None:
    """Wiele plików → lista opisów, nie obiekt (DOC:177-178, złoto --25 dla jednego pliku)."""
    token, user_id = owner
    response = client.post(
        "/api/v1/documents/upload",
        headers=_bearer(token),
        files=[
            ("file", ("ragflow_intro.txt", _TEXT, "text/plain")),
            ("file", ("smok.txt", _TEXT * 2, "text/plain")),
        ],
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert isinstance(data, list)
    assert [item["name"] for item in data] == ["ragflow_intro.txt", "smok.txt"]
    assert [item["size"] for item in data] == [sys.getsizeof(_TEXT), sys.getsizeof(_TEXT * 2)]
    assert all(item["created_by"] == user_id for item in data)
    assert all(len(str(item["id"])) == ID_LEN for item in data)
    assert len({item["id"] for item in data}) == len(data)


def test_upload_without_file_is_argument_error(client: TestClient, owner: tuple[str, str]) -> None:
    """Brak części multipart → 101 „Missing input: …" (DOC:161)."""
    token, _ = owner
    response = client.post(
        "/api/v1/documents/upload", headers=_bearer(token), files={"other": ("a.txt", b"x")}
    )
    assert response.status_code == _OK
    assert response.json()["code"] == int(RetCode.ARGUMENT_ERROR)
    assert response.json()["message"].startswith("Missing input")


def test_document_download_and_preview(client: TestClient, owner: tuple[str, str]) -> None:
    """GET /documents/{id} i /preview zwracają tę samą treść pliku (złoto 27/29)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    for path in (f"/api/v1/documents/{document_id}", f"/api/v1/documents/{document_id}/preview"):
        response = client.get(path, headers=_bearer(token))
        assert response.status_code == _OK
        assert response.content == _TEXT
        assert response.headers["content-type"].startswith("text/plain")


def test_document_download_missing_and_foreign(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Nieistniejący dokument → 102; cudzy → 108 (K11 §10c p. 9)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)

    missing = client.get(f"/api/v1/documents/{_MISSING}", headers=_bearer(token))
    assert missing.status_code == _OK
    assert missing.json()["code"] == int(RetCode.DATA_ERROR)
    assert missing.json()["message"] == "document not found"

    foreign = client.get(f"/api/v1/documents/{document_id}", headers=_bearer(bob_key))
    assert foreign.status_code == _OK
    assert foreign.json()["code"] == int(RetCode.PERMISSION_ERROR)


def test_thumbnails_map(client: TestClient, owner: tuple[str, str], bob_key: str) -> None:
    """GET /thumbnails?doc_ids= → mapa doc_id → "" dla .txt (złoto --31); cudzy poza mapą."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)

    response = client.get(
        "/api/v1/thumbnails", headers=_bearer(token), params={"doc_ids": document_id}
    )
    assert response.status_code == _OK
    assert response.json() == {"code": 0, "message": "success", "data": {document_id: ""}}

    stranger = client.get(
        "/api/v1/thumbnails", headers=_bearer(bob_key), params={"doc_ids": document_id}
    )
    assert stranger.status_code == _OK
    assert stranger.json()["data"] == {}

    empty = client.get("/api/v1/thumbnails", headers=_bearer(token))
    assert empty.json()["code"] == int(RetCode.ARGUMENT_ERROR)


async def test_thumbnails_non_empty_prefixed(
    client: TestClient, sm: async_sessionmaker[AsyncSession], owner: tuple[str, str]
) -> None:
    """Niepusta miniatura → prefiks ``/api/v1/documents/images/{kb_id}-`` (DOC:1329-1331).

    WD nie generuje miniatur (ingest zapisuje ``thumbnail=None``), więc kolumnę ustawiamy
    wprost w bazie — kolumna jest poza białą listą ``documents_query.update_meta``.
    """
    token, _ = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE documents SET thumbnail = :t WHERE id = :id"),
            {"t": "page-1.png", "id": document_id},
        )

    response = client.get(
        "/api/v1/thumbnails", headers=_bearer(token), params={"doc_ids": document_id}
    )
    assert response.status_code == _OK
    assert response.json()["data"] == {
        document_id: f"/api/v1/documents/images/{dataset_id}-page-1.png"
    }


async def test_document_image_missing_and_served(
    client: TestClient, container: Container, owner: tuple[str, str], bob_key: str
) -> None:
    """Złoto --33: brak obrazu → JSON z newline (HTTP 200); zapisany obraz → jego bajty."""
    token, _ = owner
    dataset_id = create_dataset(client, token)

    missing = client.get(
        "/api/v1/documents/images/wd_rec_e2_documents_extras-missing.png", headers=_bearer(token)
    )
    assert missing.status_code == _OK
    assert missing.headers["content-type"] == "application/json"
    assert missing.content == _MISSING_IMAGE_BODY

    foreign = client.get(
        f"/api/v1/documents/images/{'0' * 32}-page-1.png", headers=_bearer(bob_key)
    )
    assert foreign.content == _MISSING_IMAGE_BODY

    image = b"\x89PNG\r\n\x1a\nobraz"
    await container.storage.put(image_key(dataset_id, "page-1.png"), image)
    served = client.get(f"/api/v1/documents/images/{dataset_id}-page-1.png", headers=_bearer(token))
    assert served.status_code == _OK
    assert served.content == image
    assert served.headers["content-type"] == "image/png"
