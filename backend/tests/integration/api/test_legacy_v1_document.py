"""Trasy legacy ``/v1/document/*`` (brief E2-2a T4) na żywej bazie i kontenerze.

Pięć tras v0.24 wyłącznie (K11 §10d p. 17) z JWT legacy — nagłówkiem ``Authorization``
z logowania ``/api/v1/auth/login`` (jak krok ``auth: jwt`` harnessu). Kształty kopert są
zgodne ze złotem scenariusza ``documents_extras`` (kroki 17, 18, 20, 22, 24, 26, 30 i 32):
``change_status`` mapuje doc_id na status, ``run`` oddaje ``data: true``, ``upload_info`` opis
pliku z ``preview_url: null``, ``get`` surowe bajty (``text/plain``), ``thumbnails`` pustą mapę.

Test bezpieczeństwa (wymaganie 5 i 6 briefu): użytkownik B nie może ani zmienić statusu,
ani uruchomić parsowania, ani pobrać pliku, ani zobaczyć miniatury dokumentu A — każda trasa
odpowiada odmową 108 „No authorization." i stan dokumentu A się nie zmienia (CONTRACT C0 p. 9).
"""

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.main import create_app
from tests.integration.datasets.conftest import seed_default_models

pytestmark = pytest.mark.db

_OK = 200
_UNAUTHORIZED = 401
_CODE_SUCCESS = 0
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście

_A_EMAIL = "legacy-doc-a@x.pl"
_B_EMAIL = "legacy-doc-b@x.pl"

_MISSING_ID = "0" * 32
ID_LEN = 32  # identyfikatory WD: 32 znaki hex (K5 §1)
_TEXT = b"Legenda o smoku wawelskim.\n"
# Komunikat odmowy wszystkich czterech tras z dokumentem (upstream DOC:602, CONTRACT C0 p. 9).
_DENIED = {"code": int(RetCode.PERMISSION_ERROR), "message": "No authorization."}
_UPLOAD_INFO_KEYS = {
    "id",
    "name",
    "size",
    "extension",
    "mime_type",
    "created_by",
    "created_at",
    "preview_url",
}
_RUN_BODIES: tuple[dict[str, Any], ...] = (
    {"run": "1"},
    {"run": "2"},
    {"run": "1", "delete": True},
)


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Ustawienia auth + storage w katalogu tymczasowym (wzór briefu)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie testu, storage w tmp_path (wzór testów API)."""
    instance = Container(settings)
    await instance.start()
    yield instance
    await instance.aclose()


@pytest.fixture
async def models_seeded(sm: async_sessionmaker[AsyncSession]) -> None:
    """fake-embed-1024 (embedding, 1024) i fake-chat (chat) — bez wymiaru nie ma datasetu."""
    await seed_default_models(sm)


@pytest.fixture
def app(settings: Settings, container: Container, models_seeded: None) -> FastAPI:
    """Aplikacja na tym samym kontenerze i bazie co test (bez sieci, ASGITransport)."""
    return create_app(settings, container)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient ASGI; testy JWT używają nagłówka z logowania, nie klucza API."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _create_user(container: Container, email: str) -> str:
    """Konto lokalne (bez admina); zwraca jego id."""
    assert container.users is not None
    user = await container.users.create(email=email, password=PASSWORD, is_superuser=False)
    return user.id


async def _login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    """Nagłówki JWT legacy z logowania (wartość nagłówka ``Authorization`` z odpowiedzi)."""
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == _OK, response.text
    assert response.json()["code"] == _CODE_SUCCESS
    return {"Authorization": response.headers["authorization"]}


def _data(response: httpx.Response) -> Any:
    """``data`` koperty sukcesu (HTTP 200, code 0)."""
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_SUCCESS, payload
    return payload["data"]


async def _dataset_with_document(
    client: httpx.AsyncClient, headers: dict[str, str], name: str
) -> tuple[str, str]:
    """Dataset właściciela nagłówków + wgrany dokument; zwraca (dataset_id, document_id)."""
    created = cast(
        "dict[str, Any]",
        _data(await client.post("/api/v1/datasets", headers=headers, json={"name": name})),
    )
    dataset_id = cast(str, created["id"])
    uploaded = cast(
        "list[dict[str, Any]]",
        _data(
            await client.post(
                f"/api/v1/datasets/{dataset_id}/documents",
                headers=headers,
                files={"file": ("smok.txt", _TEXT, "text/plain")},
            )
        ),
    )
    return dataset_id, cast(str, uploaded[0]["id"])


async def _document_state(
    client: httpx.AsyncClient, headers: dict[str, str], dataset_id: str
) -> dict[str, Any]:
    """Stan pierwszego dokumentu datasetu: ``run`` i ``status`` (złoto listy dokumentów)."""
    listed = cast(
        "dict[str, Any]",
        _data(
            await client.get(
                f"/api/v1/datasets/{dataset_id}/documents",
                headers=headers,
                params={"page": 1, "page_size": 30},
            )
        ),
    )
    doc = cast("list[dict[str, Any]]", listed["docs"])[0]
    return {"run": doc["run"], "status": doc["status"]}


async def test_change_status_and_run_of_owner_are_success(
    client: httpx.AsyncClient, container: Container
) -> None:
    """Właściciel: change_status (kroki 17/18) i run (20/22/24) dają koperty złota."""
    await _create_user(container, _A_EMAIL)
    headers = await _login(client, _A_EMAIL)
    _, document_id = await _dataset_with_document(client, headers, "wd_v1_doc_a")

    for status in ("0", "1"):
        response = await client.post(
            "/v1/document/change_status",
            headers=headers,
            json={"doc_ids": [document_id], "status": status},
        )
        assert response.status_code == _OK, response.text
        assert response.json() == {
            "code": _CODE_SUCCESS,
            "message": "success",
            "data": {document_id: {"status": status}},
        }

    for body in _RUN_BODIES:
        response = await client.post(
            "/v1/document/run", headers=headers, json={**body, "doc_ids": [document_id]}
        )
        assert response.status_code == _OK, response.text
        assert response.json() == {"code": _CODE_SUCCESS, "message": "success", "data": True}


async def test_upload_info_get_and_thumbnails_of_owner(
    client: httpx.AsyncClient, container: Container
) -> None:
    """Właściciel: upload_info (26), get (30) i thumbnails (32) — kształty i treść złota."""
    user_id = await _create_user(container, _A_EMAIL)
    headers = await _login(client, _A_EMAIL)
    _, document_id = await _dataset_with_document(client, headers, "wd_v1_doc_a")

    upload = await client.post(
        "/v1/document/upload_info",
        headers=headers,
        files={"file": ("ragflow_intro.txt", _TEXT, "text/plain")},
    )
    info = cast("dict[str, Any]", _data(upload))
    assert set(info) == _UPLOAD_INFO_KEYS
    assert info["name"] == "ragflow_intro.txt"
    assert info["extension"] == "txt"
    assert info["mime_type"] == "text/plain"
    assert info["size"] == sys.getsizeof(_TEXT)  # DOC:823 — złoto --26: 1352 dla 1319 B
    assert info["created_by"] == user_id
    assert info["preview_url"] is None
    assert len(str(info["id"])) == ID_LEN

    downloaded = await client.get(f"/v1/document/get/{document_id}", headers=headers)
    assert downloaded.status_code == _OK
    assert downloaded.content == _TEXT
    assert downloaded.headers["content-type"].startswith("text/plain")

    thumbnails = await client.get(
        "/v1/document/thumbnails", headers=headers, params={"doc_ids": document_id}
    )
    assert thumbnails.status_code == _OK
    assert thumbnails.json() == {
        "code": _CODE_SUCCESS,
        "message": "success",
        "data": {document_id: ""},
    }


async def test_foreign_document_change_status_and_run_refused_and_untouched(
    client: httpx.AsyncClient, container: Container
) -> None:
    """B zmienia status i uruchamia parsowanie cudzego dokumentu: odmowa, stan A bez zmian."""
    await _create_user(container, _A_EMAIL)
    await _create_user(container, _B_EMAIL)
    headers_a = await _login(client, _A_EMAIL)
    headers_b = await _login(client, _B_EMAIL)
    dataset_a, document_a = await _dataset_with_document(client, headers_a, "wd_v1_doc_a")
    before = await _document_state(client, headers_a, dataset_a)

    change = await client.post(
        "/v1/document/change_status",
        headers=headers_b,
        json={"doc_ids": [document_a], "status": "1"},
    )
    assert change.status_code == _OK
    assert change.json() == _DENIED

    run = await client.post(
        "/v1/document/run",
        headers=headers_b,
        json={"doc_ids": [document_a], "run": "1", "delete": True},
    )
    assert run.status_code == _OK
    assert run.json() == _DENIED

    assert await _document_state(client, headers_a, dataset_a) == before
    assert before["run"] == "UNSTART"
    assert before["status"] == "1"  # dokument wgrany jest domyślnie włączony


async def test_foreign_document_get_and_thumbnails_refused(
    client: httpx.AsyncClient, container: Container
) -> None:
    """B nie pobiera pliku ani miniatury dokumentu A — odmowa 108 (C0 p. 9)."""
    await _create_user(container, _A_EMAIL)
    await _create_user(container, _B_EMAIL)
    headers_a = await _login(client, _A_EMAIL)
    headers_b = await _login(client, _B_EMAIL)
    _, document_a = await _dataset_with_document(client, headers_a, "wd_v1_doc_a")

    downloaded = await client.get(f"/v1/document/get/{document_a}", headers=headers_b)
    assert downloaded.status_code == _OK
    assert downloaded.json() == _DENIED

    thumbnails = await client.get(
        "/v1/document/thumbnails", headers=headers_b, params={"doc_ids": document_a}
    )
    assert thumbnails.status_code == _OK
    assert thumbnails.json() == _DENIED


async def test_missing_document_is_refused_on_every_document_route(
    client: httpx.AsyncClient, container: Container
) -> None:
    """Nieistniejące id też jest odmową, nie sukcesem (C0 p. 9: nigdy sukces na cudzym zasobie)."""
    await _create_user(container, _A_EMAIL)
    headers = await _login(client, _A_EMAIL)

    change = await client.post(
        "/v1/document/change_status",
        headers=headers,
        json={"doc_ids": [_MISSING_ID], "status": "1"},
    )
    assert change.json() == _DENIED

    run = await client.post(
        "/v1/document/run", headers=headers, json={"doc_ids": [_MISSING_ID], "run": "1"}
    )
    assert run.json() == _DENIED

    downloaded = await client.get(f"/v1/document/get/{_MISSING_ID}", headers=headers)
    assert downloaded.json() == _DENIED

    thumbnails = await client.get(
        "/v1/document/thumbnails", headers=headers, params={"doc_ids": _MISSING_ID}
    )
    assert thumbnails.json() == _DENIED


async def test_document_routes_require_authorization(client: httpx.AsyncClient) -> None:
    """Bez nagłówka ``Authorization`` każda z pięciu tras odpowiada 401 (login_required)."""
    calls: tuple[tuple[str, str, dict[str, Any]], ...] = (
        ("post", "/v1/document/change_status", {"json": {"doc_ids": [_MISSING_ID], "status": "1"}}),
        ("post", "/v1/document/run", {"json": {"doc_ids": [_MISSING_ID], "run": "1"}}),
        ("post", "/v1/document/upload_info", {"files": {"file": ("a.txt", _TEXT, "text/plain")}}),
        ("get", f"/v1/document/get/{_MISSING_ID}", {}),
        ("get", "/v1/document/thumbnails", {"params": {"doc_ids": _MISSING_ID}}),
    )
    for method, path, kwargs in calls:
        response = await getattr(client, method)(path, **kwargs)
        assert response.status_code == _UNAUTHORIZED, path
