"""Testy repozytoriów instancji dostawców: `provider_instances` i instancyjnych funkcji `models`
na MariaDB (brief E3-6b/T1, kontrakt K13 §1, §3, CONTRACT E3-6b §T1)."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.timeutil import from_ms
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as repo
from app.db.uow import transaction
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import seed_dataset

pytestmark = pytest.mark.db

NOW = FrozenClock().now_ms()
LATER = NOW + 1000
ID_A = "a" * 32
ID_B = "b" * 32
MODEL_A = "c" * 32
MODEL_B = "d" * 32
KEY = b"zaszyfrowany-klucz"
DATASETS_USING_MODEL = 3  # po id, po nazwie i po nazwie z odciętym `@…`


@pytest.fixture
async def db(fresh_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Zmigrowana świeża baza; fabryka sesji, engine zamknięty po teście."""
    await asyncio.to_thread(command.upgrade, alembic_cfg(fresh_db), "head")
    engine = make_engine(fresh_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def _insert(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    db: async_sessionmaker[AsyncSession],
    *,
    id: str = ID_A,
    name: str = "Produkcja",
    base_url: str = "http://llm.local/v1",
    api_key_enc: bytes | None = KEY,
    created_by: str | None = None,
    now_ms: int = NOW,
) -> None:
    async with transaction(db) as session:
        await repo.insert(
            session,
            id=id,
            provider="litellm",
            name=name,
            base_url=base_url,
            api_key_enc=api_key_enc,
            created_by=created_by,
            now_ms=now_ms,
        )


async def _instance(
    db: async_sessionmaker[AsyncSession], sql: str, **params: object
) -> list[tuple[object, ...]]:
    async with db() as session:
        return [tuple(row) for row in (await session.execute(text(sql), params)).all()]


async def test_insert_and_get_by_id(db: async_sessionmaker[AsyncSession]) -> None:
    """Roundtrip: wszystkie pola wiersza po `insert`, `None` dla nieznanego id."""
    await _insert(db)
    async with transaction(db) as session:
        row = await repo.get_by_id(session, ID_A)
        assert row is not None
        assert (row.id, row.provider, row.name) == (ID_A, "litellm", "Produkcja")
        assert row.base_url == "http://llm.local/v1"
        assert row.api_key_enc == KEY
        assert row.created_by is None
        assert row.create_time == NOW
        assert await repo.get_by_id(session, ID_B) is None


async def test_insert_time_columns(db: async_sessionmaker[AsyncSession]) -> None:
    """create_time/update_time z zegara wołającego, daty po `from_ms` (wzór `models`)."""
    await _insert(db)
    rows = await _instance(
        db, "SELECT create_time, create_date, update_time, update_date FROM provider_instances"
    )
    date = from_ms(NOW).replace(tzinfo=None)
    assert rows == [(NOW, date, NOW, date)]


async def test_get_by_name_is_case_insensitive(db: async_sessionmaker[AsyncSession]) -> None:
    """Kolacja `uca1400_ai_ci`: „Default" znajduje wiersz zapisany jako „default" (K13 §1)."""
    await _insert(db, name="default")
    async with transaction(db) as session:
        assert await repo.get_by_name(session, "litellm", "Default") is not None
        assert await repo.get_by_name(session, "litellm", "DEFAULT") is not None
        assert await repo.get_by_name(session, "other", "default") is None


async def test_list_by_provider_orders_newest_first(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """Kolejność `create_time DESC, id` i filtr po dostawcy (K13 §3 p. 1)."""
    await _insert(db, id=ID_A, name="starsza", now_ms=NOW)
    await _insert(db, id=ID_B, name="nowsza", now_ms=LATER)
    async with transaction(db) as session:
        rows = await repo.list_by_provider(session, "litellm")
        assert [row.id for row in rows] == [ID_B, ID_A]
        assert rows[0].name == "nowsza"
        assert await repo.list_by_provider(session, "openai") == []


async def test_update_without_key_keeps_secret(db: async_sessionmaker[AsyncSession]) -> None:
    """`set_key=False` nie rusza `api_key_enc`; nazwa, `base_url` i czas idą z zapisu."""
    await _insert(db)
    async with transaction(db) as session:
        await repo.update(
            session,
            instance_id=ID_A,
            name="Staging",
            base_url="http://staging.local/v1",
            api_key_enc=None,
            set_key=False,
            now_ms=LATER,
        )
    row = await _instance(
        db, "SELECT name, base_url, api_key_enc, update_time FROM provider_instances"
    )
    assert row == [("Staging", "http://staging.local/v1", KEY, LATER)]


async def test_update_with_key_replaces_secret(db: async_sessionmaker[AsyncSession]) -> None:
    """`set_key=True` podmienia klucz; `api_key_enc=None` klucz usuwa (K13 §4 p. 2)."""
    await _insert(db)
    async with transaction(db) as session:
        await repo.update(
            session,
            instance_id=ID_A,
            name="Produkcja",
            base_url="http://llm.local/v1",
            api_key_enc=b"nowy",
            set_key=True,
            now_ms=LATER,
        )
        await repo.update(
            session,
            instance_id=ID_A,
            name="Produkcja",
            base_url="http://llm.local/v1",
            api_key_enc=None,
            set_key=True,
            now_ms=LATER,
        )
    assert await _instance(db, "SELECT api_key_enc FROM provider_instances") == [(None,)]


async def test_delete_by_ids_returns_rowcount(db: async_sessionmaker[AsyncSession]) -> None:
    """`delete_by_ids` usuwa wskazane instancje i zwraca liczbę wierszy (CONTRACT §T1)."""
    await _insert(db, id=ID_A, name="jedna")
    await _insert(db, id=ID_B, name="druga")
    async with transaction(db) as session:
        assert await repo.delete_by_ids(session, [ID_A, "c" * 32]) == 1
        assert await repo.delete_by_ids(session, []) == 0
    assert await _instance(db, "SELECT id FROM provider_instances") == [(ID_B,)]


async def _insert_model(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    db: async_sessionmaker[AsyncSession],
    *,
    id: str = MODEL_A,
    name: str = "m-chat",
    model_type: str = "chat",
    instance_id: str | None = ID_A,
    max_tokens: int = 8192,
    dimension: int | None = None,
    extra: dict | None = None,
) -> None:
    async with transaction(db) as session:
        await models_repo.insert_for_instance(
            session,
            id=id,
            name=name,
            model_type=model_type,
            instance_id=instance_id,
            max_tokens=max_tokens,
            dimension=dimension,
            extra=extra,
            created_by=None,
            now_ms=NOW,
        )


async def test_insert_for_instance_columns(db: async_sessionmaker[AsyncSession]) -> None:
    """`insert_for_instance`: provider='litellm', is_default=0, is_active=1, base_url/klucz NULL."""
    await _insert(db)
    await _insert_model(db, extra={"a": 1}, dimension=1024, model_type="embedding")
    rows = await _instance(
        db,
        "SELECT provider, is_default, is_active, base_url, api_key_enc, max_tokens, dimension,"
        " extra, instance_id FROM models WHERE id = :id",
        id=MODEL_A,
    )
    assert rows == [("litellm", 0, 1, None, None, 8192, 1024, '{"a": 1}', ID_A)]


async def test_list_by_instance_orders_by_name(db: async_sessionmaker[AsyncSession]) -> None:
    """`list_by_instance`: filtr po instancji (None → IS NULL) i kolejność (name, model_type)."""
    await _insert(db)
    await _insert_model(db, id=MODEL_B, name="m-b", model_type="embedding")
    await _insert_model(db, id=MODEL_A, name="m-a", model_type="chat")
    await _insert_model(db, id="e" * 32, name="m-c", model_type="chat", instance_id=None)
    async with transaction(db) as session:
        rows = await models_repo.list_by_instance(session, ID_A)
        assert [(row.name, row.model_type) for row in rows] == [
            ("m-a", "chat"),
            ("m-b", "embedding"),
        ]
        assert all(row.instance_id == ID_A for row in rows)
        detached = await models_repo.list_by_instance(session, None)
        assert [(row.id, row.instance_id) for row in detached] == [("e" * 32, None)]


async def test_get_by_name_type_any(db: async_sessionmaker[AsyncSession]) -> None:
    """Para (nazwa, typ) z dowolnej instancji: ten sam wiersz co `get_by_name`."""
    await _insert(db)
    await _insert_model(db, id="e" * 32, name="m-chat", model_type="chat", instance_id=None)
    async with transaction(db) as session:
        row = await models_repo.get_by_name_type_any(session, "m-chat", "chat")
        assert row is not None and row.id == "e" * 32
        assert await models_repo.get_by_name_type_any(session, "m-chat", "embedding") is None


async def test_update_fields_only_given(db: async_sessionmaker[AsyncSession]) -> None:
    """`update_fields` zmienia tylko podane pola i zawsze `update_time`/`update_date`."""
    await _insert(db)
    await _insert_model(db)
    async with transaction(db) as session:
        await models_repo.update_fields(
            session,
            model_id=MODEL_A,
            is_active=False,
            max_tokens=None,
            extra=None,
            now_ms=LATER,
        )
    rows = await _instance(
        db, "SELECT is_active, max_tokens, update_time FROM models WHERE id = :id", id=MODEL_A
    )
    assert rows == [(0, 8192, LATER)]


async def test_delete_by_ids_models(db: async_sessionmaker[AsyncSession]) -> None:
    """`delete_by_ids` w `models` usuwa wskazane wiersze i zwraca rowcount."""
    await _insert(db)
    await _insert_model(db, id=MODEL_A, name="m-a")
    await _insert_model(db, id=MODEL_B, name="m-b")
    async with transaction(db) as session:
        assert await models_repo.delete_by_ids(session, [MODEL_A]) == 1
    assert await _instance(db, "SELECT id FROM models ORDER BY id") == [(MODEL_B,)]


async def test_count_datasets_using_matches_id_and_name(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """Liczy datasety po id, po nazwie i po nazwie z odciętym `@…` — jak `ModelRegistry._find`."""
    await _insert(db)
    await _insert_model(db, id=MODEL_A, name="m-embed", model_type="embedding")
    await seed_dataset(db, embedding_model="m-embed")
    await seed_dataset(db, embedding_model=MODEL_A)
    await seed_dataset(db, embedding_model="m-embed@litellm")
    await seed_dataset(db, embedding_model="inny-model")
    async with transaction(db) as session:
        model = await models_repo.get_by_id(session, MODEL_A)
        assert model is not None
        assert await models_repo.count_datasets_using(session, model) == DATASETS_USING_MODEL
        unused = replace(model, id="f" * 32, name="nieużywany")
        assert await models_repo.count_datasets_using(session, unused) == 0
