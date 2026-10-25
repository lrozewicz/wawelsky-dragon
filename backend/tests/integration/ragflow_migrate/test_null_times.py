"""Idempotencja etapów `users`/`keys` dla źródłowych NULL `create_time`/`update_time` (T8).

Źródło RAGFlow dopuszcza `NULL` w `user.create_time`/`update_time` i `api_token.*` — po
pierwszym biegu WD ma już konkretne wartości, a drugi bieg tych NULL-i nie może nadpisać.
"""

import hashlib
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.auth_tokens import sha256_hex
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb, source_writer

pytestmark = pytest.mark.db

U2_ID = "b0a1c2d3e4f5061728394a5b6c7d8e92"
U1_TOKEN = "ragflow-FIXTURE-u1-plain"  # noqa: S105 — token FIKCYJNY z fixture'u
U2_CREATE_MS = 1759305660000  # czas u2 z fixture'u źródła (oś czasu README §3, UTC)
U2_CREATE_DATE = "2025-10-01 08:01:00"

SOURCE_USERS = 3
SOURCE_KEYS = 4

UPDATE_USER_NULLS = "UPDATE `user` SET create_time = NULL, update_time = NULL WHERE id = %s"
UPDATE_TOKEN_NULLS = (
    "UPDATE `api_token` SET create_time = NULL, update_time = NULL WHERE token = %s"  # noqa: S105
)
USER_TIMES = "SELECT create_time, create_date, update_time, update_date FROM users WHERE id = :id"
KEY_TIMES = "SELECT create_time, update_time FROM api_keys WHERE token_hash = :h"


def _key_id(token: str) -> str:
    """Id klucza w WD (kontrakt §4) — w teście jawnie, bez importu z modułu etapu."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


async def _times(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any]
) -> tuple[Any, ...]:
    """Krotka czasów wiersza celu (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params)
        return tuple(result.first() or ())


def _null_source_times(ragflow_src: SourceDb) -> None:
    """Zeruje czasy w źródle przez publiczny `source_writer` z `conftest.py`."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(UPDATE_USER_NULLS, (U2_ID,))
        cursor.execute(UPDATE_TOKEN_NULLS, (U1_TOKEN,))


async def test_null_source_times_do_not_update_target_rows(
    ragflow_src: SourceDb, source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Drugi bieg po źródłowych NULL-ach: `updated == 0` i czasy w celu bez zmian."""
    first = await run_all(source, wd_db.sm, run_ctx, only=["users", "keys"])
    assert (first[0].created, first[0].updated, first[0].skipped) == (SOURCE_USERS, 0, 0)
    assert (first[1].created, first[1].updated, first[1].skipped) == (SOURCE_KEYS, 0, 0)
    user_before = await _times(wd_db.sm, USER_TIMES, {"id": U2_ID})
    key_before = await _times(wd_db.sm, KEY_TIMES, {"h": sha256_hex(U1_TOKEN)})
    assert user_before[0] == U2_CREATE_MS
    assert str(user_before[1]) == U2_CREATE_DATE
    assert user_before[2] == U2_CREATE_MS
    assert str(user_before[3]) == U2_CREATE_DATE

    _null_source_times(ragflow_src)
    # `source` siedzi w transakcji read-only sprzed UPDATE — potrzebne świeże połączenie.
    fresh = Source.connect(ragflow_src.dsn)
    try:
        second = await run_all(fresh, wd_db.sm, run_ctx, only=["users", "keys"])
    finally:
        fresh.close()

    users_result, keys_result = second
    assert users_result.updated == 0
    assert keys_result.updated == 0
    assert users_result.skipped == SOURCE_USERS
    assert keys_result.skipped == SOURCE_KEYS
    assert await _times(wd_db.sm, USER_TIMES, {"id": U2_ID}) == user_before
    assert await _times(wd_db.sm, KEY_TIMES, {"h": sha256_hex(U1_TOKEN)}) == key_before


async def test_null_source_times_on_insert_get_now(
    ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Bez wiersza w celu źródłowy NULL wypełnia `now_ms` (a nie NULL w kolumnie NOT NULL)."""
    _null_source_times(ragflow_src)
    fresh = Source.connect(ragflow_src.dsn)
    try:
        result = await run_all(fresh, wd_db.sm, run_ctx, only=["users", "keys"])
    finally:
        fresh.close()

    users_result, keys_result = result
    assert (users_result.created, users_result.updated) == (SOURCE_USERS, 0)
    assert (keys_result.created, keys_result.updated) == (SOURCE_KEYS, 0)
    assert None not in await _times(wd_db.sm, USER_TIMES, {"id": U2_ID})
    assert None not in await _times(wd_db.sm, KEY_TIMES, {"h": sha256_hex(U1_TOKEN)})
    async with wd_db.sm() as session:
        stored = await session.execute(
            text("SELECT id FROM api_keys WHERE id = :id"), {"id": _key_id(U1_TOKEN)}
        )
        assert stored.scalar_one() == _key_id(U1_TOKEN)
