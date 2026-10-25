"""Fixture'y i pomocnicy testów repozytorium integracji (brief T3/T6, kontrakt C1/C2/C8).

Wzorzec: tests/integration/chat/conftest.py i tests/integration/datasets/conftest.py.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.container import Container
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import integrations as integrations_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.config import IntegrationsConfig
from app.integrations.engine import SyncEngine
from tests.fakes.clock import FrozenClock
from tests.fakes.integrations import FakeConnector, fake_load_config
from tests.integration.db.helpers import alembic_cfg

TIME_MS = 1790157600000  # stały zegar testów

DEFAULT_PARSER_CONFIG: dict = {"chunk_token_num": 128, "delimiter": "\n"}


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Rejestr konektorów jest globalny per proces — czyścimy przed i po teście.

    Wzorzec `tests/integration/api/test_integrations_setup.py`; bez tego testy tego pakietu
    zależą od kolejności w procesie: `create_app` (użyty w innym teście tego workera) rejestruje
    `sharepoint` globalnie (DEC-074 p. 3), więc `test_create_without_registered_connector`
    padał pod xdist, gdy trafił na workera po teście budującym aplikację (E5-H7/T1).
    """
    registry.clear()
    yield
    registry.clear()


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def seed_dataset_and_user(
    sm: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    """Wstawia users i datasets przez repozytoria; zwraca ``(owner_id, dataset_id)``."""
    user_id = uuid.uuid4().hex
    dataset_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await users_repo.insert(
            session,
            user_id=user_id,
            email=f"{user_id[:12]}@example.com",
            nickname="seed",
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=False,
            is_service=False,
            now_ms=TIME_MS,
        )
        await datasets_repo.insert(
            session,
            id=dataset_id,
            tenant_id=user_id,
            created_by=user_id,
            name="Korpus",
            description=None,
            avatar=None,
            language="Polish",
            embedding_model="fake-embed-1024",
            embedding_dim=1024,
            permission="me",
            chunk_method="naive",
            parser_config=DEFAULT_PARSER_CONFIG,
            now_ms=TIME_MS,
        )
    return user_id, dataset_id


async def make_integration(  # noqa: PLR0913 — skrót testowy z opcjonalnymi kolumnami
    sm: async_sessionmaker[AsyncSession],
    *,
    dataset_id: str | None = None,
    owner_id: str | None = None,
    now_ms: int = TIME_MS,
    name: str = "SP test",
    config: dict | None = None,
    **kwargs: object,
) -> int:
    """Wstawia integrację przez repo; bez dataset_id/owner_id tworzy je razem z userem."""
    if dataset_id is None or owner_id is None:
        owner_id, dataset_id = await seed_dataset_and_user(sm)
    async with transaction(sm) as session:
        return await integrations_repo.insert_integration(
            session,
            type="fake",
            name=name,
            dataset_id=dataset_id,
            owner_id=owner_id,
            config=config if config is not None else {"site_url": "https://example.test"},
            now_ms=now_ms,
            **kwargs,
        )


@pytest.fixture
def clock() -> FrozenClock:
    """Zegar zamrożony na stałym czasie testów (brief T6; wzorzec test_audit.py)."""
    return FrozenClock(TIME_MS)


@pytest.fixture
async def container(
    migrated_db: Settings, tmp_path: Path, clock: FrozenClock
) -> AsyncIterator[Container]:
    """Kontener po ``start()`` na zmigrowanej bazie, storage w ``tmp_path`` (brief T6).

    ``start()`` tworzy engine/sessionmaker (bez połączenia), usługi i bramkę LLM; po teście
    ``aclose()`` zamyka zasoby.
    """
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}), clock=clock
    )
    await instance.start()
    yield instance
    await instance.aclose()


@pytest.fixture
def fake() -> FakeConnector:
    """Skryptowany konektor testowy (kontrakt C8) — jeszcze nie w rejestrze."""
    return FakeConnector()


@pytest.fixture
def registered_fake(fake: FakeConnector) -> Iterator[FakeConnector]:
    """Rejestruje ``FakeConnector`` pod typem ``fake``; po teście czyści rejestr (brief T6)."""
    registry.register("fake", fake, fake_load_config)
    yield fake
    registry.clear()


@pytest.fixture
def engine(container: Container) -> SyncEngine:
    """Silnik integracji na kontenerze testowym z domyślną konfiguracją (brief T6)."""
    return SyncEngine(container, IntegrationsConfig())
