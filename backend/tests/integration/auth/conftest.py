"""Fixture'y testów auth na MariaDB (brief T3, kontrakt C5 i sekcja „Testy”)."""

from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from tests.integration.db.helpers import alembic_cfg


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
def auth_settings(migrated_db: Settings) -> Settings:
    """Ustawienia z sekretami generowanymi w teście — `.env` nieczytany (sekcja „Testy”)."""
    return migrated_db.model_copy(
        update={"secret_key": SecretStr("s" * 48), "crypto_key": SecretStr("ab" * 32)}
    )


@pytest.fixture
async def sm(auth_settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(auth_settings)
    yield make_sessionmaker(engine)
    await engine.dispose()
