"""Fixture'y kontraktowych testów hub-compat user-api (brief T5a, kontrakt C9).

`fresh_db`/`migrated_db`/`auth_settings`/`sm` dziedziczymy z `tests/contract/conftest.py`
(conftest katalogu nadrzędnego — bez re-eksportu). Wzorce: `tests/integration/api/conftest.py`
(start kontenera, ASGITransport), `tests/integration/chat/conftest.py`
(seed_user/seed_chat na `chats_repo.insert`).
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import chats as chats_repo
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from app.main import create_app
from tests.integration.ingest.conftest import TIME, TIME_MS
from tests.integration.ingest.pipeline_helpers import make_container

# Sekret testowy powierzchni hub-compat (K7 §1.7); nigdy nie jest prawdziwym sekretem.
SVC_SECRET = "test-secret"  # noqa: S105

SeedChat = Callable[[str | None], Awaitable[str]]


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Sekrety testowe + storage w tmp_path + sekret SVC (kontrakt C9)."""
    return auth_settings.model_copy(
        update={
            "storage_root": str(tmp_path),
            "hub_compat_api_secret": SecretStr(SVC_SECRET),
        }
    )


@pytest.fixture
async def container(settings: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy na tej samej bazie co aplikacja; start ręczny (C9)."""
    instance = await make_container(settings, tmp_path)
    yield instance
    await instance.aclose()


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    """Aplikacja na tym samym `settings` i kontenerze co test (kontrakt C9)."""
    return create_app(settings, container)


@pytest.fixture
async def svc(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient z nagłówkiem `X-API-Secret` (ASGI, bez sieci)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Secret": SVC_SECRET}
    ) as client:
        yield client


@pytest.fixture
async def anon(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient **bez** nagłówka `X-API-Secret` (testy 401, AG-31)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture(params=["", "/user-api"])
def prefix(request: pytest.FixtureRequest) -> str:
    """Prefiks montażu user-api: `""` i `"/user-api"` (K7 §1.8, AG-29)."""
    return str(request.param)


async def seed_user(sm: async_sessionmaker[AsyncSession]) -> str:
    """Wstawia użytkownika; zwraca id (e-mail `{id}@example.com`) — wzorzec chat/conftest."""
    user_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :email, 'seed', :time_ms, :time, :time_ms, :time)"
            ),
            {"id": user_id, "email": f"{user_id}@example.com", "time_ms": TIME_MS, "time": TIME},
        )
    return user_id


@pytest.fixture
def seed_chat(sm: async_sessionmaker[AsyncSession]) -> SeedChat:
    """Helper: czat testowy dla właściciela; bez `owner_id` zakłada też użytkownika.

    Zwraca id czatu (= `dialog_id` tras `/api/access`); wiersz w `chats` jest potrzebny
    jako cel FK `assistant_access.chat_id` (kontrakt C9).
    """

    async def _seed(owner_id: str | None = None) -> str:
        tenant_id = owner_id or await seed_user(sm)
        chat_id = uuid.uuid4().hex
        row = ChatRow(
            id=chat_id,
            tenant_id=tenant_id,
            created_by=tenant_id,
            name=f"Czat hub-compat {chat_id[:8]}",  # UNIQUE (tenant_id, name)
            language="Polish",
            llm_id="fake-chat",
            llm_setting={"temperature": 0.1, "max_tokens": 512},
            prompt_config={},
            similarity_threshold=0.0,
            vector_similarity_weight=0.3,
            top_n=6,
            top_k=1024,
            rerank_candidates_count=64,
            rerank_id="",
            meta_data_filter=None,
            status="1",
        )
        async with transaction(sm) as session:
            await chats_repo.insert(session, row, now_ms=TIME_MS)
        return chat_id

    return _seed
