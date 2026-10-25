"""Testy HTTP tras retrievalu (brief E1-9a T4): /retrieval i /datasets/{id}/search.

Całość na jednym event loop (httpx ASGITransport + kontener bez lifespan): zadanie
parsowania wykonywane jak u workera — claim z kolejki i DocumentIngestService.run_parse_task
(wzór: tests/integration/retrieval i pipeline_helpers).
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
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
from tests.integration.ingest.pipeline_helpers import WORKER_ID, build_context, worker_queue

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
CHUNK_KEYS = 16  # klucze złota retrieval--06 → data.chunks.0
_TWO_DATASETS = 2  # liczba datasetów w teście wielo-datasetowym (wym. 1 briefu)
_OK = 200  # wszystkie koperty ragflow wracają jako HTTP 200

# Tekst dokumentu z wyróżnym słowem-kluczem (jak fixture recordera: smokwawelski).
TEXT = (
    "Legenda o smoku wawelskim należy do najstarszych opowieści Krakowa.\n"
    "Smokwawelski, bo tak przezwali go mieszczanie, zamieszkiwał jaskinię "
    "u stóp wzgórza, z której co noc wymuszał na mieszkańcach okup w postaci bydła.\n"
)

_OWNER_EMAIL = "owner@x.pl"
_BOB_EMAIL = "bob@x.pl"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Any) -> Settings:
    """Ustawienia auth + storage_root w katalogu tymczasowym (wzór test_documents_routes)."""
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


@pytest.fixture
async def owner(
    users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None
) -> tuple[str, str]:
    """Właściciel datasetu Alice: jawny token klucza API i user_id."""
    user = await users_svc.create(email=_OWNER_EMAIL, password=PASSWORD, is_superuser=False)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys_svc.create(principal)).token, user.id


@pytest.fixture
async def bob_key(users_svc: UserService, keys_svc: ApiKeyService, models_seeded: None) -> str:
    """Drugi użytkownik (Bob) z własnym kluczem API."""
    user = await users_svc.create(email=_BOB_EMAIL, password=PASSWORD, is_superuser=False)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys_svc.create(principal)).token


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[Container]:
    """Kontener aplikacji startowany ręcznie (ASGITransport nie odpala lifespan)."""
    instance = Container(settings)
    await instance.start()
    yield instance
    await instance.aclose()


@pytest.fixture
async def client(container: Container, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """httpx na ASGI tej samej pętli zdarzeń — DB tylko z jednej pętli (pool)."""
    app: FastAPI = create_app(settings, container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        yield c


async def create_dataset(client: httpx.AsyncClient, token: str) -> str:
    """POST /datasets z asercją code 0; zwraca id datasetu."""
    response = await client.post(
        "/api/v1/datasets", headers=_bearer(token), json={"name": "wd_retrieval"}
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == 0, payload
    return str(payload["data"]["id"])


async def upload_and_parse(
    client: httpx.AsyncClient, token: str, dataset_id: str, container: Container
) -> None:
    """Upload pliku, parse trasą API, zadanie parsowania wykonane jak u workera."""
    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        files={"file": ("legenda.txt", TEXT.encode())},
    )
    assert response.json()["code"] == 0, response.json()
    document_id = response.json()["data"][0]["id"]
    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents/parse",
        headers=_bearer(token),
        json={"document_ids": [document_id]},
    )
    assert response.json()["code"] == 0, response.json()
    queue = worker_queue(container)
    task = await queue.claim(WORKER_ID, ["parse_document"])
    assert task is not None, "zadanie musi być do wzięcia"
    await container.ingest.run_parse_task(task, build_context(container, task, queue))
    response = await client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        params={"page": 1, "page_size": 30},
    )
    assert response.json()["data"]["docs"][0]["run"] == "DONE", response.json()


@pytest.fixture
async def parsed_dataset_id(
    client: httpx.AsyncClient, owner: tuple[str, str], container: Container
) -> str:
    """Dataset Alice z jednym sparsowanym dokumentem (id datasetu)."""
    token, _user_id = owner
    dataset_id = await create_dataset(client, token)
    await upload_and_parse(client, token, dataset_id, container)
    return dataset_id


async def test_retrieval_route(
    client: httpx.AsyncClient, owner: tuple[str, str], parsed_dataset_id: str
) -> None:
    """Przykład briefu: code 0, total >= 1, chunks[0] 16 kluczy, doc_aggs lista agregatów."""
    token, _user_id = owner
    response = await client.post(
        "/api/v1/retrieval",
        headers=_bearer(token),
        json={"question": "smokwawelski", "dataset_ids": [parsed_dataset_id]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["total"] >= 1
    assert len(data["chunks"][0]) == CHUNK_KEYS
    assert all(sorted(agg) == ["count", "doc_id", "doc_name"] for agg in data["doc_aggs"])
    assert data["doc_aggs"][0]["count"] >= 1


async def test_datasets_search_route(
    client: httpx.AsyncClient, owner: tuple[str, str], parsed_dataset_id: str
) -> None:
    """POST /datasets/search — to samo co /retrieval (C4.3, dataset_ids z body)."""
    token, _user_id = owner
    response = await client.post(
        "/api/v1/datasets/search",
        headers=_bearer(token),
        json={"question": "smokwawelski", "dataset_ids": [parsed_dataset_id]},
    )
    assert response.json()["code"] == 0, response.json()
    assert response.json()["data"]["total"] >= 1


async def test_dataset_path_search_route(
    client: httpx.AsyncClient, owner: tuple[str, str], parsed_dataset_id: str
) -> None:
    """Przykład briefu: POST /datasets/{A}/search bez dataset_ids w body."""
    token, _user_id = owner
    response = await client.post(
        f"/api/v1/datasets/{parsed_dataset_id}/search",
        headers=_bearer(token),
        json={"question": "smokwawelski"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["total"] >= 1
    assert len(body["data"]["chunks"][0]) == CHUNK_KEYS


async def test_datasets_search_multiple_datasets(
    client: httpx.AsyncClient, owner: tuple[str, str], container: Container, parsed_dataset_id: str
) -> None:
    """POST /datasets/search z dwoma datasetami: wyniki i agregaty z obu (C4.3, wym. 1)."""
    token, _user_id = owner
    other_id = await create_dataset(client, token)
    await upload_and_parse(client, token, other_id, container)
    response = await client.post(
        "/api/v1/datasets/search",
        headers=_bearer(token),
        json={"question": "smokwawelski", "dataset_ids": [parsed_dataset_id, other_id]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["total"] >= _TWO_DATASETS
    assert len(data["doc_aggs"]) == _TWO_DATASETS
    assert {chunk["dataset_id"] for chunk in data["chunks"]} == {parsed_dataset_id, other_id}


async def test_empty_question_returns_empty(
    client: httpx.AsyncClient, owner: tuple[str, str], parsed_dataset_id: str
) -> None:
    """Przykład briefu: question "" → code 0 i pusty wynik (M6 p. 4)."""
    token, _user_id = owner
    response = await client.post(
        "/api/v1/retrieval",
        headers=_bearer(token),
        json={"question": "", "dataset_ids": [parsed_dataset_id]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"] == {"chunks": [], "doc_aggs": [], "total": 0}


_EMPTY = {"chunks": [], "doc_aggs": [], "total": 0}


async def test_datasets_search_no_matches_returns_empty(
    client: httpx.AsyncClient, owner: tuple[str, str], parsed_dataset_id: str
) -> None:
    """POST /datasets/search: pytanie bez trafień → code 0 i pusty wynik (M6 p. 4)."""
    token, _user_id = owner
    response = await client.post(
        "/api/v1/datasets/search",
        headers=_bearer(token),
        json={"question": "zupelnieobcehaslo", "dataset_ids": [parsed_dataset_id]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"] == _EMPTY


async def test_dataset_path_search_no_matches_returns_empty(
    client: httpx.AsyncClient, owner: tuple[str, str], parsed_dataset_id: str
) -> None:
    """POST /datasets/{ds}/search: pytanie bez trafień → code 0 i pusty wynik (M6 p. 4)."""
    token, _user_id = owner
    response = await client.post(
        f"/api/v1/datasets/{parsed_dataset_id}/search",
        headers=_bearer(token),
        json={"question": "zupelnieobcehaslo"},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"] == _EMPTY


async def test_foreign_user_denied(
    client: httpx.AsyncClient, bob_key: str, parsed_dataset_id: str
) -> None:
    """Przykład briefu: Bob na prywatnym datasetcie Alice → koperta 102 (złoto --24)."""
    response = await client.post(
        "/api/v1/retrieval",
        headers=_bearer(bob_key),
        json={"question": "x", "dataset_ids": [parsed_dataset_id]},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert body["message"] == f"You don't own the dataset {parsed_dataset_id}."
