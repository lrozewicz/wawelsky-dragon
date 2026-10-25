"""Testy sesji i transakcji na prawdziwej MariaDB (kontrakt C12)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.engine import make_sessionmaker
from app.db.uow import transaction

pytestmark = pytest.mark.db


async def test_select_one(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1


async def test_transaction_commits(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (id INT PRIMARY KEY)"))
    async with transaction(make_sessionmaker(db_engine)) as session:
        await session.execute(text("INSERT INTO t (id) VALUES (1)"))
    async with make_sessionmaker(db_engine)() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM t"))
        assert result.scalar_one() == 1


async def test_transaction_rolls_back(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (id INT PRIMARY KEY)"))
    with pytest.raises(RuntimeError, match="boom"):
        async with transaction(make_sessionmaker(db_engine)) as session:
            await session.execute(text("INSERT INTO t (id) VALUES (2)"))
            raise RuntimeError("boom")
    async with make_sessionmaker(db_engine)() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM t WHERE id = 2"))
        assert result.scalar_one() == 0


async def test_server_settings(db_engine: AsyncEngine, fresh_db: Settings) -> None:
    """Kolacja serwera i świeżej bazy zgodna z K2; min token FULLTEXT = 2."""
    async with db_engine.connect() as conn:
        # SHOW VARIABLES zwraca wiersz (Variable_name, Value) — wartość to kolumna [1].
        result = await conn.execute(text("SHOW VARIABLES LIKE 'innodb_ft_min_token_size'"))
        assert result.one()[1] == "2"
        result = await conn.execute(text("SELECT @@collation_server"))
        assert result.scalar_one() == "utf8mb4_uca1400_ai_ci"
        result = await conn.execute(
            text(
                "SELECT DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA"
                " WHERE SCHEMA_NAME = :n"
            ),
            {"n": fresh_db.db_name},
        )
        assert result.scalar_one() == "utf8mb4_uca1400_ai_ci"
