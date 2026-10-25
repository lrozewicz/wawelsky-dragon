"""Narzędzie migracji schematu — `python -m app.tools.migrate` (kontrakt C8/C12)."""

import asyncio
import logging
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.core.logging import configure_logging
from app.core.timeutil import SystemClock
from app.db.engine import make_engine, make_sessionmaker
from app.db.schema import SCHEMA_HEAD
from app.llm.registry import ModelRegistry
from app.services.users import UserService

ALEMBIC_INI: Path = Path(__file__).resolve().parents[2] / "alembic.ini"

logger = logging.getLogger("app.tools.migrate")


async def seed_models(settings: Settings) -> int:
    """Zasiewa domyślne modele (kontrakt C12); zwraca liczbę wstawionych."""
    engine = make_engine(settings)
    try:
        registry = ModelRegistry(
            make_sessionmaker(engine), settings, SystemClock(), UuidV7Generator()
        )
        return await registry.seed_defaults()
    finally:
        await engine.dispose()


async def bootstrap_admin(settings: Settings) -> bool:
    """Tworzy konta admina z ustawień, jeśli brak (kontrakt C11); True gdy utworzony."""
    engine = make_engine(settings)
    try:
        users = UserService(make_sessionmaker(engine), settings, SystemClock(), UuidV7Generator())
        return await users.ensure_admin(
            settings.admin_email, settings.admin_password.get_secret_value()
        )
    finally:
        await engine.dispose()


def main() -> int:
    """Wykonuje `alembic upgrade head`, zasiew modeli i bootstrap admina; błąd → kod 1."""
    settings = Settings()
    configure_logging(settings)
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    inserted = asyncio.run(seed_models(settings))
    created = asyncio.run(bootstrap_admin(settings))
    logger.info("migrations applied", extra={"event": "migrate_done", "head": SCHEMA_HEAD})
    logger.info("models seeded", extra={"event": "models_seeded", "inserted": inserted})
    # DEC-001: klucz `created` koliduje z atrybutem LogRecord — prefiks admin_.
    logger.info("admin bootstrap", extra={"admin_created": created})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
