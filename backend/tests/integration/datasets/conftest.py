"""Fixture'y i pomocniki testów datasetów (brief T1a; wzór: tests/integration/ingest)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import models as models_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.domain.policy.principal import Principal
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg

TIME_MS = 1790157600000  # stały zegar testów (FrozenClock)


def date_ms(ms: int) -> datetime:
    """Naivna datetime z milisekund (wartość kolumny DATETIME(3) w SQL testowych)."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).replace(tzinfo=None)


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
    """Kontener na zmigrowanej bazie, storage w tmp_path; po teście aclose (brief T1a)."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    yield instance
    await instance.aclose()


async def seed_user(
    sm: async_sessionmaker[AsyncSession],
    *,
    nickname: str = "Alice",
    is_superuser: bool = False,
) -> tuple[str, str]:
    """Wstawia użytkownika przez users_repo.insert; zwraca (user_id, email)."""
    user_id = uuid.uuid4().hex
    email = f"{user_id[:12]}@example.com"
    async with transaction(sm) as session:
        await users_repo.insert(
            session,
            user_id=user_id,
            email=email,
            nickname=nickname,
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=is_superuser,
            is_service=False,
            now_ms=TIME_MS,
        )
    return user_id, email


def principal(user_id: str, email: str) -> Principal:
    """Principal zwykłego użytkownika (jwt) do wywołań usługi (brief T1a)."""
    return Principal(
        user_id=user_id,
        email=email,
        is_superuser=False,
        is_service=False,
        auth_kind="jwt",
    )


async def seed_model(
    sm: async_sessionmaker[AsyncSession],
    name: str,
    model_type: str,
    *,
    dimension: int | None = None,
    is_default: bool = True,
) -> str:
    """Wstawia model przez models_repo.insert (+dimension); zwraca id (brief T1a)."""
    model_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await models_repo.insert(
            session,
            id=model_id,
            name=name,
            model_type=model_type,
            is_default=is_default,
            now_ms=TIME_MS,
        )
        if dimension is not None:
            await models_repo.set_dimension_if_null(session, model_id, dimension, TIME_MS)
    return model_id


async def seed_default_models(sm: async_sessionmaker[AsyncSession]) -> None:
    """Modele z briefu T1a: fake-embed-1024 (embedding, 1024) i fake-chat (chat), oba domyślne."""
    await seed_model(sm, "fake-embed-1024", "embedding", dimension=1024)
    await seed_model(sm, "fake-chat", "chat")


async def exec_sql(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> None:
    """Jedna instrukcja SQL w transakcji (przygotowanie/odczyty testowe)."""
    async with transaction(sm) as session:
        await session.execute(text(sql), params)


async def count_sql(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> int:
    """Liczba wierszy zapytania (odczyty testowe)."""
    async with transaction(sm) as session:
        return len((await session.execute(text(sql), params)).scalars().all())
