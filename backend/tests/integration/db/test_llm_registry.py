"""Testy ModelRegistry na MariaDB (brief T4, kontrakt C11).

Przygotowanie bazy w teście async przez `asyncio.to_thread` — `env.py` robi `asyncio.run`,
więc nie wolno wołać `command.upgrade` bezpośrednio w pętli zdarzeń.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from app.core.config import Settings
from app.core.crypto import encrypt
from app.core.errors import NotFound, OperationNotAllowed
from app.core.timeutil import from_ms
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import provider_instances
from app.db.uow import transaction
from app.llm.registry import ModelRegistry
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

SEED_COUNT = 4  # chat + embedding + rerank + image2text przy pełnych WD_LLM_DEFAULT_*
SEED_COUNT_NO_RERANK = 3  # pusty WD_LLM_DEFAULT_RERANK pomija rerank
DIM = 3072

# Instancja dostawcy dla testów `resolve` z instancją (K13 §0 p. 4, §1).
INSTANCE_ID = "b" * 32
INSTANCE_URL = "http://inst.local/v1"
INSTANCE_KEY = "k1"

# Ustawienia rejestru wg briefu T4; crypto_key 64 hex — potrzebny do decrypt w resolve.
UPDATES: dict[str, Any] = {
    "llm_default_chat": "fake-chat",
    "llm_default_embedding": "fake-embed-3072",
    "llm_default_rerank": "fake-rerank",
    "llm_default_vlm": "fake-vision",
    "crypto_key": SecretStr("00" * 32),
}


class Env:
    """Zmigrowana baza + fabryka rejestrów + pomocnicze zapytania Core."""

    def __init__(self, fresh_db: Settings, engine: AsyncEngine) -> None:
        self.fresh_db = fresh_db
        self.engine = engine
        self.sessionmaker = make_sessionmaker(engine)

    def registry(self, **updates: Any) -> ModelRegistry:
        settings = self.fresh_db.model_copy(update={**UPDATES, **updates})
        return ModelRegistry(self.sessionmaker, settings, FrozenClock(), SeqIdGenerator())

    async def execute(self, sql: str, **params: Any) -> None:
        """UPDATE/INSERT modyfikujący stan na potrzeby testu (osobna transakcja)."""
        async with transaction(self.sessionmaker) as session:
            await session.execute(text(sql), params)

    async def one(self, sql: str, **params: Any) -> RowMapping:
        """Jeden wiersz z bazy na świeżym połączeniu."""
        async with self.sessionmaker() as session:
            return (await session.execute(text(sql), params)).mappings().one()


@pytest.fixture
async def env(fresh_db: Settings) -> AsyncIterator[Env]:
    """Zmigrowana świeża baza; engine zamknięty po teście."""
    await asyncio.to_thread(command.upgrade, alembic_cfg(fresh_db), "head")
    engine = make_engine(fresh_db)
    yield Env(fresh_db, engine)
    await engine.dispose()


async def test_seed_defaults_empty(env: Env) -> None:
    inserted = await env.registry().seed_defaults()
    assert inserted == SEED_COUNT
    rows = await env.one(
        "SELECT COUNT(*) AS n, SUM(is_default = 1) AS defaults,"
        " SUM(provider = 'litellm') AS litellm FROM models"
    )
    assert rows["n"] == SEED_COUNT
    assert rows["defaults"] == SEED_COUNT
    assert rows["litellm"] == SEED_COUNT
    types = await env.one("SELECT COUNT(DISTINCT model_type) AS n FROM models")
    assert types["n"] == SEED_COUNT


async def test_seed_defaults_second_time(env: Env) -> None:
    await env.registry().seed_defaults()
    assert await env.registry().seed_defaults() == 0
    rows = await env.one("SELECT COUNT(*) AS n FROM models")
    assert rows["n"] == SEED_COUNT


async def test_seed_defaults_logs_existing_model(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """Drugi zasiew: istniejące modele → INFO `seed_default_model_exists` (nazwa + typ, C4)."""
    await env.registry().seed_defaults()
    caplog.set_level(logging.INFO, logger="app.llm")
    assert await env.registry().seed_defaults() == 0
    events = [record for record in caplog.records if record.event == "seed_default_model_exists"]
    assert {(record.model_name, record.model_type) for record in events} == {
        ("fake-chat", "chat"),
        ("fake-embed-3072", "embedding"),
        ("fake-rerank", "rerank"),
        ("fake-vision", "image2text"),
    }


async def test_seed_defaults_empty_rerank(env: Env) -> None:
    assert await env.registry(llm_default_rerank="").seed_defaults() == SEED_COUNT_NO_RERANK
    rows = await env.one("SELECT COUNT(*) AS n FROM models WHERE model_type = 'rerank'")
    assert rows["n"] == 0


async def test_seed_keeps_existing_default(env: Env) -> None:
    """W tabeli jest już chat is_default=1 o innej nazwie → nowy seed z is_default=0 (C11)."""
    now = FrozenClock().now_ms()
    await env.execute(
        "INSERT INTO models (id, name, model_type, is_default, create_time, create_date,"
        " update_time, update_date)"
        " VALUES (:id, 'stary-chat', 'chat', 1, :now, :date, :now, :date)",
        id="a" * 32,
        now=now,
        date=from_ms(now).replace(tzinfo=None),
    )
    assert await env.registry().seed_defaults() == SEED_COUNT
    fake = await env.one("SELECT is_default FROM models WHERE name = 'fake-chat'")
    assert fake["is_default"] == 0
    stary = await env.one("SELECT is_default FROM models WHERE name = 'stary-chat'")
    assert stary["is_default"] == 1


async def test_resolve_default(env: Env) -> None:
    await env.registry().seed_defaults()
    for ref in (None, ""):
        model = await env.registry().resolve(ref, "chat")
        assert model.name == "fake-chat"
        assert model.model_type == "chat"
        assert model.id is not None and re.fullmatch(r"[0-9a-f]{32}", model.id)
        assert model.api_key is None


async def test_resolve_by_id(env: Env) -> None:
    await env.registry().seed_defaults()
    chat = await env.registry().resolve(None, "chat")
    assert chat.id is not None
    same = await env.registry().resolve(chat.id, "chat")
    assert same == chat
    with pytest.raises(NotFound) as exc:
        await env.registry().resolve(chat.id, "embedding")
    assert exc.value.message == f"model not found: {chat.id}"


@pytest.mark.parametrize(
    "ref",
    ["fake-chat", "fake-chat@OpenAI-API-Compatible", "fake-chat@recorder@OpenAI-API-Compatible"],
)
async def test_resolve_name_suffixes(env: Env, ref: str) -> None:
    await env.registry().seed_defaults()
    assert await env.registry().resolve(ref, "chat") == await env.registry().resolve(None, "chat")


async def test_resolve_missing(env: Env) -> None:
    await env.registry().seed_defaults()
    with pytest.raises(NotFound) as exc:
        await env.registry().resolve("nie-ma", "chat")
    assert exc.value.message == "model not found: nie-ma"


async def test_resolve_inactive(env: Env) -> None:
    await env.registry().seed_defaults()
    await env.execute("UPDATE models SET is_active = 0 WHERE name = 'fake-chat'")
    with pytest.raises(NotFound) as exc:
        await env.registry().resolve(None, "chat")
    assert exc.value.message == "model not found: default chat"


async def test_resolve_no_default_rerank(env: Env) -> None:
    await env.registry(llm_default_rerank="").seed_defaults()
    with pytest.raises(NotFound) as exc:
        await env.registry().resolve(None, "rerank")
    assert exc.value.message == "model not found: default rerank"


async def test_resolve_decrypts_api_key(env: Env) -> None:
    await env.registry().seed_defaults()
    await env.execute(
        "UPDATE models SET api_key_enc = :blob, base_url = 'http://x/v1',"
        """ extra = '{"extra_body": {"a": 1}}' WHERE name = 'fake-chat'""",
        blob=encrypt("00" * 32, b"sk-test"),
    )
    ref = await env.registry().resolve(None, "chat")
    assert ref.api_key is not None and ref.api_key.get_secret_value() == "sk-test"
    assert ref.base_url == "http://x/v1"
    assert ref.extra == {"extra_body": {"a": 1}}


async def test_set_dimension(env: Env) -> None:
    await env.registry().seed_defaults()
    embed = await env.registry().resolve(None, "embedding")
    assert embed.id is not None
    registry = env.registry()
    await registry.set_dimension(embed.id, DIM)
    rows = await env.one("SELECT dimension FROM models WHERE name = 'fake-embed-3072'")
    assert rows["dimension"] == DIM
    await registry.set_dimension(embed.id, DIM)  # ta sama wartość → OK
    with pytest.raises(OperationNotAllowed) as exc:
        await registry.set_dimension(embed.id, 1024)
    assert exc.value.message == f"model dimension mismatch: {DIM} != 1024"
    with pytest.raises(NotFound) as missing:
        await registry.set_dimension("f" * 32, 1)
    assert missing.value.message == f"model not found: {'f' * 32}"


async def test_insert_time_columns(env: Env) -> None:
    """create_time z zegara rejestru, create_date = from_ms (porównanie bez strefy)."""
    await env.registry().seed_defaults()
    rows = await env.one("SELECT create_time, create_date FROM models WHERE name = 'fake-chat'")
    now = FrozenClock().now_ms()
    assert rows["create_time"] == now
    assert rows["create_date"] == from_ms(now).replace(tzinfo=None)


async def _seed_instance(
    env: Env, *, base_url: str = INSTANCE_URL, key: str | None = INSTANCE_KEY
) -> None:
    """Wstawia instancję dostawcy; klucz szyfrowany z AAD ``provider-instance:<id>`` (K13 §1)."""
    blob = (
        None
        if key is None
        else encrypt("00" * 32, key.encode(), aad=b"provider-instance:" + INSTANCE_ID.encode())
    )
    async with transaction(env.sessionmaker) as session:
        await provider_instances.insert(
            session,
            id=INSTANCE_ID,
            provider="litellm",
            name="Produkcja",
            base_url=base_url,
            api_key_enc=blob,
            created_by=None,
            now_ms=FrozenClock().now_ms(),
        )


async def test_resolve_uses_instance_endpoint(env: Env) -> None:
    """Model z `instance_id`, bez własnego `base_url`/klucza → jedno i drugie z instancji."""
    await env.registry().seed_defaults()
    await _seed_instance(env)
    await env.execute(
        "UPDATE models SET instance_id = :iid WHERE name = 'fake-chat'", iid=INSTANCE_ID
    )
    ref = await env.registry().resolve("fake-chat", "chat")
    assert ref.base_url == INSTANCE_URL
    assert ref.api_key is not None
    assert ref.api_key.get_secret_value() == INSTANCE_KEY


async def test_resolve_instance_without_key(env: Env) -> None:
    """Instancja bez klucza → `base_url` z instancji, `api_key` None (K13 §0 p. 4)."""
    await env.registry().seed_defaults()
    await _seed_instance(env, key=None)
    await env.execute(
        "UPDATE models SET instance_id = :iid WHERE name = 'fake-chat'", iid=INSTANCE_ID
    )
    ref = await env.registry().resolve("fake-chat", "chat")
    assert ref.base_url == INSTANCE_URL
    assert ref.api_key is None


async def test_resolve_row_values_win_over_instance(env: Env) -> None:
    """Stan sprzed K13: własny `base_url` i klucz wiersza wygrywają z instancją."""
    await env.registry().seed_defaults()
    await _seed_instance(env)
    await env.execute(
        "UPDATE models SET instance_id = :iid, base_url = 'http://row.local/v1',"
        " api_key_enc = :blob WHERE name = 'fake-chat'",
        iid=INSTANCE_ID,
        blob=encrypt("00" * 32, b"sk-row"),
    )
    ref = await env.registry().resolve("fake-chat", "chat")
    assert ref.base_url == "http://row.local/v1"
    assert ref.api_key is not None
    assert ref.api_key.get_secret_value() == "sk-row"


async def test_resolve_row_base_url_with_instance_key(env: Env) -> None:
    """Wiersz ma `base_url`, nie ma klucza → klucz dochodzi z instancji (K13 §0 p. 4)."""
    await env.registry().seed_defaults()
    await _seed_instance(env)
    await env.execute(
        "UPDATE models SET instance_id = :iid, base_url = 'http://row.local/v1'"
        " WHERE name = 'fake-chat'",
        iid=INSTANCE_ID,
    )
    ref = await env.registry().resolve("fake-chat", "chat")
    assert ref.base_url == "http://row.local/v1"
    assert ref.api_key is not None
    assert ref.api_key.get_secret_value() == INSTANCE_KEY


async def test_resolve_without_instance_has_no_endpoint(env: Env) -> None:
    """Model bez instancji i bez `base_url`/klucza → oba `None` (globalne z Settings)."""
    await env.registry().seed_defaults()
    ref = await env.registry().resolve(None, "chat")
    assert ref.base_url is None
    assert ref.api_key is None
