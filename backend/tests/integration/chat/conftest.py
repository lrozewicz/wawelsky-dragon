"""Fixture'y i pomocnicy testów repozytoriów czatu (brief T3, kontrakt C9) i usługi (brief T4).

Wzorzec: tests/integration/retrieval/conftest.py (fixture'y lokalne, pomocnicy
wspólnych pakietów przez import — jak w testach retrievalu).
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.container import Container
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import chat_datasets as chat_datasets_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories import models as models_repo
from app.db.repositories.chats import ChatRow
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from app.domain.chat.events import ChatEvent
from app.llm.openai_gateway import OpenAIGateway
from app.services.chat import ChatStream
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME, TIME_MS, seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import ingest_text


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy: storage w tmp_path, modele fake (wzorzec tests/integration/retrieval)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


async def seed_user(sm: async_sessionmaker[AsyncSession]) -> str:
    """Wstawia users; zwraca id (e-mail `{id}@example.com`) (brief T3)."""
    user_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :email, 'seed', :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": user_id,
                "email": f"{user_id}@example.com",
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
    return user_id


async def seed_chat(  # noqa: PLR0913 — kształt sygnatury z briefu T3
    sm: async_sessionmaker[AsyncSession],
    tenant_id: str,
    dataset_ids: Sequence[str],
    *,
    prompt_config: dict | None = None,
    llm_id: str = "fake-chat",
    similarity_threshold: float = 0.0,
    vector_similarity_weight: float = 0.3,
    top_n: int = 6,
    meta_data_filter: dict | None = None,
) -> ChatRow:
    """Wstawia chats + chat_datasets (brief T3); zwraca chats.get."""
    chat_id = uuid.uuid4().hex
    row = ChatRow(
        id=chat_id,
        tenant_id=tenant_id,
        created_by=tenant_id,
        name=f"Czat testowy {chat_id[:8]}",  # UNIQUE (tenant_id, name)
        language="Polish",
        llm_id=llm_id,
        llm_setting={"temperature": 0.1, "max_tokens": 512},
        prompt_config=prompt_config if prompt_config is not None else {},
        similarity_threshold=similarity_threshold,
        vector_similarity_weight=vector_similarity_weight,
        top_n=top_n,
        top_k=1024,
        rerank_candidates_count=64,
        rerank_id="",
        meta_data_filter=meta_data_filter,
        status="1",
    )
    async with transaction(sm) as session:
        await chats_repo.insert(session, row, now_ms=TIME_MS)
        await chat_datasets_repo.insert_many(session, chat_id, dataset_ids)
        return await chats_repo.get(session, chat_id)


async def register_think_model(sm: async_sessionmaker[AsyncSession]) -> None:
    """Rejestruje model fake-chat-think (typ chat, K10 §4) — testy myślenia (brief T5)."""
    async with transaction(sm) as session:
        await models_repo.insert(
            session,
            id="t" * 32,
            name="fake-chat-think",
            model_type="chat",
            is_default=False,
            now_ms=TIME_MS,
        )


async def register_strict_model(sm: async_sessionmaker[AsyncSession]) -> None:
    """Rejestruje model fake-chat-strict (typ chat, K10 poprawka 2026-10-04) — czat T5."""
    async with transaction(sm) as session:
        await models_repo.insert(
            session,
            id="r" * 32,
            name="fake-chat-strict",
            model_type="chat",
            is_default=False,
            now_ms=TIME_MS,
        )


def use_scenario(container: Container, scenario: str) -> None:
    """Podmienia container.llm na bramkę z nagłówkiem X-Fake-Scenario (K10 §4).

    Nagłówek tylko dla /chat/completions — embeddingi bez scenariusza. Podmiana
    następuje przed pierwszym wywołaniem LLM, więc stara bramka ma pustą pulę
    klientów; nową zamyka fixture ``container`` przez ``aclose()``.
    """

    async def hook(request: httpx2.Request) -> None:
        if request.url.path.endswith("/chat/completions"):
            request.headers["X-Fake-Scenario"] = scenario

    container.llm = OpenAIGateway(
        container.settings,
        sessionmaker=container.sessionmaker,
        clock=container.clock,
        event_hooks={"request": [hook]},
    )


async def collect(stream: ChatStream) -> list[ChatEvent]:
    """Konsumuje strumień zdarzeń czatu do listy."""
    return [event async for event in stream.events]


async def chat_with_doc(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    text: str,
    *,
    prompt_config: dict[str, Any] | None = None,
    owner: str | None = None,
) -> tuple[ChatRow, DatasetRow, str]:
    """Dataset (seed_dataset), ingestia tekstu, czat z tym datasetem.

    Zwraca (czat, dataset, id dokumentu).

    Czat w trybie termowym (similarity_threshold=0.0, vector_similarity_weight=0.0);
    pytanie w teście ma zawierać słowa dokumentu. ``owner`` — tenant czatu (domyślnie
    właściciel datasetu); używane w testach uprawnień (R0 p. 2).
    """
    dataset = await seed_dataset(sm)
    doc_id = await ingest_text(container, dataset, "wawel.txt", text)
    chat = await seed_chat(
        sm,
        owner or dataset.tenant_id,
        [dataset.id],
        prompt_config=prompt_config,
        similarity_threshold=0.0,
        vector_similarity_weight=0.0,
    )
    return chat, dataset, doc_id
