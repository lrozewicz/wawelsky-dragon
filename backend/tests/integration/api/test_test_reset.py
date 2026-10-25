"""Testy integracyjne POST /api/wd/v1/test/reset (K9 §5 p. 1, §3, §4)."""

import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy import table as sql_table
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import RateLimited
from app.db.repositories import documents as documents_repo
from app.db.repositories import provider_instances as provider_instances_repo
from app.db.repositories.maintenance import list_tables, wipe_all
from app.db.uow import transaction
from app.integrations.sharepoint import auth as sharepoint_auth
from app.integrations.sharepoint.auth import TokenProvider
from app.main import create_app
from app.services.auth_ratelimit import LoginGuard
from app.storage.keys import document_key
from tests.fakes.clock import FrozenClock
from tests.integration.chat.conftest import seed_chat, seed_user
from tests.integration.ingest.conftest import TIME, TIME_MS, make_document_row, seed_dataset

pytestmark = pytest.mark.db

_OK = 200
_HEX32 = re.compile(r"[0-9a-f]{32}")

_RESET = "/api/wd/v1/test/reset"
EMAIL = "admin@wd.test"
PASSWORD = "wd-test-admin-1"  # noqa: S105 — stała testowa z K9 §2, nie sekret
OVERRIDE_PASSWORD = "pw-12345678"  # noqa: S105 — celowa atrapa hasła w teście
GRAPH_SECRET = "graph-reset-secret"  # noqa: S105 — sekret wyłącznie testowy

# Tabele czyszczone przez seed scenariusza — muszą być puste po resecie (K9 §5 p. 1).
_SEEDED_TABLES = ("datasets", "documents", "chats", "chat_datasets")
# Stan po resecie: admin, jego klucz i 6 modeli (K9 §3, poprawka 2026-10-04).
_RESET_COUNTS = {"users": 1, "api_keys": 1, "models": 6}

# Modele zasiewane resetem — K9 §3 p. 4, posortowane po nazwie (ORDER BY name).
_EXPECTED_MODELS = [
    ("fake-chat", "chat", True, None),
    ("fake-chat-strict", "chat", False, None),
    ("fake-chat-think", "chat", False, None),
    ("fake-embed-1024", "embedding", True, 1024),
    ("fake-rerank", "rerank", True, None),
    ("fake-vision", "image2text", True, None),
]


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Sekrety testowe, storage w tmp_path, pusty admin → domyślne z K9 §2."""
    return auth_settings.model_copy(
        update={
            "storage_root": str(tmp_path),
            "env": "test",
            "admin_email": "",
            "admin_password": SecretStr(""),
        }
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    return Container(settings)


@pytest.fixture
def client(settings: Settings, container: Container) -> Iterator[TestClient]:
    """Aplikacja ze startem lifespan (kontener: engine, usługi); aclose w zamknięciu."""
    with TestClient(create_app(settings, container)) as test_client:
        yield test_client


async def _counts(sm: async_sessionmaker[AsyncSession], tables: Sequence[str]) -> dict[str, int]:
    """Liczność wierszy podanych tabel (nazwy z information_schema albo stałe w teście)."""
    async with transaction(sm) as session:
        return {
            t: cast(
                int,
                (
                    await session.execute(select(func.count()).select_from(sql_table(t)))
                ).scalar_one(),
            )
            for t in tables
        }


async def _table_names(sm: async_sessionmaker[AsyncSession]) -> list[str]:
    """Wszystkie tabele schematu poza alembic_version (to samo źródło co wipe_all)."""
    async with transaction(sm) as session:
        return await list_tables(session)


async def _models(sm: async_sessionmaker[AsyncSession]) -> list[tuple[str, str, bool, int | None]]:
    """Wiersze models: (name, model_type, is_default, dimension), po nazwie."""
    async with transaction(sm) as session:
        rows = (
            await session.execute(
                text("SELECT name, model_type, is_default, dimension FROM models ORDER BY name")
            )
        ).all()
    return [(str(r[0]), str(r[1]), bool(r[2]), cast("int | None", r[3])) for r in rows]


async def _seed_api_key(sm: async_sessionmaker[AsyncSession], user_id: str) -> None:
    """Surowy wiersz api_keys (kolumny NOT NULL; reszta NULL) — wzór: repozytorium api_keys."""
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO api_keys (id, user_id, token_hash, token_enc, prefix, name,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (:id, :user_id, :token_hash, :token_enc, :prefix, NULL,"
                " :now_ms, :date, :now_ms, :date)"
            ),
            {
                "id": "k" * 32,
                "user_id": user_id,
                "token_hash": "h" * 64,
                "token_enc": b"enc",
                "prefix": "ragflow-" + "p" * 8,
                "now_ms": TIME_MS,
                "date": TIME,
            },
        )


async def test_wipe_all_direct(sm: async_sessionmaker[AsyncSession]) -> None:
    """Repozytorium bezpośrednio: wipe_all czyści tabele i zwraca listę bez alembic_version."""
    await seed_user(sm)
    async with transaction(sm) as session:
        tables = await wipe_all(session)
    assert tables
    assert "alembic_version" not in tables
    assert await _counts(sm, ("users",)) == {"users": 0}


async def test_reset_wipes_seeded_state(
    client: TestClient,
    container: Container,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Reset po zasianiu danych: tabele puste poza adminem/kluczem/modelami, storage czysty."""
    assert client.post(_RESET).status_code == _OK
    # Zasiew: dodatkowy użytkownik, dataset, dokument, czat, klucz API, plik w storage.
    user_id = await seed_user(sm)
    dataset = await seed_dataset(sm)
    row = make_document_row(dataset)
    async with transaction(sm) as session:
        await documents_repo.insert(session, row)
    await seed_chat(sm, dataset.tenant_id, [dataset.id])
    await _seed_api_key(sm, user_id)
    # document_key przyjmuje suffix bez kropki → files/{ds}/{doc}/original.txt
    key = document_key(dataset.id, row.id, "txt")
    await container.storage.put(key, b"x")

    response = client.post(_RESET)
    assert response.status_code == _OK
    assert await _counts(sm, _SEEDED_TABLES) == dict.fromkeys(_SEEDED_TABLES, 0)
    assert await _counts(sm, tuple(_RESET_COUNTS)) == _RESET_COUNTS
    assert await _models(sm) == _EXPECTED_MODELS
    assert await container.storage.exists(key) is False


async def test_reset_wipes_provider_instances(
    client: TestClient,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Reset czyści `provider_instances` (K13 §1, §5) — także gdy instancję wstawiono ręcznie."""
    assert client.post(_RESET).status_code == _OK
    async with transaction(sm) as session:
        await provider_instances_repo.insert(
            session,
            id="i" * 32,
            provider="litellm",
            name="Produkcja",
            base_url="http://llm.local/v1",
            api_key_enc=None,
            created_by=None,
            now_ms=TIME_MS,
        )
    assert await _counts(sm, ("provider_instances",)) == {"provider_instances": 1}
    assert client.post(_RESET).status_code == _OK
    assert await _counts(sm, ("provider_instances",)) == {"provider_instances": 0}


def test_reset_response_and_login(client: TestClient) -> None:
    """Kształt odpowiedzi K9 §4 + login admina i /users/me z kluczem z resetu."""
    body = client.post(_RESET).json()
    data = cast(dict[str, object], body["data"])
    assert set(data) == {"admin_email", "admin_user_id", "api_key", "models"}
    models = cast(dict[str, str], data["models"])
    assert models == {
        "chat": "fake-chat",
        "embedding": "fake-embed-1024",
        "rerank": "fake-rerank",
        "image2text": "fake-vision",
    }
    assert data["admin_email"] == EMAIL
    assert _HEX32.fullmatch(cast(str, data["admin_user_id"])) is not None
    assert cast(str, data["api_key"]).startswith("ragflow-")

    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.json()["code"] == 0
    me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {data['api_key']}"})
    assert me.json()["code"] == 0
    assert me.json()["data"]["email"] == EMAIL


async def test_reset_idempotent(client: TestClient, sm: async_sessionmaker[AsyncSession]) -> None:
    """Dwa resety z rzędu → te same liczności wszystkich tabel i te same modele (K9 §5 p. 1)."""
    client.post(_RESET)
    tables = tuple(await _table_names(sm))
    first = await _counts(sm, tables)
    first_models = await _models(sm)
    client.post(_RESET)
    assert await _counts(sm, tables) == first
    assert await _models(sm) == first_models


async def test_reset_clears_login_guard(
    client: TestClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Reset czyści tabelę `login_attempts` (K9 §3 p. 3): po resecie hit nie rzuca, licznik 0.

    Guard na `sm` (ten sam schemat co kontener, ale pętla zdarzeń testu — kontener na
    TestClient ma własny portal/loop), przez co `hit` nie przekracza pętli.
    """
    guard = LoginGuard("10/min", FrozenClock(), sm)
    for _ in range(10):
        await guard.hit("10.0.0.1", "a@x.pl")
    with pytest.raises(RateLimited):
        await guard.hit("10.0.0.1", "a@x.pl")
    assert client.post(_RESET).status_code == _OK
    async with transaction(sm) as session:
        result = await session.execute(text("SELECT COUNT(*) FROM login_attempts"))
    assert int(result.scalar_one()) == 0
    await guard.hit("10.0.0.1", "a@x.pl")  # limiter wyczyszczony — nie rzuca


async def test_reset_clears_graph_token_cache(client: TestClient) -> None:
    """Reset czyści modułowy cache tokenów Graph (kontrakt C3 WP E4-H2)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "tok-reset", "expires_in": 3599})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = TokenProvider(http, tenant_id="T1", client_id="C1", client_secret=GRAPH_SECRET)
        assert await provider.get_token() == "tok-reset"
    assert sharepoint_auth._token_cache != {}

    assert client.post(_RESET).status_code == _OK
    assert sharepoint_auth._token_cache == {}


def test_reset_body_overrides_admin(client: TestClient) -> None:
    """Niepuste admin_email/admin_password z ciała wygrywają z domyślnymi; junk ignorowany."""
    body = client.post(
        _RESET,
        json={"admin_email": "x@wd.test", "admin_password": OVERRIDE_PASSWORD, "junk": 1},
    ).json()
    data = cast(dict[str, object], body["data"])
    assert data["admin_email"] == "x@wd.test"
    login = client.post(
        "/api/v1/auth/login", json={"email": "x@wd.test", "password": OVERRIDE_PASSWORD}
    )
    assert login.json()["code"] == 0
