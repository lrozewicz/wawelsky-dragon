"""Testy repozytoriów llm_cache i embedding_cache na MariaDB (brief T4, kontrakt C9)."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import embedding_cache, llm_cache
from app.db.uow import transaction
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

NOW = FrozenClock().now_ms()
KEY = "k" * 64
EKEY = "e" * 64


@pytest.fixture
async def db(fresh_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Zmigrowana świeża baza; fabryka sesji, engine zamknięty po teście."""
    await asyncio.to_thread(command.upgrade, alembic_cfg(fresh_db), "head")
    engine = make_engine(fresh_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def test_llm_cache_roundtrip(db: async_sessionmaker[AsyncSession]) -> None:
    async with transaction(db) as session:
        await llm_cache.put(
            session,
            key_hash=KEY,
            model="fake-chat",
            response="Witaj",
            tokens_in=3,
            tokens_out=2,
            expires_at=NOW + 1000,
            now_ms=NOW,
        )
    async with db() as session:
        assert await llm_cache.get(session, KEY, NOW) == ("Witaj", 3, 2)


async def test_llm_cache_expired(db: async_sessionmaker[AsyncSession]) -> None:
    """expires_at > now_ms — granica włącznie: expires_at == now → chybienie."""
    async with transaction(db) as session:
        await llm_cache.put(
            session,
            key_hash=KEY,
            model="fake-chat",
            response="Witaj",
            tokens_in=3,
            tokens_out=2,
            expires_at=NOW + 1000,
            now_ms=NOW,
        )
    async with db() as session:
        assert await llm_cache.get(session, KEY, NOW + 1000) is None


async def test_llm_cache_put_overwrites(db: async_sessionmaker[AsyncSession]) -> None:
    """Drugi put tym samym kluczem nadpisuje wiersz (ON DUPLICATE KEY UPDATE)."""
    for response, tin, tout, ttl in (("pierwszy", 1, 1, 1000), ("drugi", 5, 6, 2000)):
        async with transaction(db) as session:
            await llm_cache.put(
                session,
                key_hash=KEY,
                model="fake-chat",
                response=response,
                tokens_in=tin,
                tokens_out=tout,
                expires_at=NOW + ttl,
                now_ms=NOW,
            )
    async with db() as session:
        assert await llm_cache.get(session, KEY, NOW) == ("drugi", 5, 6)


async def test_embedding_cache_roundtrip(db: async_sessionmaker[AsyncSession]) -> None:
    async with transaction(db) as session:
        await embedding_cache.put(
            session,
            key_hash=EKEY,
            model="fake-embed",
            dim=3,
            vector=b"\x00" * 12,
            expires_at=NOW + 1,
        )
    async with db() as session:
        assert await embedding_cache.get(session, EKEY, NOW) == b"\x00" * 12
        assert await embedding_cache.get(session, EKEY, NOW + 1) is None


async def test_embedding_cache_put_overwrites(db: async_sessionmaker[AsyncSession]) -> None:
    for blob in (b"\x00" * 12, b"\x01" * 12):
        async with transaction(db) as session:
            await embedding_cache.put(
                session,
                key_hash=EKEY,
                model="fake-embed",
                dim=3,
                vector=blob,
                expires_at=NOW + 1,
            )
    async with db() as session:
        assert await embedding_cache.get(session, EKEY, NOW) == b"\x01" * 12
