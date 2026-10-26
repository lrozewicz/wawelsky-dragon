"""Fixture'y testów RunPod: kontener na świeżej bazie, fałszywe API RunPod, superuser."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.db.uow import transaction
from app.domain.policy import Principal
from tests.fakes.clock import FrozenClock
from tests.fakes.runpod import FakeRunpod
from tests.integration.ingest.conftest import TIME, TIME_MS, migrated_db  # noqa: F401 — fixture


@pytest.fixture
def fake() -> FakeRunpod:
    return FakeRunpod()


@pytest.fixture
async def container(
    migrated_db: Settings,  # noqa: F811
    tmp_path: Path,
    fake: FakeRunpod,
) -> AsyncIterator[Container]:
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    await instance.storage.ensure_layout()
    instance.runpod_http = fake.client()  # type: ignore[attr-defined]
    yield instance
    await instance.aclose()


@pytest.fixture
async def sm(container: Container) -> async_sessionmaker[AsyncSession]:
    assert container.sessionmaker is not None
    return container.sessionmaker


@pytest.fixture
async def admin(container: Container) -> Principal:
    """Superuser z wierszem w ``users`` (FK ``created_by`` instancji i wdrożeń)."""
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, 'admin@example.com', 'admin', :ms, :t, :ms, :t)"
            ),
            {"id": "a" * 32, "ms": TIME_MS, "t": TIME},
        )
    return Principal("a" * 32, "admin@example.com", True, False, "jwt")


@pytest.fixture
def user() -> Principal:
    return Principal("b" * 32, "user@example.com", False, False, "jwt")
