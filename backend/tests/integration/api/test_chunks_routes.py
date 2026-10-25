"""Testy HTTP tras /api/v1/.../documents/.../chunks (brief E1-9a T3c; wzór test_documents)."""

import os
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

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

_OK = 200
ITEM_KEYS = 12  # klucze elementu listy chunków (złoto chunks_list--06)
CREATED_KEYS = 9  # klucze data.chunk po POST bez tag_kwd w żądaniu (złoto chunks_extras--06)
SOURCE_KEYS = 10  # klucze data GET …/chunks/{id} (złoto chunks_extras--08)
ID_LEN = 16  # długość id chunka ręcznego (new_chunk_id)
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


@pytest.fixture
def frozen_client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja z zamrożonym zegarem: kolejne żądania widzą ten sam ``now_ms`` (FIXA p. 1)."""
    with TestClient(
        create_app(settings, Container(settings, clock=FrozenClock())),
        base_url="https://testserver",
    ) as test_client:
        yield test_client


def create_dataset(client: TestClient, token: str) -> str:
    """POST /datasets z asercją code 0; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": "wd_chunks"})
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    dataset_id: str = payload["data"]["id"]
    return dataset_id


def upload(client: TestClient, token: str, dataset_id: str) -> str:
    """POST multipart z plikiem bez parsowania; zwraca id dokumentu."""
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


def chunks_url(dataset_id: str, document_id: str) -> str:
    """Wspólny prefiks tras chunków (C3.5)."""
    return f"/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks"


def create_chunk(
    client: TestClient, token: str, dataset_id: str, document_id: str, **body: Any
) -> str:
    """POST …/chunks z domyślną treścią; zwraca id chunka."""
    response = client.post(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"content": "Ala ma kota", **body},
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    chunk_id: str = payload["data"]["chunk"]["id"]
    return chunk_id


async def test_create_chunk_shape(client: TestClient, owner: tuple[str, str]) -> None:
    """POST {"content", "important_keywords"} → data.chunk z 9 kluczami, bez tag_kwd."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.post(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"content": "Ala ma kota", "important_keywords": ["kot"]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    chunk = body["data"]["chunk"]
    assert sorted(chunk.keys()) == sorted(
        [
            "id",
            "content",
            "document_id",
            "dataset_id",
            "important_keywords",
            "questions",
            "create_time",
            "create_timestamp",
            "doc_type_kwd",
        ]
    )
    assert len(chunk) == CREATED_KEYS
    assert len(chunk["id"]) == ID_LEN
    assert chunk["content"] == "Ala ma kota"
    assert chunk["document_id"] == document_id
    assert chunk["dataset_id"] == dataset_id
    assert chunk["important_keywords"] == ["kot"]
    assert chunk["questions"] == []
    assert chunk["doc_type_kwd"] == "text"


async def test_create_chunk_shape_with_tag_kwd(client: TestClient, owner: tuple[str, str]) -> None:
    """POST z tag_kwd w żądaniu → data.chunk ma tag_kwd (upstream CHK:1128-1130, :1167)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.post(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"content": "Ala ma kota", "tag_kwd": ["zwierzęta"]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    chunk = body["data"]["chunk"]
    assert len(chunk) == CREATED_KEYS + 1
    assert chunk["tag_kwd"] == ["zwierzęta"]


async def test_create_chunk_empty_content(client: TestClient, owner: tuple[str, str]) -> None:
    """POST {"content": ""} → code 102 „`content` is required" (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.post(
        chunks_url(dataset_id, document_id), headers=_bearer(token), json={"content": ""}
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "`content` is required"


async def test_create_chunk_questions_not_list(client: TestClient, owner: tuple[str, str]) -> None:
    """POST {"questions": "q"} → 102 „`questions` is required to be a list" (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.post(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"content": "x", "questions": "q"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "`questions` is required to be a list"


async def test_list_chunks(client: TestClient, owner: tuple[str, str]) -> None:
    """GET ?page=1&page_size=30 → total 1, 12 kluczy, available, positions [], doc.id (brief)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    create_chunk(client, token, dataset_id, document_id)
    response = client.get(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        params={"page": 1, "page_size": 30},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["total"] == 1
    items = body["data"]["chunks"]
    assert len(items[0]) == ITEM_KEYS
    assert items[0]["available"] is True
    assert items[0]["positions"] == []
    assert body["data"]["doc"]["id"] == document_id


async def test_list_chunks_id_filter_miss(client: TestClient, owner: tuple[str, str]) -> None:
    """GET ?id=0000000000000000 → code 102 „Chunk not found: <A>/0000000000000000" (brief)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.get(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        params={"id": "0" * ID_LEN},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == f"Chunk not found: {dataset_id}/{'0' * ID_LEN}"


def list_data(
    client: TestClient, token: str, dataset_id: str, document_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """GET …/chunks z asercją code 0; zwraca ``data`` odpowiedzi."""
    response = client.get(
        chunks_url(dataset_id, document_id), headers=_bearer(token), params=params
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    data: dict[str, Any] = body["data"]
    return data


async def test_list_chunks_available_filter(client: TestClient, owner: tuple[str, str]) -> None:
    """Brak parametru → wszystkie; available=true → włączone; available=false → wyłączone (C2)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    enabled = create_chunk(client, token, dataset_id, document_id, content="włączony")
    disabled = create_chunk(client, token, dataset_id, document_id, content="wyłączony")
    switched = client.patch(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"chunk_ids": [disabled], "available": False},
    )
    assert switched.status_code == _OK
    assert switched.json()["code"] == 0, switched.json()

    all_data = list_data(client, token, dataset_id, document_id, {})
    assert all_data["total"] == 2  # noqa: PLR2004 — dwa chunki bez filtra
    assert [c["id"] for c in all_data["chunks"]] == [enabled, disabled]

    on_data = list_data(client, token, dataset_id, document_id, {"available": "true"})
    assert on_data["total"] == 1
    assert [c["id"] for c in on_data["chunks"]] == [enabled]

    off_data = list_data(client, token, dataset_id, document_id, {"available": "false"})
    assert off_data["total"] == 1
    assert [c["id"] for c in off_data["chunks"]] == [disabled]


@pytest.mark.parametrize("value", ["false", "1", "True", ""])
async def test_list_chunks_available_other_values_only_disabled(
    client: TestClient, owner: tuple[str, str], value: str
) -> None:
    """Każda wartość poza ``"true"`` → tylko wyłączone (upstream CHK:580)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    enabled = create_chunk(client, token, dataset_id, document_id, content="włączony")
    disabled = create_chunk(client, token, dataset_id, document_id, content="wyłączony")
    client.patch(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"chunk_ids": [disabled], "available": False},
    )
    data = list_data(client, token, dataset_id, document_id, {"available": value})
    assert data["total"] == 1
    assert [c["id"] for c in data["chunks"]] == [disabled]
    assert enabled not in [c["id"] for c in data["chunks"]]


async def test_list_chunks_available_filter_pagination(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """page_size=1 z available=true → jedna pozycja na stronę, total z filtrem (C2)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    first = create_chunk(client, token, dataset_id, document_id, content="pierwszy")
    second = create_chunk(client, token, dataset_id, document_id, content="drugi")
    disabled = create_chunk(client, token, dataset_id, document_id, content="wyłączony")
    client.patch(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"chunk_ids": [disabled], "available": False},
    )
    data = list_data(
        client, token, dataset_id, document_id, {"available": "true", "page_size": 1, "page": 1}
    )
    assert data["total"] == 2  # noqa: PLR2004 — dwa włączone z trzech
    assert [c["id"] for c in data["chunks"]] == [first]
    page_two = list_data(
        client, token, dataset_id, document_id, {"available": "true", "page_size": 1, "page": 2}
    )
    assert [c["id"] for c in page_two["chunks"]] == [second]


async def test_list_chunks_available_ignored_in_v024_profile(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """Profil ``ragflow_0_24`` (nagłówek) ignoruje ``available`` → wszystkie (CONTRACT C2)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    enabled = create_chunk(client, token, dataset_id, document_id, content="włączony")
    disabled = create_chunk(client, token, dataset_id, document_id, content="wyłączony")
    client.patch(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"chunk_ids": [disabled], "available": False},
    )
    response = client.get(
        chunks_url(dataset_id, document_id),
        headers={**_bearer(token), "X-RAGFlow-Compat": "0.24"},
        params={"available": "true"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["total"] == 2  # noqa: PLR2004 — filtr zignorowany, oba chunki
    assert [c["id"] for c in body["data"]["chunks"]] == [enabled, disabled]


async def test_get_chunk(client: TestClient, owner: tuple[str, str]) -> None:
    """GET …/chunks/{cid} → 10 kluczy surowego dokumentu (złoto chunks_extras--08)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    chunk_id = create_chunk(client, token, dataset_id, document_id, important_keywords=["kot"])
    response = client.get(
        f"{chunks_url(dataset_id, document_id)}/{chunk_id}", headers=_bearer(token)
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert sorted(data.keys()) == sorted(
        [
            "content_with_weight",
            "create_time",
            "create_timestamp_flt",
            "doc_id",
            "doc_type_kwd",
            "docnm_kwd",
            "id",
            "important_kwd",
            "kb_id",
            "question_kwd",
        ]
    )
    assert len(data) == SOURCE_KEYS
    assert data["id"] == chunk_id
    assert data["content_with_weight"] == "Ala ma kota"
    assert data["doc_id"] == document_id
    assert data["kb_id"] == dataset_id
    assert data["docnm_kwd"] == "d.txt"
    assert data["doc_type_kwd"] == "text"
    assert data["important_kwd"] == ["kot"]
    assert data["question_kwd"] == []


async def test_get_chunk_with_tag_kwd(frozen_client: TestClient, owner: tuple[str, str]) -> None:
    """GET …/chunks/{cid} chunka z ``tag_kwd`` → 11 kluczy, ``tag_kwd`` obecne (FIXA p. 2).

    Upstream zwraca surowy dokument magazynu (``chunk_api.py:639-656``), a ten ma
    ``tag_kwd`` ustawione przez POST/PATCH — brak klucza tylko dla chunka bez tagów.
    """
    token, _user_id = owner
    dataset_id = create_dataset(frozen_client, token)
    document_id = upload(frozen_client, token, dataset_id)
    chunk_id = create_chunk(frozen_client, token, dataset_id, document_id, tag_kwd=["zwierzęta"])
    response = frozen_client.get(
        f"{chunks_url(dataset_id, document_id)}/{chunk_id}", headers=_bearer(token)
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert len(body["data"]) == SOURCE_KEYS + 1
    assert body["data"]["tag_kwd"] == ["zwierzęta"]


async def test_get_chunk_unknown_id(client: TestClient, owner: tuple[str, str]) -> None:
    """GET …/chunks/zzz → code 102 „Chunk not found!" (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.get(f"{chunks_url(dataset_id, document_id)}/zzz", headers=_bearer(token))
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "Chunk not found!"


async def test_update_chunk_patch_and_put(client: TestClient, owner: tuple[str, str]) -> None:
    """PATCH i PUT {"content": "Nowa"} → code 0, brak data; GET pokazuje treść (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    chunk_id = create_chunk(client, token, dataset_id, document_id)
    for method in ("PATCH", "PUT"):
        response = client.request(
            method,
            f"{chunks_url(dataset_id, document_id)}/{chunk_id}",
            headers=_bearer(token),
            json={"content": "Nowa"},
        )
        assert response.status_code == _OK
        body = response.json()
        assert body["code"] == 0, body
        assert "data" not in body
    listed = client.get(chunks_url(dataset_id, document_id), headers=_bearer(token))
    assert listed.json()["data"]["chunks"][0]["content"] == "Nowa"


async def test_update_chunk_twice_same_ms(
    frozen_client: TestClient, owner: tuple[str, str]
) -> None:
    """Dwa identyczne PATCH-e w tej samej ms → oba code 0 (FIXA p. 1; UPDATE bez zmian).

    MySQL przy ``UPDATE`` bez zmiany wiersza zwraca rowcount 0 — liczy się dopasowanie
    wiersza, nie liczba zmienionych (inaczej fałszywe 102 „Index updating failure").
    """
    token, _user_id = owner
    dataset_id = create_dataset(frozen_client, token)
    document_id = upload(frozen_client, token, dataset_id)
    chunk_id = create_chunk(
        frozen_client, token, dataset_id, document_id, important_keywords=["kot"]
    )
    patch = {"content": "Ala ma kota", "important_keywords": ["kot"], "available": True}
    for _ in range(2):
        response = frozen_client.patch(
            f"{chunks_url(dataset_id, document_id)}/{chunk_id}",
            headers=_bearer(token),
            json=patch,
        )
        assert response.status_code == _OK
        body = response.json()
        assert body["code"] == 0, body
        assert "data" not in body


async def test_switch_chunks_same_value_same_ms(
    frozen_client: TestClient, owner: tuple[str, str]
) -> None:
    """Przełączenie na wartość już ustawioną (ta sama ms) → code 0, data true (FIXA p. 1).

    Chunek ręczny powstaje jako ``available`` = true; switch ``available_int: 1`` nie zmienia
    wiersza (rowcount 0), więc liczenie zmienionych wierszy dawałoby fałszywe 102.
    """
    token, _user_id = owner
    dataset_id = create_dataset(frozen_client, token)
    document_id = upload(frozen_client, token, dataset_id)
    chunk_id = create_chunk(frozen_client, token, dataset_id, document_id)
    for _ in range(2):
        response = frozen_client.patch(
            chunks_url(dataset_id, document_id),
            headers=_bearer(token),
            json={"chunk_ids": [chunk_id], "available_int": 1},
        )
        assert response.status_code == _OK
        body = response.json()
        assert body["code"] == 0, body
        assert body["data"] is True


async def test_switch_chunks(client: TestClient, owner: tuple[str, str]) -> None:
    """PATCH …/chunks {"chunk_ids", "available_int": 0} → data true; GET available false (brief)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    chunk_id = create_chunk(client, token, dataset_id, document_id)
    response = client.patch(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"chunk_ids": [chunk_id], "available_int": 0},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"] is True
    listed = client.get(chunks_url(dataset_id, document_id), headers=_bearer(token))
    assert listed.json()["data"]["chunks"][0]["available"] is False


async def test_switch_chunks_missing_id(client: TestClient, owner: tuple[str, str]) -> None:
    """PATCH …/chunks z nieistniejącym chunk_id → 102 „Index updating failure" (CHK:1352)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.patch(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"chunk_ids": ["0" * ID_LEN], "available": True},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == "Index updating failure"


async def test_update_chunk_missing_id(client: TestClient, owner: tuple[str, str]) -> None:
    """PATCH …/chunks/{cid} nieistniejącego chunka → 102 „Can't find this chunk <id>” (CHK:1251)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.patch(
        f"{chunks_url(dataset_id, document_id)}/{'0' * ID_LEN}",
        headers=_bearer(token),
        json={"content": "Nowa"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == f"Can't find this chunk {'0' * ID_LEN}"


async def test_delete_chunks(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE {"chunk_ids": [cid]} → code 0; GET listy total 0 (przykład briefu)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    chunk_id = create_chunk(client, token, dataset_id, document_id)
    response = client.request(
        "DELETE",
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"chunk_ids": [chunk_id]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    listed = client.get(chunks_url(dataset_id, document_id), headers=_bearer(token))
    assert listed.json()["data"]["total"] == 0


async def test_delete_chunks_duplicate_ids(client: TestClient, owner: tuple[str, str]) -> None:
    """DELETE z powtórzonym id → code 0, data.success_count i errors (CHK:1223-1226)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    chunk_id = create_chunk(client, token, dataset_id, document_id)
    response = client.request(
        "DELETE",
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"chunk_ids": [chunk_id, chunk_id]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["success_count"] == 1
    assert body["data"]["errors"] == [f"Duplicate chunk ids: {chunk_id}"]


async def test_list_chunks_foreign_user_denied(
    client: TestClient, owner: tuple[str, str], bob_key: str
) -> None:
    """Bob czyta chunki datasetu Alice → koperta 102 „You don't own the dataset" (złoto --22)."""
    token, _user_id = owner
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    create_chunk(client, token, dataset_id, document_id)
    response = client.get(chunks_url(dataset_id, document_id), headers=_bearer(bob_key))
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == f"You don't own the dataset {dataset_id}."
