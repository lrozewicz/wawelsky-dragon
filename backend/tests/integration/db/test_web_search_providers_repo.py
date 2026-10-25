"""Testy repozytorium `web_search_providers` na MariaDB (CONTRACT E6-3f §C2, K2 §6)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import web_search_providers as repo
from app.db.uow import transaction
from app.services.web_search import keys
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME_MS

pytestmark = pytest.mark.db

LATER = TIME_MS + 1000
ID_A = "a" * 32
ID_B = "b" * 32
PLAIN = "tvly-SECRET-key"
SEARXNG_CONFIG = {"base_url": "http://searxng:8080"}


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


async def _insert(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    sm: async_sessionmaker[AsyncSession],
    *,
    id: str = ID_A,
    provider: str = "tavily",
    name: str = "Tavily",
    config: dict | None = None,
    api_key_enc: bytes | None = None,
    is_default: bool = False,
    created_by: str | None = None,
    now_ms: int = TIME_MS,
) -> None:
    """Wstawia dostawcę do bazy (§C2)."""
    async with transaction(sm) as session:
        await repo.insert(
            session,
            id=id,
            provider=provider,
            name=name,
            config=config if config is not None else {"base_url": "http://tavily.local"},
            api_key_enc=api_key_enc,
            is_default=is_default,
            created_by=created_by,
            now_ms=now_ms,
        )


async def _raw(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> list[tuple]:
    """Wykonuje surowy SELECT w transakcji i zwraca wiersze."""
    async with transaction(sm) as session:
        result = await session.execute(text(sql), params)
        return [tuple(row) for row in result.all()]


async def test_insert_and_get_round_trip(sm: async_sessionmaker[AsyncSession]) -> None:
    """`insert` + `get_by_id`: pola, `config` jako dict, brak dla nieznanego id (§C2)."""
    config = {"base_url": "http://tavily.local", "top_n": 5}
    await _insert(sm, config=config)
    async with transaction(sm) as session:
        row = await repo.get_by_id(session, ID_A)
        assert row is not None
        assert (row.id, row.provider, row.name) == (ID_A, "tavily", "Tavily")
        assert row.config == config
        assert row.is_default is False
        assert row.created_by is None
        assert row.create_time == TIME_MS
        assert await repo.get_by_id(session, uuid.uuid4().hex) is None


async def test_get_by_name_case_insensitive(sm: async_sessionmaker[AsyncSession]) -> None:
    """`get_by_name` nie rozróżnia wielkości liter (kolacja `uca1400_ai_ci`, §C2)."""
    await _insert(sm, name="Szukacz")
    async with transaction(sm) as session:
        assert await repo.get_by_name(session, "szukacz") is not None
        assert await repo.get_by_name(session, "brak") is None


async def test_seed_searxng_is_default(migrated_db: Settings) -> None:
    """Seed migracji: `searxng` widoczny przez `get_default`, `config` jako dict (§C2, K2 §6)."""
    engine = make_engine(migrated_db)
    sm = make_sessionmaker(engine)
    try:
        async with transaction(sm) as session:
            row = await repo.get_default(session)
    finally:
        await engine.dispose()
    assert row is not None
    assert row.provider == "searxng"
    assert row.name == "searxng"
    assert row.config == SEARXNG_CONFIG
    assert row.is_default is True
    assert row.api_key_enc is None


async def test_get_default_is_oldest(sm: async_sessionmaker[AsyncSession]) -> None:
    """`get_default` zwraca najmniejsze `create_time` wśród domyślnych (§C2)."""
    await _insert(sm, id=ID_A, name="Nowy", is_default=True, now_ms=TIME_MS)
    await _insert(sm, id=ID_B, name="Starszy", is_default=True, now_ms=1000)
    async with transaction(sm) as session:
        row = await repo.get_default(session)
    assert row is not None
    assert row.id == ID_B


async def test_list_all_order(sm: async_sessionmaker[AsyncSession]) -> None:
    """`list_all` w kolejności `create_time` ASC (najstarszy pierwszy, §C2)."""
    await _insert(sm, id=ID_A, name="Drugi", now_ms=LATER)
    await _insert(sm, id=ID_B, name="Pierwszy", now_ms=TIME_MS)
    async with transaction(sm) as session:
        rows = await repo.list_all(session)
    ids = [r.id for r in rows if r.id in (ID_A, ID_B)]
    assert ids == [ID_B, ID_A]


async def test_update_set_key_true_and_false(sm: async_sessionmaker[AsyncSession]) -> None:
    """`update` zmienia pola; klucz tylko przy `set_key=True` (§C2)."""
    await _insert(sm, config={"base_url": "http://a.local"})
    async with transaction(sm) as session:
        await repo.update(
            session,
            provider_id=ID_A,
            name="Nowa nazwa",
            config={"base_url": "http://b.local"},
            is_default=True,
            api_key_enc=b"klucz-1",
            set_key=True,
            now_ms=LATER,
        )
        row = await repo.get_by_id(session, ID_A)
    assert row is not None
    assert (row.name, row.config) == ("Nowa nazwa", {"base_url": "http://b.local"})
    assert row.is_default is True
    assert row.api_key_enc == b"klucz-1"
    assert row.create_time == TIME_MS
    # set_key=False nie rusza klucza.
    async with transaction(sm) as session:
        await repo.update(
            session,
            provider_id=ID_A,
            name="Jeszcze inna",
            config={"base_url": "http://c.local"},
            is_default=False,
            api_key_enc=b"klucz-2",
            set_key=False,
            now_ms=LATER,
        )
        row2 = await repo.get_by_id(session, ID_A)
    assert row2 is not None
    assert row2.api_key_enc == b"klucz-1"


async def test_delete_by_id(sm: async_sessionmaker[AsyncSession]) -> None:
    """`delete_by_id` zwraca liczbę usuniętych wierszy, wiersz znika (§C2)."""
    await _insert(sm)
    async with transaction(sm) as session:
        assert await repo.delete_by_id(session, ID_A) == 1
        assert await repo.get_by_id(session, ID_A) is None
        assert await repo.delete_by_id(session, ID_A) == 0


async def test_repr_hides_key_bytes(sm: async_sessionmaker[AsyncSession]) -> None:
    """`repr(row)` nie zawiera bajtów klucza (`field(repr=False)`, §C2, testy negatywne)."""
    await _insert(sm, api_key_enc=b"super-tajny-blob")
    async with transaction(sm) as session:
        row = await repo.get_by_id(session, ID_A)
    assert row is not None
    assert "super-tajny-blob" not in repr(row)
    assert "super-tajny-blob" not in str(row)


async def test_key_encrypted_in_db(migrated_db: Settings) -> None:
    """Klucz w DB zaszyfrowany: kolumna ≠ plaintext, bez podciągu; `repr`/`str` bez klucza.

    Test negatywny pary mutacji `k18-web-search-key-leak` (CONTRACT §C2/§C3).
    """
    engine = make_engine(migrated_db)
    sm = make_sessionmaker(engine)
    try:
        blob = keys.encrypt_key(migrated_db, ID_A, PLAIN)
        async with transaction(sm) as session:
            await repo.insert(
                session,
                id=ID_A,
                provider="tavily",
                name="Tavily",
                config={"base_url": "http://tavily.local"},
                api_key_enc=blob,
                is_default=False,
                created_by=None,
                now_ms=TIME_MS,
            )
        raw = await _raw(
            sm,
            "SELECT api_key_enc FROM web_search_providers WHERE id = CAST(:id AS BINARY)",
            id=ID_A,
        )
        stored = raw[0][0]
        assert stored != PLAIN.encode()
        assert PLAIN.encode() not in bytes(stored)
        async with transaction(sm) as session:
            row = await repo.get_by_id(session, ID_A)
        assert row is not None
        assert PLAIN not in repr(row)
        assert PLAIN not in str(row)
        # Blob odszyfrowuje się z powrotem do jawnego klucza (AAD = id).
        assert keys.decrypt_key(migrated_db, ID_A, bytes(stored)) == PLAIN
    finally:
        await engine.dispose()
