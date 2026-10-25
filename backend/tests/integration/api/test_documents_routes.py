"""Testy HTTP tras /api/v1/datasets/.../documents (brief E1-9a T2b; wzór test_datasets_routes)."""

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
from app.services.documents import MSG_STOP_NOT_RUNNING
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.integration.datasets.conftest import seed_default_models

pytestmark = pytest.mark.db

_OK = 200
UPLOADED_KEYS = 15  # klucze elementu odpowiedzi uploadu (złoto --02)
LISTED_KEYS = 28  # klucze elementu listy dokumentów (złoto --03)
FULL_KEYS = 26  # klucze odpowiedzi PATCH/PUT (document_full)
TOTAL_DOCS = 2  # po dwukrotnym uploadzie
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście

_OWNER_EMAIL = "owner@x.pl"
_BOB_EMAIL = "bob@x.pl"


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


def create_dataset(client: TestClient, token: str) -> str:
    """POST /datasets z asercją code 0; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": "wd_docs"})
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    dataset_id: str = payload["data"]["id"]
    return dataset_id


def upload(
    client: TestClient, token: str, dataset_id: str, name: str = "a.txt", content: bytes = b"hello"
) -> dict[str, Any]:
    """POST multipart z jednym plikiem; zwraca data[0]."""
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        files={"file": (name, content)},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    element: dict[str, Any] = body["data"][0]
    return element


async def test_upload_document_shape(client: TestClient, owner: tuple[str, str]) -> None:
    """Upload a.txt → 15 kluczy, name/location a.txt, UNSTART, thumbnail "", pipeline None."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    assert len(element) == UPLOADED_KEYS
    assert element["name"] == element["location"] == "a.txt"
    assert element["run"] == "UNSTART"
    assert element["thumbnail"] == ""
    assert element["pipeline_id"] is None


async def test_upload_duplicate_name(client: TestClient, owner: tuple[str, str]) -> None:
    """Ten sam plik drugi raz → name „a(1).txt" (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    upload(client, token, dataset_id)
    assert upload(client, token, dataset_id)["name"] == "a(1).txt"


async def test_upload_without_file_part(client: TestClient, owner: tuple[str, str]) -> None:
    """Multipart bez pola file → code 101 „No file part!" (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        files={"other": ("b.txt", b"x")},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"] == "No file part!"


async def test_upload_empty_filename(client: TestClient, owner: tuple[str, str]) -> None:
    """Plik z pustą nazwą → code 101 „No file selected!" (DOC:661).

    Ręczny multipart: httpx dla files={"file": ("", b"x")} pominąłby filename
    w Content-Disposition i pole przyszłoby jako tekst, nie plik.
    """
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    body = (
        b"--BOUNDARY\r\n"
        b'Content-Disposition: form-data; name="file"; filename=""\r\n'
        b"Content-Type: text/plain\r\n\r\n"
        b"x\r\n"
        b"--BOUNDARY--\r\n"
    )
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={**_bearer(token), "content-type": "multipart/form-data; boundary=BOUNDARY"},
        content=body,
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == RetCode.ARGUMENT_ERROR
    assert payload["message"] == "No file selected!"


async def test_upload_unsupported_suffix(client: TestClient, owner: tuple[str, str]) -> None:
    """Plik x.exe → code 500 z komunikatem upstreamu (DOC:571/705, DEC-088 p. 4)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        files={"file": ("x.exe", b"MZ")},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.SERVER_ERROR
    assert body["message"] == "x.exe: This type of file has not been supported yet!"


async def test_upload_missing_dataset(client: TestClient, owner: tuple[str, str]) -> None:
    """Nieistniejący dataset → 102 „Can't find the dataset with ID x!" (DOC:516, DEC-088 p. 4).

    Upstream sprawdza istnienie datasetu **przed** uprawnieniami; profil odmowy uploadu
    (109 „no authorization") obsługuje wyłącznie cudzy dataset.
    """
    token, _user_id = owner
    response = client.post(
        "/api/v1/datasets/nonexistent/documents",
        headers=_bearer(token),
        files={"file": ("a.txt", b"hi")},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "Can't find the dataset with ID nonexistent!"


async def test_list_documents(client: TestClient, owner: tuple[str, str]) -> None:
    """GET ?page=1&page_size=30 → total 2, docs[0] 28 kluczy, nickname (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    upload(client, token, dataset_id)
    upload(client, token, dataset_id)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={"page": 1, "page_size": 30},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["message"] == "success"
    assert body["data"]["total"] == TOTAL_DOCS
    assert {doc["name"] for doc in body["data"]["docs"]} == {"a.txt", "a(1).txt"}
    assert len(body["data"]["docs"][0]) == LISTED_KEYS
    assert body["data"]["docs"][0]["nickname"] == "owner"


async def test_list_documents_filter_run(client: TestClient, owner: tuple[str, str]) -> None:
    """?run=DONE → total 0; ?run=BAD → 102 „Invalid filter run status conditions: BAD"."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    upload(client, token, dataset_id)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token), params={"run": "DONE"}
    )
    assert response.status_code == _OK
    assert response.json()["data"]["total"] == 0
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token), params={"run": "BAD"}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "Invalid filter run status conditions: BAD"


async def test_list_documents_run_empty_ignored(client: TestClient, owner: tuple[str, str]) -> None:
    """D2: `?run=` (pusty) to brak filtra, nie błąd — total bez zmian (upstream DOC:990-996)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    upload(client, token, dataset_id)
    for params in ({"run": ""}, {"run[]": ""}, {"run": " "}):
        response = client.get(
            f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token), params=params
        )
        assert response.status_code == _OK
        body = response.json()
        assert body["code"] == 0, params
        assert body["data"]["total"] == 1  # jeden upload, brak filtra


async def test_list_documents_orderby_name(client: TestClient, owner: tuple[str, str]) -> None:
    """?orderby=name → kolejność wg nazwy; desc=true odwraca (upstream DOC:895-897)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    for name in ("b.txt", "A.txt", "c.txt"):
        upload(client, token, dataset_id, name=name)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={"orderby": "name", "desc": "false"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert [doc["name"] for doc in body["data"]["docs"]] == ["A.txt", "b.txt", "c.txt"]
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={"orderby": "name", "desc": "true"},
    )
    assert [doc["name"] for doc in response.json()["data"]["docs"]] == [
        "c.txt",
        "b.txt",
        "A.txt",
    ]


async def test_list_documents_invalid_orderby(client: TestClient, owner: tuple[str, str]) -> None:
    """?orderby=unknown → koperta 101 z komunikatem upstream (DOC:895-897)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={"orderby": "unknown"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"] == "invalid orderby field: unknown"


async def test_download_document(client: TestClient, owner: tuple[str, str]) -> None:
    """GET …/documents/{doc} → bajty pliku, text/plain, Content-Disposition (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents/{element['id']}", headers=_bearer(token)
    )
    assert response.status_code == _OK
    assert response.content == b"hello"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''a.txt"


async def test_download_document_foreign_user_denied(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Bob czyta dokument prywatnego datasetu → koperta 102, nie bajty (złoto --15)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents/{element['id']}", headers=_bearer(bob_key)
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    # Odmowa nie ujawnia istnienia cudzego dokumentu (K11 §10c p. 9, złoto --15).
    assert body["message"] == "document not found"
    assert b"secret" not in response.content


async def test_update_document_patch_and_put(client: TestClient, owner: tuple[str, str]) -> None:
    """PATCH i PUT {"name": "c.txt"} → code 0, data.name c.txt, 26 kluczy (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    for method in ("PATCH", "PUT"):
        response = client.request(
            method,
            f"/api/v1/datasets/{dataset_id}/documents/{element['id']}",
            headers=_bearer(token),
            json={"name": "c.txt"},
        )
        assert response.status_code == _OK
        body = response.json()
        assert body["code"] == 0, body
        assert body["data"]["name"] == "c.txt"
        assert len(body["data"]) == FULL_KEYS


async def test_update_document_immutable_field(client: TestClient, owner: tuple[str, str]) -> None:
    """PATCH {"chunk_count": 3} → 102 „can't change `chunk_count`" (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    response = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/{element['id']}",
        headers=_bearer(token),
        json={"chunk_count": 3},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "can't change `chunk_count`"


async def test_parse_document(client: TestClient, owner: tuple[str, str]) -> None:
    """parse {"document_ids": [doc]} → data {"success_count": 1} (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/parse",
        headers=_bearer(token),
        json={"document_ids": [element["id"]]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"] == {"success_count": 1}


async def test_parse_document_empty_body(client: TestClient, owner: tuple[str, str]) -> None:
    """parse {} → 102 „`document_ids` is required" (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/parse", headers=_bearer(token), json={}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "`document_ids` is required"


async def test_parse_document_unknown_id(client: TestClient, owner: tuple[str, str]) -> None:
    """parse {"document_ids": ["zzz"]} → 102 „Documents not found: ['zzz']" (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/parse",
        headers=_bearer(token),
        json={"document_ids": ["zzz"]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "Documents not found: ['zzz']"


async def test_stop_running_document(client: TestClient, owner: tuple[str, str]) -> None:
    """stop po parse (zadanie w kolejce) → {"success_count": 1} (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    parsed = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/parse",
        headers=_bearer(token),
        json={"document_ids": [element["id"]]},
    )
    assert parsed.json()["code"] == 0, parsed.json()
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/stop",
        headers=_bearer(token),
        json={"document_ids": [element["id"]]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"] == {"success_count": 1}


async def test_stop_unstarted_document(client: TestClient, owner: tuple[str, str]) -> None:
    """stop UNSTART → {"success_count": 0, "errors": [MSG_STOP_NOT_RUNNING]} (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents/stop",
        headers=_bearer(token),
        json={"document_ids": [element["id"]]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"] == {"success_count": 0, "errors": [MSG_STOP_NOT_RUNNING]}


async def test_legacy_chunks_parse_and_stop(client: TestClient, owner: tuple[str, str]) -> None:
    """POST/DELETE /datasets/{A}/chunks → code 0, brak klucza data (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/chunks",
        headers=_bearer(token),
        json={"document_ids": [element["id"]]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert "data" not in body
    response = client.request(
        "DELETE",
        f"/api/v1/datasets/{dataset_id}/chunks",
        headers=_bearer(token),
        json={"document_ids": [element["id"]]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert "data" not in body


async def test_delete_documents_by_ids(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE {"ids": [doc]} → data {"deleted": 1} (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    element = upload(client, token, dataset_id)
    response = client.request(
        "DELETE",
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        json={"ids": [element["id"]]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0
    assert body["data"] == {"deleted": 1}


async def test_delete_documents_empty_body(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE {} → 102 „should either provide doc ids … dataset: <A>. " (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    response = client.request(
        "DELETE",
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        json={},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == (
        f"should either provide doc ids or set delete_all(true), dataset: {dataset_id}. "
    )
