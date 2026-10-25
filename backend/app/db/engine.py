"""Engine i fabryka sesji MariaDB (kontrakt C1) — bez globali i połączeń przy imporcie."""

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def database_url(settings: Settings, *, driver: str = "asyncmy") -> URL:
    """URL mysql+<driver>://user:pass@host:port/name?charset=utf8mb4.

    Tworzony przez ``URL.create`` — hasło z SecretStr, bez ręcznego escapowania.
    """
    return URL.create(
        drivername=f"mysql+{driver}",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        query={"charset": "utf8mb4"},
    )


def make_engine(settings: Settings) -> AsyncEngine:
    """Silnik async MariaDB z pulą wg Settings. Bez łączenia z bazą."""
    return create_async_engine(
        database_url(settings),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_overflow,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={"connect_timeout": 5},
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji: expire_on_commit=False, by obiekty przeżywały commit."""
    return async_sessionmaker(engine, expire_on_commit=False)
