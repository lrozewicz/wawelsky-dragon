"""Środowisko Alembic — tryb async na MariaDB (kontrakt C7).

Wywoływane tylko z kodu synchronicznego (wewnątrz robi `asyncio.run`) — patrz C12.
"""

import asyncio

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context
from app.core.config import Settings
from app.db.engine import database_url

config = context.config

# Modele ORM poza zakresem (T2) — migracje trzymają czysty SQL, bez autogenerate.
target_metadata = None

# Ustawienia z wywołania programowego (`cfg.attributes["settings"]`, C12) albo z env (WD_*).
settings = context.config.attributes.get("settings") or Settings()


def run_migrations_offline() -> None:
    """Tryb offline nieobsługiwany (kontrakt C7)."""
    raise RuntimeError("offline mode not supported")


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(database_url(settings), poolclass=NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
