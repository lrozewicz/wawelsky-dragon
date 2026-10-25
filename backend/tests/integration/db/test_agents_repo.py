"""Testy repozytoriów `agents` / `agent_sessions` na MariaDB (CONTRACT E6-3f §C2, K2 §6)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import agent_sessions as sessions_repo
from app.db.repositories import agents as repo
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME, TIME_MS

pytestmark = pytest.mark.db

LATER = TIME_MS + 1000
AGENT_A = "a" * 32
AGENT_B = "b" * 32
SESSION_A = "c" * 32
SESSION_B = "d" * 32


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


async def _seed_user(sm: async_sessionmaker[AsyncSession], *, nickname: str = "seed") -> str:
    """Wstawia `users`; zwraca id (e-mail `{id}@example.com`)."""
    user_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :email, :nickname, :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": user_id,
                "email": f"{user_id}@example.com",
                "nickname": nickname,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
    return user_id


async def _insert_agent(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    sm: async_sessionmaker[AsyncSession],
    tenant_id: str,
    *,
    id: str = AGENT_A,
    title: str = "Agent",
    dsl: dict | None = None,
    unsupported_components: list[str] | None = None,
    now_ms: int = TIME_MS,
) -> repo.AgentRow:
    """Wstawia agenta i zwraca `repo.get_by_id`."""
    async with transaction(sm) as session:
        await repo.insert(
            session,
            id=id,
            tenant_id=tenant_id,
            created_by=tenant_id,
            title=title,
            description="opis",
            avatar=None,
            permission="me",
            canvas_category="agent_canvas",
            tags="",
            dsl={"graph": {}} if dsl is None else dsl,
            unsupported_components=unsupported_components,
            now_ms=now_ms,
        )
        row = await repo.get_by_id(session, id)
    assert row is not None
    return row


async def _insert_session(
    sm: async_sessionmaker[AsyncSession],
    agent_id: str,
    user_id: str,
    *,
    id: str = SESSION_A,
    now_ms: int = TIME_MS,
) -> None:
    """Wstawia sesję agenta do bazy."""
    async with transaction(sm) as session:
        await sessions_repo.insert(
            session,
            id=id,
            agent_id=agent_id,
            user_id=user_id,
            owner_id=None,
            name="Rozmowa",
            source="agent",
            messages=[{"role": "user", "content": "hej"}],
            reference=[],
            dsl={"graph": {}},
            tokens=3,
            duration=1.5,
            round=1,
            errors=None,
            now_ms=now_ms,
        )


async def _count(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> int:
    """Liczba wierszy wg surowego SELECT (do kaskady/istnienia)."""
    async with transaction(sm) as session:
        return int((await session.execute(text(sql), params)).scalar_one())


async def test_insert_and_get_round_trip(sm: async_sessionmaker[AsyncSession]) -> None:
    """`insert` + `get_by_id`: pola i zdekodowany JSON; brak dla nieznanego id (§C2)."""
    owner = await _seed_user(sm)
    row = await _insert_agent(sm, owner, dsl={"graph": {"nodes": []}}, unsupported_components=["x"])
    assert (row.tenant_id, row.created_by, row.title) == (owner, owner, "Agent")
    assert row.dsl == {"graph": {"nodes": []}}
    assert row.unsupported_components == ["x"]
    assert (row.permission, row.canvas_category, row.tags) == ("me", "agent_canvas", "")
    assert (row.create_time, row.update_time) == (TIME_MS, TIME_MS)
    async with transaction(sm) as session:
        assert await repo.get_by_id(session, uuid.uuid4().hex) is None


async def test_list_by_tenant_order(sm: async_sessionmaker[AsyncSession]) -> None:
    """`list_by_tenant`: tylko agenci właściciela, `update_time` DESC (§C2)."""
    owner = await _seed_user(sm)
    other = await _seed_user(sm, nickname="obcy")
    await _insert_agent(sm, owner, id=AGENT_A, title="Starszy", now_ms=TIME_MS)
    await _insert_agent(sm, owner, id=AGENT_B, title="Nowszy", now_ms=LATER)
    await _insert_agent(sm, other, id="e" * 32, title="Obcy", now_ms=LATER)
    async with transaction(sm) as session:
        rows = await repo.list_by_tenant(session, owner)
    assert [r.id for r in rows] == [AGENT_B, AGENT_A]


async def test_unsupported_components_null_round_trips(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`unsupported_components` NULL → None po odczycie (§C2)."""
    owner = await _seed_user(sm)
    row = await _insert_agent(sm, owner, unsupported_components=None)
    assert row.unsupported_components is None


async def test_duplicate_tenant_title_raises(sm: async_sessionmaker[AsyncSession]) -> None:
    """UNIQUE (tenant_id, title): duplikat → IntegrityError (§C2)."""
    owner = await _seed_user(sm)
    await _insert_agent(sm, owner, title="Ten sam")
    with pytest.raises(IntegrityError):
        async with transaction(sm) as session:
            await repo.insert(
                session,
                id=AGENT_B,
                tenant_id=owner,
                created_by=owner,
                title="Ten sam",
                description=None,
                avatar=None,
                permission="me",
                canvas_category="agent_canvas",
                tags="",
                dsl={"graph": {}},
                unsupported_components=None,
                now_ms=TIME_MS,
            )


async def test_update_agent(sm: async_sessionmaker[AsyncSession]) -> None:
    """`update` podmienia pola i podbija czasy (§C2)."""
    owner = await _seed_user(sm)
    await _insert_agent(sm, owner)
    async with transaction(sm) as session:
        await repo.update(
            session,
            agent_id=AGENT_A,
            title="Nowy tytuł",
            description=None,
            avatar="ikona",
            permission="team",
            canvas_category="agent_canvas",
            tags="a,b",
            dsl={"graph": {"nodes": [1]}},
            unsupported_components=None,
            now_ms=LATER,
        )
        row = await repo.get_by_id(session, AGENT_A)
    assert row is not None
    assert (row.title, row.permission, row.tags) == ("Nowy tytuł", "team", "a,b")
    assert row.dsl == {"graph": {"nodes": [1]}}
    assert (row.create_time, row.update_time) == (TIME_MS, LATER)


async def test_delete_agent(sm: async_sessionmaker[AsyncSession]) -> None:
    """`delete_by_id` zwraca liczbę wierszy, agent znika (§C2)."""
    owner = await _seed_user(sm)
    await _insert_agent(sm, owner)
    async with transaction(sm) as session:
        assert await repo.delete_by_id(session, AGENT_A) == 1
        assert await repo.get_by_id(session, AGENT_A) is None
        assert await repo.delete_by_id(session, AGENT_A) == 0


async def test_session_insert_and_get(sm: async_sessionmaker[AsyncSession]) -> None:
    """`agent_sessions.insert` + `get_by_id`: pola i zdekodowany JSON (§C2)."""
    owner = await _seed_user(sm)
    await _insert_agent(sm, owner)
    await _insert_session(sm, AGENT_A, owner)
    async with transaction(sm) as session:
        row = await sessions_repo.get_by_id(session, SESSION_A)
    assert row is not None
    assert (row.agent_id, row.user_id, row.name, row.source) == (AGENT_A, owner, "Rozmowa", "agent")
    assert row.messages == [{"role": "user", "content": "hej"}]
    assert (row.reference, row.dsl) == ([], {"graph": {}})
    assert (row.tokens, row.duration, row.round) == (3, 1.5, 1)
    assert row.owner_id is None


async def test_list_by_agent_order(sm: async_sessionmaker[AsyncSession]) -> None:
    """`list_by_agent`: sesje agenta/ucznia, `update_time` DESC, obcy user pominięty (§C2)."""
    owner = await _seed_user(sm)
    other = await _seed_user(sm, nickname="obcy")
    await _insert_agent(sm, owner)
    await _insert_session(sm, AGENT_A, owner, id=SESSION_A, now_ms=TIME_MS)
    await _insert_session(sm, AGENT_A, owner, id=SESSION_B, now_ms=LATER)
    await _insert_session(sm, AGENT_A, other, id="f" * 32, now_ms=LATER)
    async with transaction(sm) as session:
        rows = await sessions_repo.list_by_agent(session, AGENT_A, owner)
    assert [r.id for r in rows] == [SESSION_B, SESSION_A]


async def test_session_update(sm: async_sessionmaker[AsyncSession]) -> None:
    """`agent_sessions.update` podmienia pola i podbija czasy (§C2)."""
    owner = await _seed_user(sm)
    await _insert_agent(sm, owner)
    await _insert_session(sm, AGENT_A, owner)
    async with transaction(sm) as session:
        await sessions_repo.update(
            session,
            session_id=SESSION_A,
            name="Inna",
            source="agent",
            messages=[{"role": "user", "content": "x"}],
            reference=[{"k": "v"}],
            dsl={"graph": {"nodes": []}},
            tokens=9,
            duration=2.0,
            round=2,
            errors="warn",
            now_ms=LATER,
        )
        row = await sessions_repo.get_by_id(session, SESSION_A)
    assert row is not None
    assert (row.name, row.tokens, row.round, row.errors) == ("Inna", 9, 2, "warn")
    assert row.reference == [{"k": "v"}]
    assert (row.create_time, row.update_time) == (TIME_MS, LATER)


async def test_delete_agent_cascades_sessions(sm: async_sessionmaker[AsyncSession]) -> None:
    """ON DELETE CASCADE: usunięcie agenta zabiera jego sesje (§C2)."""
    owner = await _seed_user(sm)
    await _insert_agent(sm, owner)
    await _insert_session(sm, AGENT_A, owner)
    async with transaction(sm) as session:
        await repo.delete_by_id(session, AGENT_A)
        assert await sessions_repo.get_by_id(session, SESSION_A) is None
    remaining = await _count(
        sm, "SELECT COUNT(*) FROM agent_sessions WHERE agent_id = :a", a=AGENT_A
    )
    assert remaining == 0


async def test_delete_session(sm: async_sessionmaker[AsyncSession]) -> None:
    """`agent_sessions.delete_by_id` zwraca liczbę wierszy (§C2)."""
    owner = await _seed_user(sm)
    await _insert_agent(sm, owner)
    await _insert_session(sm, AGENT_A, owner)
    async with transaction(sm) as session:
        assert await sessions_repo.delete_by_id(session, SESSION_A) == 1
        assert await sessions_repo.get_by_id(session, SESSION_A) is None
