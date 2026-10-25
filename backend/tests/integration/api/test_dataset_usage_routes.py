"""Testy HTTP trasy użycia datasetu (K20 §4, zadanie V12-1/T3).

Zakres: własne czaty i wyszukiwarki widoczne z nazwami (kształt ``data`` dosłownie z K20 §4),
cudze zasoby wyłącznie jako ``hidden_*`` (bez nazw i id), superuser widzi wszystkie wiązania,
członek zespołu 403 ``forbidden``, obcy i nieistniejący dataset 404 ``not_found``, ucięcie
listy > 50 z ``truncated=true`` (bez wliczania do ``hidden_*``), sortowanie po ``name``
potem ``id``, baza bez powiązań oraz bez zmiany stanu (trasa tylko do odczytu, Q52).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME_MS, seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

_HTTP_OK = 200
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_USAGE_LIMIT = 50  # K20 §4

_TIME_DATE = datetime.fromtimestamp(TIME_MS / 1000, tz=UTC).replace(tzinfo=None)


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener ze magazynem w tmp_path i modelami fake-llm (wzorzec tests/integration/api)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _sm(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera (istnieje po ``start()``)."""
    sessionmaker = cast("async_sessionmaker[AsyncSession] | None", container.sessionmaker)
    assert sessionmaker is not None, "container nie wystartował"
    return sessionmaker


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na żywym kontenerze z nadpisanym aktorem (wzorzec test_kb_export_routes)."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (bez nagłówka Authorization)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _usage(container: Container, principal: Principal, dataset_id: str) -> tuple[int, dict]:
    """Wywołuje ``GET /datasets/{id}/usage`` i zwraca (status, treść JSON)."""
    async with _client(_app(container, principal)) as client:
        response = await client.get(f"/api/wd/v1/datasets/{dataset_id}/usage")
    return response.status_code, response.json()


async def _seed_chat_binding(
    sm: async_sessionmaker[AsyncSession], tenant_id: str, dataset_id: str, name: str
) -> str:
    """Czat ``tenant_id`` o danej nazwie z wiązaniem do datasetu; zwraca id czatu."""
    chat_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO chats (id, tenant_id, created_by, name, llm_id, prompt_config,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, :name, '', '{}', :t, :d, :t, :d)"
            ),
            {
                "id": chat_id,
                "tenant": tenant_id,
                "name": name,
                "t": TIME_MS,
                "d": _TIME_DATE,
            },
        )
        await session.execute(
            text("INSERT INTO chat_datasets (chat_id, dataset_id, ordinal) VALUES (:c, :ds, 0)"),
            {"c": chat_id, "ds": dataset_id},
        )
    return chat_id


async def _seed_search_binding(
    sm: async_sessionmaker[AsyncSession], tenant_id: str, dataset_id: str, name: str
) -> str:
    """Wyszukiwarka ``tenant_id`` o danej nazwie z wiązaniem do datasetu; zwraca id."""
    search_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO searches (id, tenant_id, created_by, name, search_config, status,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, :name, '{}', '1', :t, :d, :t, :d)"
            ),
            {
                "id": search_id,
                "tenant": tenant_id,
                "name": name,
                "t": TIME_MS,
                "d": _TIME_DATE,
            },
        )
        await session.execute(
            text(
                "INSERT INTO search_datasets (search_id, dataset_id, ordinal) VALUES (:s, :ds, 0)"
            ),
            {"s": search_id, "ds": dataset_id},
        )
    return search_id


async def _set_permission(
    sm: async_sessionmaker[AsyncSession], dataset_id: str, permission: str
) -> None:
    """Ustawia ``datasets.permission`` (``team`` → członek zespołu ma READ)."""
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET permission = :p WHERE id = :id"),
            {"p": permission, "id": dataset_id},
        )


async def _binding_counts(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> tuple[int, int]:
    """Liczba wiązań datasetu w ``chat_datasets`` i ``search_datasets`` (dowód braku zmian)."""
    async with transaction(sm) as session:
        chats = (
            await session.execute(
                text("SELECT COUNT(*) FROM chat_datasets WHERE dataset_id = :ds"),
                {"ds": dataset_id},
            )
        ).scalar_one()
        searches = (
            await session.execute(
                text("SELECT COUNT(*) FROM search_datasets WHERE dataset_id = :ds"),
                {"ds": dataset_id},
            )
        ).scalar_one()
    return int(chats), int(searches)


# --- kształt odpowiedzi i widoczność -------------------------------------------------------------


async def test_owner_sees_own_chats_and_searches_with_names(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Właściciel: 200 i kształt ``data`` dosłownie z K20 §4, posortowany po name."""
    dataset: DatasetRow = await seed_dataset(sm)
    chat_first = await _seed_chat_binding(sm, dataset.tenant_id, dataset.id, "Czat GUS")
    chat_second = await _seed_chat_binding(sm, dataset.tenant_id, dataset.id, "Czat ALK")
    search_id = await _seed_search_binding(sm, dataset.tenant_id, dataset.id, "Wyszukiwarka")
    principal = principal_for(dataset.tenant_id)

    status, body = await _usage(container, principal, dataset.id)

    assert status == _HTTP_OK, body
    assert set(body) == {"data"}, body
    data = body["data"]
    assert set(data) == {"chats", "searches", "hidden_chats", "hidden_searches", "truncated"}
    assert data["chats"] == [
        {"id": chat_second, "name": "Czat ALK"},
        {"id": chat_first, "name": "Czat GUS"},
    ]
    assert data["searches"] == [{"id": search_id, "name": "Wyszukiwarka"}]
    assert data["hidden_chats"] == 0
    assert data["hidden_searches"] == 0
    assert data["truncated"] is False


async def test_foreign_bindings_stay_hidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudze czaty i wyszukiwarki: tylko ``hidden_*`` — bez nazw i id (test izolacji)."""
    dataset: DatasetRow = await seed_dataset(sm)
    other_a = await seed_user(sm)
    other_b = await seed_user(sm)
    foreign_chat_a = await _seed_chat_binding(sm, other_a, dataset.id, "Czat obcy A")
    foreign_chat_b = await _seed_chat_binding(sm, other_b, dataset.id, "Czat obcy B")
    foreign_search = await _seed_search_binding(sm, other_a, dataset.id, "Wyszukiwarka obca")
    principal = principal_for(dataset.tenant_id)

    status, body = await _usage(container, principal, dataset.id)

    assert status == _HTTP_OK, body
    data = body["data"]
    assert data["chats"] == []
    assert data["searches"] == []
    assert data["hidden_chats"] == len((foreign_chat_a, foreign_chat_b))
    assert data["hidden_searches"] == 1
    assert data["truncated"] is False
    # Nazwy i id cudzych zasobów nigdzie nie wyciekają.
    leaked = json.dumps(body, ensure_ascii=False)
    for secret in (foreign_chat_a, foreign_chat_b, foreign_search, "obcy", "obca"):
        assert secret not in leaked, leaked


async def test_superuser_sees_all_bindings(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Superuser widzi wszystkie wiązania z nazwami; ``hidden_*`` = 0."""
    dataset: DatasetRow = await seed_dataset(sm)
    other = await seed_user(sm)
    own_chat = await _seed_chat_binding(sm, dataset.tenant_id, dataset.id, "Czat własny")
    foreign_chat = await _seed_chat_binding(sm, other, dataset.id, "Czat obcy")
    foreign_search = await _seed_search_binding(sm, other, dataset.id, "Wyszukiwarka obca")

    status, body = await _usage(
        container, principal_for(uuid.uuid4().hex, superuser=True), dataset.id
    )

    assert status == _HTTP_OK, body
    data = body["data"]
    assert data["chats"] == [
        {"id": foreign_chat, "name": "Czat obcy"},
        {"id": own_chat, "name": "Czat własny"},
    ]
    assert data["searches"] == [{"id": foreign_search, "name": "Wyszukiwarka obca"}]
    assert data["hidden_chats"] == 0
    assert data["hidden_searches"] == 0
    assert data["truncated"] is False


# --- uprawnienia ---------------------------------------------------------------------------------


async def test_team_member_is_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Członek zespołu (``permission=team``, READ tak) nie sprawdza użycia: 403 ``forbidden``."""
    dataset: DatasetRow = await seed_dataset(sm)
    await _set_permission(sm, dataset.id, "team")
    member = await seed_user(sm)

    status, body = await _usage(container, principal_for(member), dataset.id)

    assert status == _HTTP_FORBIDDEN, body
    assert body["error"]["code"] == "forbidden"


async def test_stranger_gets_not_found(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Obcy bez dostępu do odczytu (dataset ``permission=me``): 404 ``not_found``."""
    dataset: DatasetRow = await seed_dataset(sm)
    stranger = await seed_user(sm)

    status, body = await _usage(container, principal_for(stranger), dataset.id)

    assert status == _HTTP_NOT_FOUND, body
    assert body["error"]["code"] == "not_found"


async def test_missing_dataset_gets_not_found(container: Container) -> None:
    """Nieistniejący dataset: 404 ``not_found``."""
    status, body = await _usage(container, principal_for(uuid.uuid4().hex), uuid.uuid4().hex)
    assert status == _HTTP_NOT_FOUND, body
    assert body["error"]["code"] == "not_found"


# --- limit i sortowanie --------------------------------------------------------------------------


async def test_more_than_fifty_is_truncated(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """> 50 czatów: lista ucięta do 50, ``truncated=true``, licznik hidden nie rośnie."""
    dataset: DatasetRow = await seed_dataset(sm)
    for ordinal in range(_USAGE_LIMIT + 2):
        await _seed_chat_binding(sm, dataset.tenant_id, dataset.id, f"Czat {ordinal:03d}")
    await _seed_search_binding(sm, dataset.tenant_id, dataset.id, "Wyszukiwarka")

    status, body = await _usage(container, principal_for(dataset.tenant_id), dataset.id)

    assert status == _HTTP_OK, body
    data = body["data"]
    assert len(data["chats"]) == _USAGE_LIMIT
    assert data["chats"][0]["name"] == "Czat 000"
    assert data["searches"] != []
    assert data["hidden_chats"] == 0
    assert data["hidden_searches"] == 0
    assert data["truncated"] is True


async def test_exactly_fifty_is_not_truncated(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dokładnie 50 wiązań: cała lista, ``truncated=false`` (K20 §4: ucięcie dopiero > 50)."""
    dataset: DatasetRow = await seed_dataset(sm)
    for ordinal in range(_USAGE_LIMIT):
        await _seed_chat_binding(sm, dataset.tenant_id, dataset.id, f"Czat {ordinal:03d}")

    status, body = await _usage(container, principal_for(dataset.tenant_id), dataset.id)

    assert status == _HTTP_OK, body
    data = body["data"]
    assert len(data["chats"]) == _USAGE_LIMIT
    assert data["chats"][-1]["name"] == "Czat 049"
    assert data["hidden_chats"] == 0
    assert data["truncated"] is False


async def test_more_than_fifty_searches_is_truncated(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """> 50 wyszukiwarek: lista ucięta do 50, ``truncated=true`` (K20 §4 — obie listy)."""
    dataset: DatasetRow = await seed_dataset(sm)
    for ordinal in range(_USAGE_LIMIT + 1):
        await _seed_search_binding(sm, dataset.tenant_id, dataset.id, f"Wyszukiwarka {ordinal:03d}")

    status, body = await _usage(container, principal_for(dataset.tenant_id), dataset.id)

    assert status == _HTTP_OK, body
    data = body["data"]
    assert len(data["searches"]) == _USAGE_LIMIT
    assert data["searches"][0]["name"] == "Wyszukiwarka 000"
    assert data["chats"] == []
    assert data["hidden_searches"] == 0
    assert data["truncated"] is True


async def test_exactly_fifty_searches_is_not_truncated(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dokładnie 50 wyszukiwarek: cała lista, ``truncated=false`` (K20 §4: ucięcie > 50)."""
    dataset: DatasetRow = await seed_dataset(sm)
    for ordinal in range(_USAGE_LIMIT):
        await _seed_search_binding(sm, dataset.tenant_id, dataset.id, f"Wyszukiwarka {ordinal:03d}")

    status, body = await _usage(container, principal_for(dataset.tenant_id), dataset.id)

    assert status == _HTTP_OK, body
    data = body["data"]
    assert len(data["searches"]) == _USAGE_LIMIT
    assert data["searches"][-1]["name"] == "Wyszukiwarka 049"
    assert data["hidden_searches"] == 0
    assert data["truncated"] is False


async def test_sorted_by_name_then_id(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Sortowanie po ``name``, a przy tej samej nazwie po ``id`` (superuser, dwaj właściciele)."""
    dataset: DatasetRow = await seed_dataset(sm)
    other = await seed_user(sm)
    first = await _seed_chat_binding(sm, other, dataset.id, "Wspólna nazwa")
    second = await _seed_chat_binding(sm, dataset.tenant_id, dataset.id, "Wspólna nazwa")
    await _seed_chat_binding(sm, dataset.tenant_id, dataset.id, "Alfa")
    search_a = await _seed_search_binding(sm, other, dataset.id, "Wspólna wyszukiwarka")
    search_b = await _seed_search_binding(sm, dataset.tenant_id, dataset.id, "Wspólna wyszukiwarka")

    status, body = await _usage(
        container, principal_for(uuid.uuid4().hex, superuser=True), dataset.id
    )

    assert status == _HTTP_OK, body
    data = body["data"]
    assert [item["name"] for item in data["chats"]] == ["Alfa", "Wspólna nazwa", "Wspólna nazwa"]
    same_name_ids = [item["id"] for item in data["chats"][1:]]
    assert same_name_ids == sorted([first, second])
    same_search_ids = [item["id"] for item in data["searches"]]
    assert same_search_ids == sorted([search_a, search_b])


# --- stany brzegowe i brak zmiany stanu ----------------------------------------------------------


async def test_dataset_without_bindings_returns_empty(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Baza bez powiązań: puste listy, ``hidden_*`` = 0, ``truncated=false``."""
    dataset: DatasetRow = await seed_dataset(sm)

    status, body = await _usage(container, principal_for(dataset.tenant_id), dataset.id)

    assert status == _HTTP_OK, body
    assert body["data"] == {
        "chats": [],
        "searches": [],
        "hidden_chats": 0,
        "hidden_searches": 0,
        "truncated": False,
    }


async def test_route_does_not_change_state(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Trasa tylko do odczytu (Q52): po wywołaniu wiązania nadal są."""
    dataset: DatasetRow = await seed_dataset(sm)
    await _seed_chat_binding(sm, dataset.tenant_id, dataset.id, "Czat")
    await _seed_search_binding(sm, dataset.tenant_id, dataset.id, "Wyszukiwarka")

    status, _body = await _usage(container, principal_for(dataset.tenant_id), dataset.id)

    assert status == _HTTP_OK
    assert await _binding_counts(sm, dataset.id) == (1, 1)
