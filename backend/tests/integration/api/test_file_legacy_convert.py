"""Testy ``POST /api/v1/file/convert`` (legacy) w obu profilach (E4-5b T4; CONTRACT §D4, §D6).

Wzór ``test_files_link_routes.py`` i ``test_file_legacy_routes.py``: kontener testowy (dostęp do
DB na weryfikację ``files.location`` i wiersza ``file2document``), principal nadpisany
``get_principal``, profil wybierany nagłówkiem ``X-RAGFlow-Compat: 0.24`` (K11 §10d p. 15).
Sprawdzamy: dokument datasetu na TYM SAMYM kluczu bloba pliku (bez kopii), wiersz
``file2document``, kształt odpowiedzi per profil (0.24: lista ``{document_id,file_id,id}``;
0.27: ``{"code":0,"data":true,"message":"success"}``), ``replace`` przenosi dokument między
datasetami zostawiając blob pliku (K16 §1 p. 4-5), a folder rozwija się do plików-liści.
"""

import dataclasses
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.db.repositories import documents as documents_repo
from app.db.repositories import files as files_repo
from app.db.repositories.models import set_dimension_if_null
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.datasets import DatasetService
from app.storage.keys import StorageKey
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME_MS
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

_HTTP_OK = 200
_V024 = {"X-RAGFlow-Compat": "0.24"}
_FILE_BYTES = b"Wawelski Dragon - legacy convert (E4-5b T4).\n"
_MISSING = uuid.uuid4().hex


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy + wymiar modelu embedding (dokument linkowany do datasetu)."""
    instance = await make_container(migrated_db, tmp_path)
    async with transaction(instance.sessionmaker) as session:
        await set_dimension_if_null(session, "e" * 32, 1024, TIME_MS)
    yield instance
    await instance.aclose()


def _principal(user_id: str, *, v024: bool) -> Principal:
    """Principal 0.24: ``auth_kind="api_key"`` (JWT w ``get_compat_profile`` wymusza 0.27)."""
    base = principal_for(user_id)
    return dataclasses.replace(base, auth_kind="api_key") if v024 else base


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja z nadpisanym ``get_principal`` (profil wybiera nagłówek CompatDep)."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (wzór ``test_files_routes.py``)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _dataset(container: Container, principal: Principal, name: str) -> str:
    """Dataset principala przez usługę; zwraca id."""
    return (await DatasetService(container).create(principal, name=name)).id


async def _folder(client: httpx.AsyncClient, name: str, parent_id: str | None = None) -> str:
    """POST /files (JSON, profil 0.27 — narzędzie) → id folderu."""
    payload: dict[str, Any] = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = await client.post("/api/v1/files", json=payload)
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    folder_id: str = body["data"]["id"]
    return folder_id


async def _upload(client: httpx.AsyncClient, name: str, parent_id: str | None = None) -> str:
    """POST /files (multipart, profil 0.27) → id pliku."""
    data = {"parent_id": parent_id} if parent_id is not None else None
    response = await client.post("/api/v1/files", files={"file": (name, _FILE_BYTES)}, data=data)
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    file_id: str = body["data"][0]["id"]
    return file_id


async def _convert(
    client: httpx.AsyncClient,
    file_ids: Sequence[str],
    kb_ids: Sequence[str],
    *,
    v024: bool,
) -> Any:
    """POST /file/convert; ``v024`` dokłada nagłówek zgodności 0.24."""
    return await client.post(
        "/api/v1/file/convert",
        headers=_V024 if v024 else None,
        json={"file_ids": list(file_ids), "kb_ids": list(kb_ids)},
    )


async def _docs(client: httpx.AsyncClient, dataset_id: str) -> list[dict[str, Any]]:
    """Lista dokumentów datasetu przez ``GET /datasets/{id}/documents``."""
    response = await client.get(f"/api/v1/datasets/{dataset_id}/documents")
    body = response.json()
    assert body["code"] == RetCode.SUCCESS, body
    docs: list[dict[str, Any]] = body["data"]["docs"]
    return docs


async def _stored_link(sm: async_sessionmaker[AsyncSession], file_id: str) -> tuple[Any, list[Any]]:
    """(wiersz ``files``, wiersze ``file2document``) z bazy dla pliku."""
    async with transaction(sm) as session:
        row = await files_repo.get(session, file_id)
        links = await files_repo.list_links(session, file_id)
    assert row is not None
    return row, links


async def _document(sm: async_sessionmaker[AsyncSession], document_id: str) -> Any:
    """Wiersz ``documents`` z bazy (do porównania ``location``)."""
    async with transaction(sm) as session:
        return await documents_repo.get(session, document_id)


async def test_convert_v027_links_file_blob_without_copy(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """0.27: ``data true``; dokument na kluczu bloba + ``file2document`` (K16 §1 p. 4)."""
    alice = principal_for(await seed_user(sm))
    dataset_id = await _dataset(container, alice, "wd_e4b_t4_v027")
    async with _client(_app(container, alice)) as client:
        file_id = await _upload(client, "wd_e4b_t4_v027.txt")
        response = await _convert(client, [file_id], [dataset_id], v024=False)
        docs = await _docs(client, dataset_id)

    assert response.status_code == _HTTP_OK, response.text
    assert response.json() == {"code": RetCode.SUCCESS, "data": True, "message": "success"}

    file_row, links = await _stored_link(sm, file_id)
    assert file_row.location is not None and file_row.location.startswith("filemanager/")
    assert len(links) == 1 and links[0].file_id == file_id
    document = await _document(sm, links[0].document_id)
    assert document.location == file_row.location
    assert [doc["id"] for doc in docs] == [links[0].document_id]


async def test_convert_v024_returns_link_rows_for_file(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """0.24: ``data`` to lista ``{document_id,file_id,id}``; dokument na kluczu bloba pliku."""
    alice = _principal(await seed_user(sm), v024=True)
    dataset_id = await _dataset(container, alice, "wd_e4b_t4_v024")
    async with _client(_app(container, alice)) as client:
        file_id = await _upload(client, "wd_e4b_t4_v024.txt")
        response = await _convert(client, [file_id], [dataset_id], v024=True)

    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS and body["message"] == "success"
    assert isinstance(body["data"], list) and len(body["data"]) == 1
    link = body["data"][0]
    assert set(link) == {"document_id", "file_id", "id"}
    assert link["file_id"] == file_id

    file_row, links = await _stored_link(sm, file_id)
    assert [row.id for row in links] == [link["id"]]
    document = await _document(sm, link["document_id"])
    assert document.location == file_row.location


@pytest.mark.parametrize("v024", [False, True], ids=["v027", "v024"])
async def test_convert_replace_moves_document_and_keeps_blob(
    container: Container, sm: async_sessionmaker[AsyncSession], v024: bool
) -> None:
    """``replace``: dokument znika z pierwszego datasetu, blob pliku zostaje (K16 §1 p. 5)."""
    alice = _principal(await seed_user(sm), v024=v024)
    first = await _dataset(container, alice, "wd_e4b_t4_pierwszy")
    second = await _dataset(container, alice, "wd_e4b_t4_drugi")
    async with _client(_app(container, alice)) as client:
        file_id = await _upload(client, "wd_e4b_t4_replace.txt")
        assert (await _convert(client, [file_id], [first], v024=v024)).json()["code"] == 0
        assert (await _convert(client, [file_id], [second], v024=v024)).json()["code"] == 0
        first_docs = await _docs(client, first)
        second_docs = await _docs(client, second)

    assert first_docs == []
    assert len(second_docs) == 1
    file_row, links = await _stored_link(sm, file_id)
    assert len(links) == 1
    assert links[0].document_id == second_docs[0]["id"]
    # Blob pliku należy do wiersza ``files`` — ``replace`` go nie kasuje (K16 §1 p. 5).
    assert file_row.location is not None
    assert await container.storage.exists(StorageKey(file_row.location))


async def test_convert_folder_expands_to_leaf_files_v024(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """0.24: convert folderu rozwija się do plików-liści — dwa wiązania (K16 §1 p. 4)."""
    alice = _principal(await seed_user(sm), v024=True)
    dataset_id = await _dataset(container, alice, "wd_e4b_t4_folder")
    async with _client(_app(container, alice)) as client:
        folder_id = await _folder(client, "wd_e4b_t4_katalog")
        first = await _upload(client, "wd_e4b_t4_a.txt", folder_id)
        second = await _upload(client, "wd_e4b_t4_b.txt", folder_id)
        response = await _convert(client, [folder_id], [dataset_id], v024=True)
        docs = await _docs(client, dataset_id)

    assert response.status_code == _HTTP_OK, response.text
    body = response.json()
    assert body["code"] == RetCode.SUCCESS
    links = body["data"]
    assert [link["file_id"] for link in links] == [first, second]
    # Kolejność listy dokumentów datasetu nie jest przedmiotem testu (wiązań pilnuje file_id).
    assert {doc["id"] for doc in docs} == {link["document_id"] for link in links}
    assert len(docs) == len(links)
