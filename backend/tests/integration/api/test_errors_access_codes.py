"""Kody odmowy i 401 na trasach datasets/documents/chunks/retrieval (K11 §10c p. 9-10).

Wzorzec: ``docs/contracts/golden-E2.md`` §„Nagrane pliki" + pliki złota
``backend/tests/contract/golden/v0.27.2/<katalog>/errors_access--NN.json``.
Tests marked ``db``/``fakellm`` — stos ``verify.sh``/``tools/dev/up.sh test``.

Pokrycie łatki mutacji ``e2-1-401-missing-auth.patch``: testy 401 (brak/ zły klucz).
"""

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
_UNAUTHORIZED = 401
_DATA_ERROR = int(RetCode.DATA_ERROR)  # 102
_AUTHENTICATION_ERROR = int(RetCode.AUTHENTICATION_ERROR)  # 109
_MISSING_ID = "0" * 32
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście

_OWNER_EMAIL = "owner@x.pl"
_SECOND_EMAIL = "second@x.pl"

# Koperta 401 dosłownie ze złota (datasets/errors_access--36.json).
_UNAUTHORIZED_BODY = {
    "code": 401,
    "data": None,
    "message": "<Unauthorized '401: Unauthorized'>",
}


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
    """Właściciel zasobów: (token, user_id)."""
    return await make_key(users_svc, keys_svc, _OWNER_EMAIL)


@pytest.fixture
async def second(
    users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None
) -> tuple[str, str]:
    """Drugi użytkownik (obcy wobec zasobów właściciela): (token, user_id)."""
    return await make_key(users_svc, keys_svc, _SECOND_EMAIL)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


def create_dataset(client: TestClient, token: str) -> str:
    """POST /datasets z asercją code 0; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": "wd_err1"})
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


def chunks_url(dataset_id: str, document_id: str) -> str:
    """Wspólny prefiks tras chunków (C3.5)."""
    return f"/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks"


def create_chunk(client: TestClient, token: str, dataset_id: str, document_id: str) -> str:
    """POST …/chunks z domyślną treścią; zwraca id chunka."""
    response = client.post(
        chunks_url(dataset_id, document_id),
        headers=_bearer(token),
        json={"content": "Ala ma kota"},
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    chunk_id: str = payload["data"]["chunk"]["id"]
    return chunk_id


def _refusal(response: Any, code: int, message: str) -> None:
    """Wspólna asercja koperty odmowy: HTTP 200, kod, komunikat i brak ``data``."""
    assert response.status_code == _OK
    body = response.json()
    assert body == {"code": code, "message": message}


# --- 401: brak i zły nagłówek Authorization (złoto --36..--41) ---


def test_missing_authorization_returns_401(client: TestClient) -> None:
    """GET /datasets bez nagłówka Authorization → HTTP 401 z kopertą złota (--36)."""
    response = client.get("/api/v1/datasets")
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == _UNAUTHORIZED_BODY


def test_bad_api_key_returns_401(client: TestClient) -> None:
    """GET /datasets z nieznanym kluczem → HTTP 401 z tą samą kopertą (--37)."""
    response = client.get("/api/v1/datasets", headers=_bearer("not-a-real-key"))
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == _UNAUTHORIZED_BODY


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/v1/chats"), ("POST", "/api/v1/retrieval")],
)
def test_missing_authorization_other_routes(client: TestClient, method: str, path: str) -> None:
    """Brak nagłówka na /chats i /retrieval → HTTP 401 (złoto --38/--40)."""
    response = client.request(method, path, json={})
    assert response.status_code == _UNAUTHORIZED
    assert response.json() == _UNAUTHORIZED_BODY


# --- cudzy dataset kluczem drugiego użytkownika ---


def test_dataset_get_foreign_lacks_permission(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """GET /datasets/{id} obcym kluczem → 102 „lacks permission for dataset" (--11)."""
    token, _ = owner
    second_token, second_id = second
    dataset_id = create_dataset(client, token)
    response = client.get(f"/api/v1/datasets/{dataset_id}", headers=_bearer(second_token))
    _refusal(
        response,
        _DATA_ERROR,
        f"User '{second_id}' lacks permission for dataset '{dataset_id}'",
    )


def test_dataset_update_foreign_lacks_permission(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """PUT /datasets/{id} obcym kluczem → 102 + komunikat złota; nazwa bez zmian (--10)."""
    token, _ = owner
    second_token, second_id = second
    dataset_id = create_dataset(client, token)
    response = client.put(
        f"/api/v1/datasets/{dataset_id}",
        headers=_bearer(second_token),
        json={"name": "intruder"},
    )
    _refusal(
        response,
        _DATA_ERROR,
        f"User '{second_id}' lacks permission for dataset '{dataset_id}'",
    )
    fresh = client.get(f"/api/v1/datasets/{dataset_id}", headers=_bearer(token))
    assert fresh.json()["data"]["name"] == "wd_err1"


def test_dataset_list_filter_foreign_lacks_permission(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """GET /datasets?id=<cudzy> → 102 „lacks permission for dataset" (--12)."""
    token, _ = owner
    second_token, second_id = second
    dataset_id = create_dataset(client, token)
    response = client.get(
        "/api/v1/datasets", params={"id": dataset_id}, headers=_bearer(second_token)
    )
    _refusal(
        response,
        _DATA_ERROR,
        f"User '{second_id}' lacks permission for dataset '{dataset_id}'",
    )


def test_datasets_delete_foreign_leaves_dataset(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """DELETE /datasets obcym kluczem → 102 i dataset właściciela nadal istnieje (--53)."""
    token, _ = owner
    second_token, second_id = second
    dataset_id = create_dataset(client, token)
    response = client.request(
        "DELETE", "/api/v1/datasets", headers=_bearer(second_token), json={"ids": [dataset_id]}
    )
    _refusal(
        response,
        _DATA_ERROR,
        f"User '{second_id}' lacks permission for datasets: '{dataset_id}'",
    )
    fresh = client.get(f"/api/v1/datasets/{dataset_id}", headers=_bearer(token))
    assert fresh.json()["code"] == 0


def test_dataset_get_missing_lacks_permission(client: TestClient, owner: tuple[str, str]) -> None:
    """GET /datasets/<32 zera> kluczem właściciela → 102 z jego id i żądanym id (--42)."""
    token, user_id = owner
    response = client.get(f"/api/v1/datasets/{_MISSING_ID}", headers=_bearer(token))
    _refusal(
        response,
        _DATA_ERROR,
        f"User '{user_id}' lacks permission for dataset '{_MISSING_ID}'",
    )


# --- dokumenty ---


def test_upload_foreign_dataset_no_authorization(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """POST …/documents obcym kluczem → 109 „no authorization", lista bez zmian (--13)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(second_token),
        files={"file": ("d.txt", b"hello")},
    )
    _refusal(response, _AUTHENTICATION_ERROR, "no authorization")
    listed = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert listed.json()["data"]["total"] == 0


def test_documents_list_foreign_not_own_dataset(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """GET …/documents obcym kluczem → 102 „You don't own the dataset <id>. " (--14)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    response = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(second_token))
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {dataset_id}. ")


def test_document_download_foreign_document_not_found(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """GET …/documents/{id} obcym kluczem → 102 „document not found", nie bajty (--15)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents/{document_id}", headers=_bearer(second_token)
    )
    _refusal(response, _DATA_ERROR, "document not found")
    assert b"hello" not in response.content


def test_document_patch_foreign_dont_own_dataset(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """PATCH …/documents/{id} obcym kluczem → 102 „you don't own the dataset" (--16)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/{document_id}",
        headers=_bearer(second_token),
        json={"meta_fields": {"author": "intruder"}},
    )
    _refusal(response, _DATA_ERROR, "you don't own the dataset")


def test_documents_delete_foreign_leaves_document(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """DELETE …/documents obcym kluczem → 102 i dokument właściciela nadal istnieje (--50)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    response = client.request(
        "DELETE",
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(second_token),
        json={"ids": [document_id]},
    )
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {dataset_id}. ")
    listed = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert listed.json()["data"]["total"] == 1


def test_document_download_missing_document_not_found(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """GET …/documents/<32 zera> kluczem właściciela → 102 „document not found" (--47)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/documents/{_MISSING_ID}", headers=_bearer(token)
    )
    _refusal(response, _DATA_ERROR, "document not found")


# --- chunki ---


def test_chunks_list_foreign_not_own_dataset(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """GET …/chunks obcym kluczem → 102 „You don't own the dataset <id>." (--22)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    create_chunk(client, token, dataset_id, document_id)
    response = client.get(chunks_url(dataset_id, document_id), headers=_bearer(second_token))
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {dataset_id}.")


def test_chunks_delete_foreign_leaves_chunk(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """DELETE …/chunks obcym kluczem → 102 i chunk właściciela nadal istnieje (--49)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    document_id = upload(client, token, dataset_id)
    chunk_id = create_chunk(client, token, dataset_id, document_id)
    response = client.request(
        "DELETE",
        chunks_url(dataset_id, document_id),
        headers=_bearer(second_token),
        json={"chunk_ids": [chunk_id]},
    )
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {dataset_id}.")
    listed = client.get(chunks_url(dataset_id, document_id), headers=_bearer(token))
    assert listed.json()["data"]["total"] == 1


def test_chunks_list_missing_document_message(client: TestClient, owner: tuple[str, str]) -> None:
    """GET …/<32 zera>/chunks kluczem właściciela → 102 „you don't own the document <id>" (--48)."""
    token, _ = owner
    dataset_id = create_dataset(client, token)
    response = client.get(chunks_url(dataset_id, _MISSING_ID), headers=_bearer(token))
    _refusal(response, _DATA_ERROR, f"you don't own the document {_MISSING_ID}")


# --- retrieval ---


def test_retrieval_foreign_not_own_dataset(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """POST /retrieval na cudzym datasecie → 102 „You don't own the dataset <id>." (--24)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    response = client.post(
        "/api/v1/retrieval",
        headers=_bearer(second_token),
        json={"question": "x", "dataset_ids": [dataset_id]},
    )
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {dataset_id}.")


def test_datasets_search_foreign_not_own_dataset(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """POST /datasets/search na cudzym datasecie → 102 (upstream: `accessible` = False)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    response = client.post(
        "/api/v1/datasets/search",
        headers=_bearer(second_token),
        json={"question": "x", "dataset_ids": [dataset_id]},
    )
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {dataset_id}.")


def test_dataset_path_search_foreign_not_own_dataset(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """POST /datasets/{ds}/search na cudzym datasecie → 102 (jak --24 dla /retrieval)."""
    token, _ = owner
    second_token, _second_id = second
    dataset_id = create_dataset(client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/search",
        headers=_bearer(second_token),
        json={"question": "x"},
    )
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {dataset_id}.")


def test_datasets_search_missing_dataset_not_own(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """POST /datasets/search z nieistniejącym datasetem → 102 (upstream: `accessible` = False)."""
    token, _ = owner
    response = client.post(
        "/api/v1/datasets/search",
        headers=_bearer(token),
        json={"question": "x", "dataset_ids": [_MISSING_ID]},
    )
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {_MISSING_ID}.")


def test_dataset_path_search_missing_dataset_not_own(
    client: TestClient, owner: tuple[str, str]
) -> None:
    """POST /datasets/{ds}/search z nieistniejącym datasetem → 102 (upstream: `accessible`)."""
    token, _ = owner
    response = client.post(
        f"/api/v1/datasets/{_MISSING_ID}/search", headers=_bearer(token), json={"question": "x"}
    )
    _refusal(response, _DATA_ERROR, f"You don't own the dataset {_MISSING_ID}.")


# --- czaty i sesje: odmowa 109 ``no authorization`` z ``data: false`` ---


def create_chat(client: TestClient, token: str, name: str = "wd_err2_chat") -> str:
    """POST /chats z asercją code 0; zwraca id czatu."""
    response = client.post("/api/v1/chats", headers=_bearer(token), json={"name": name})
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    chat_id: str = payload["data"]["id"]
    return chat_id


def create_session(client: TestClient, token: str, chat_id: str) -> str:
    """POST …/sessions z asercją code 0; zwraca id sesji."""
    response = client.post(
        f"/api/v1/chats/{chat_id}/sessions", headers=_bearer(token), json={"name": "wd_err2_s"}
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    session_id: str = payload["data"]["id"]
    return session_id


def _no_authorization(response: Any) -> None:
    """Koperta ``_ensure_owned_chat``: 109 + ``data: false`` (upstream chat_api.py:190)."""
    assert response.status_code == _OK
    assert response.json() == {
        "code": _AUTHENTICATION_ERROR,
        "message": "no authorization",
        "data": False,
    }


def foreign_chat_requests(
    chat_id: str, session_id: str
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Żądania drugiego użytkownika na cudzym czacie i cudzej sesji (złoto --25..--34, --51)."""
    return [
        ("GET", f"/api/v1/chats/{chat_id}", None),
        ("PUT", f"/api/v1/chats/{chat_id}", {"name": "wd_err2_intruder"}),
        ("PATCH", f"/api/v1/chats/{chat_id}", {"name": "wd_err2_intruder"}),
        ("POST", f"/api/v1/chats/{chat_id}/sessions", {"name": "wd_err2_intruder"}),
        ("GET", f"/api/v1/chats/{chat_id}/sessions", None),
        ("GET", f"/api/v1/chats/{chat_id}/sessions/{session_id}", None),
        ("PATCH", f"/api/v1/chats/{chat_id}/sessions/{session_id}", {"name": "wd_err2_intruder"}),
        ("POST", f"/api/v1/chats/{chat_id}/completions", {"question": "x", "stream": False}),
        (
            "POST",
            "/api/v1/chat/completions",
            {"chat_id": chat_id, "stream": False, "messages": [{"role": "user", "content": "x"}]},
        ),
        ("DELETE", f"/api/v1/chats/{chat_id}/sessions", {"ids": [session_id]}),
    ]


def test_foreign_chat_and_session_refusals(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """Cudzy czat i cudza sesja obcym kluczem → 109 ``no authorization`` na każdej trasie.

    Złoto v0.27.2: ``chats___/errors_access--{25,26,27}``, ``chats___sessions/--{28,29,51}``,
    ``chats___sessions___/--{30,31}``, ``chats___completions/--33``, ``chat__completions/--34``.
    """
    token, _ = owner
    second_token, _second_id = second
    chat_id = create_chat(client, token)
    session_id = create_session(client, token, chat_id)
    for method, path, body in foreign_chat_requests(chat_id, session_id):
        response = client.request(method, path, headers=_bearer(second_token), json=body)
        _no_authorization(response)


def test_missing_chat_sessions_no_authorization(client: TestClient, owner: tuple[str, str]) -> None:
    """GET …/<32 zera>/sessions kluczem właściciela → 109 (złoto --46), nie 102."""
    token, _ = owner
    response = client.get(f"/api/v1/chats/{_MISSING_ID}/sessions", headers=_bearer(token))
    _no_authorization(response)


# --- K11 §10c p. 10: odmowa DELETE nie rusza zasobów właściciela ---


def test_chats_delete_foreign_leaves_chat(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """DELETE /chats cudzym kluczem → 102 ``Chat(<id>) not found.`` bez ``data`` (--52).

    Czat właściciela nadal istnieje (K11 §10c p. 10).
    """
    token, _ = owner
    second_token, _second_id = second
    chat_id = create_chat(client, token)
    response = client.request(
        "DELETE", "/api/v1/chats", headers=_bearer(second_token), json={"ids": [chat_id]}
    )
    _refusal(response, _DATA_ERROR, f"Chat({chat_id}) not found.")
    fresh = client.get(f"/api/v1/chats/{chat_id}", headers=_bearer(token))
    assert fresh.json()["code"] == 0, fresh.json()


def test_sessions_delete_foreign_leaves_session(
    client: TestClient, owner: tuple[str, str], second: tuple[str, str]
) -> None:
    """DELETE …/sessions cudzym kluczem → 109 ``no authorization`` (--51).

    Sesja właściciela nadal istnieje (K11 §10c p. 10).
    """
    token, _ = owner
    second_token, _second_id = second
    chat_id = create_chat(client, token)
    session_id = create_session(client, token, chat_id)
    response = client.request(
        "DELETE",
        f"/api/v1/chats/{chat_id}/sessions",
        headers=_bearer(second_token),
        json={"ids": [session_id]},
    )
    _no_authorization(response)
    listed = client.get(f"/api/v1/chats/{chat_id}/sessions", headers=_bearer(token))
    ids = [item["id"] for item in listed.json()["data"]]
    assert ids == [session_id]
