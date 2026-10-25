"""Bramka fake-llm przez instancję dostawcy: `resolve` → OpenAIGateway (K13 §0 p. 4).

Model w rejestrze ma `instance_id`, a `base_url`/klucz dochodzą z wiersza instancji —
bramka musi odpowiedzieć tak samo jak przy wartościach globalnych z ``Settings``.
"""

import asyncio
import os

import pytest

from alembic import command
from app.core.config import Settings
from app.core.crypto import encrypt
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as instances_repo
from app.db.uow import transaction
from app.llm.openai_gateway import OpenAIGateway
from app.llm.registry import ModelRegistry
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.integration.db.helpers import alembic_cfg

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

INSTANCE_ID = "b" * 32
MODEL_ID = "a" * 32
INSTANCE_KEY = "fake-instance-key"
QUESTION = [{"role": "user", "content": "Jak się masz?"}]
ANSWER = "Odpowiedź testowa: Jak się masz?"


async def test_resolve_and_chat_through_instance(fresh_db: Settings) -> None:
    """`resolve` bierze `base_url`/klucz z instancji, a bramka odpowiada przez fake-llm."""
    await asyncio.to_thread(command.upgrade, alembic_cfg(fresh_db), "head")
    engine = make_engine(fresh_db)
    sessionmaker = make_sessionmaker(engine)
    now = FrozenClock().now_ms()
    base_url = os.environ["WD_LLM_BASE_URL"]
    crypto_key = fresh_db.crypto_key.get_secret_value()
    try:
        async with transaction(sessionmaker) as session:
            await instances_repo.insert(
                session,
                id=INSTANCE_ID,
                provider="litellm",
                name="Fake",
                base_url=base_url,
                api_key_enc=encrypt(
                    crypto_key,
                    INSTANCE_KEY.encode(),
                    aad=b"provider-instance:" + INSTANCE_ID.encode(),
                ),
                created_by=None,
                now_ms=now,
            )
            await models_repo.insert_for_instance(
                session,
                id=MODEL_ID,
                name="fake-chat",
                model_type="chat",
                instance_id=INSTANCE_ID,
                max_tokens=8192,
                dimension=None,
                extra=None,
                created_by=None,
                now_ms=now,
            )
        registry = ModelRegistry(sessionmaker, fresh_db, FrozenClock(), SeqIdGenerator())
        ref = await registry.resolve("fake-chat", "chat")
        assert ref.base_url == base_url == fresh_db.llm_base_url
        assert ref.api_key is not None
        assert ref.api_key.get_secret_value() == INSTANCE_KEY
        gateway = OpenAIGateway(fresh_db)
        try:
            result = await gateway.chat(ref, QUESTION)
        finally:
            await gateway.aclose()
        assert result.text == ANSWER
    finally:
        await engine.dispose()
