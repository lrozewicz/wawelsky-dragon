"""Testy unit warstwy DB — engine i sessionmaker, bez bazy (kontrakt C1)."""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.db.engine import database_url, make_engine, make_sessionmaker

_DB_PASSWORD = "p@ss"  # noqa: S105 — celowe atrapa hasła w teście
_DB_PORT = 3307


def _settings() -> Settings:
    """Ustawienia testowe z literałów — bez env i bez bazy."""
    return Settings(
        env="test",
        db_host="h",
        db_port=_DB_PORT,
        db_user="u",
        db_password=_DB_PASSWORD,
        db_name="n",
    )


def test_database_url() -> None:
    url = database_url(_settings())
    assert url.drivername == "mysql+asyncmy"
    assert url.host == "h"
    assert url.port == _DB_PORT
    assert url.username == "u"
    assert url.password == _DB_PASSWORD
    assert url.database == "n"
    assert url.query == {"charset": "utf8mb4"}


def test_database_url_driver() -> None:
    assert database_url(_settings(), driver="pymysql").drivername == "mysql+pymysql"


async def test_make_engine() -> None:
    settings = _settings()
    engine = make_engine(settings)
    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "mysql+asyncmy"
    assert engine.pool.size() == settings.db_pool_size
    await engine.dispose()


async def test_make_sessionmaker() -> None:
    engine = make_engine(_settings())
    sm = make_sessionmaker(engine)
    assert isinstance(sm, async_sessionmaker)
    assert sm.kw["expire_on_commit"] is False
    await engine.dispose()
