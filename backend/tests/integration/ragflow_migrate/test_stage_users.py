"""Testy etapu `users` migracji RAGFlow→WD (brief T4, kontrakt §3 i §4)."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote, urlsplit

import pymysql
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AuthenticationFailed
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock
from app.services.auth import AccountDisabled, AuthService
from app.services.auth_ratelimit import LoginGuard
from app.tools.ragflow_migrate import stages
from app.tools.ragflow_migrate.runner import plan_all, run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageInventory, StageResult
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

U1_ID = "b0a1c2d3e4f5061728394a5b6c7d8e91"
U2_ID = "b0a1c2d3e4f5061728394a5b6c7d8e92"
U3_ID = "b0a1c2d3e4f5061728394a5b6c7d8e93"
U1_EMAIL = "admin@rf.test"
U2_EMAIL = "alice@rf.test"
U3_EMAIL = "bob@rf.test"
T1_ID = U1_ID
T2_ID = U2_ID
T3_ID = U3_ID
U1_LAST_LOGIN_MS = 1759305600000  # `last_login_time` = `create_time` u1 (oś czasu README §3, UTC)
SOURCE_USERS = 3
SOURCE_MEMBERSHIPS = 2
NEW_USER_ID = "b0a1c2d3e4f5061728394a5b6c7d8e94"
ORPHAN_TENANT_ID = "b0a1c2d3e4f5061728394a5b6c7d8e95"
UPPERCASE_ADMIN_EMAIL = "ADMIN@rf.test"
SAFE_WRONG_PASSWORD = "wrong-fixture-pw"  # noqa: S105 — atrapa w teście, nie sekret
LOGGER_IP = "1.1.1.1"


@contextmanager
def _source_writer(dsn: str) -> Iterator[pymysql.connections.Connection]:
    """Zapisywalne połączenie ze źródłem (sesja `Source` jest READ ONLY) — na modyfikacje testu."""
    parts = urlsplit(dsn)
    conn = pymysql.connect(
        host=parts.hostname,
        port=parts.port or 3306,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        database=unquote(parts.path.lstrip("/")),
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


async def _scalar(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> Any:
    """Pojedyncza wartość z bazy WD (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return result.scalar_one()


async def _ids(sm: async_sessionmaker[AsyncSession]) -> set[str]:
    """Zbiór id w `users`."""
    async with sm() as session:
        result = await session.execute(text("SELECT id FROM users"))
        return {str(row) for row in result.scalars().all()}


async def _select_one(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any]
) -> tuple[Any, ...]:
    """Pierwszy wiersz jako krotka (wielokolumnowe asercje)."""
    async with sm() as session:
        result = await session.execute(text(sql), params)
        return tuple(result.first() or ())


def _run(source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any) -> Any:
    """`run_all(only=["users"])` — wspólny skrót testów etapu."""
    return run_all(source, wd_db.sm, ctx, only=["users"], **kwargs)


async def _migrate(source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any) -> StageResult:
    """Bieg etapu i jego wynik (jedyny etap w `only`)."""
    results = await _run(source, wd_db, ctx, **kwargs)
    assert [result.stage for result in results] == ["users"]
    return results[0]


def _auth_service(wd_db: WdDb) -> AuthService:
    """AuthService na bazie WD testu; sekrety generowane w teście (jak `tests/integration/auth`)."""
    clock = SystemClock()
    settings = wd_db.settings.model_copy(
        update={"secret_key": SecretStr("s" * 48), "crypto_key": SecretStr("ab" * 32)}
    )
    return AuthService(
        wd_db.sm, settings, clock, UuidV7Generator(), LoginGuard("100/min", clock, wd_db.sm)
    )


async def test_run_migrates_users_with_source_ids(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) `run` tworzy 3 użytkowników, zachowując id źródła 1:1."""
    result = await _migrate(source, wd_db, run_ctx)
    assert result.created == SOURCE_USERS
    assert result.updated == 0
    assert result.skipped == 0
    assert result.source_count == SOURCE_USERS
    assert result.target_count == SOURCE_USERS
    assert await _ids(wd_db.sm) == {U1_ID, U2_ID, U3_ID}
    assert run_ctx.shared["user_ids"] == {U1_ID, U2_ID, U3_ID}


async def test_run_preserves_columns_from_contract(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Kolizje pól: `is_active` z `status='0'`, hash hasła bez zmian, `last_login_time` w ms."""
    await _migrate(source, wd_db, run_ctx)
    flags = await _select_one(
        wd_db.sm, "SELECT is_active, is_superuser FROM users WHERE id = :id", {"id": U1_ID}
    )
    assert flags == (1, 1)
    assert await _scalar(wd_db.sm, "SELECT is_active FROM users WHERE id = :id", {"id": U3_ID}) == 0
    hash_u1 = await _scalar(
        wd_db.sm, "SELECT password_hash FROM users WHERE id = :id", {"id": U1_ID}
    )
    hash_u2 = await _scalar(
        wd_db.sm, "SELECT password_hash FROM users WHERE id = :id", {"id": U2_ID}
    )
    assert str(hash_u1).startswith("pbkdf2:sha256:600000$")
    assert str(hash_u2).startswith("scrypt:32768:8:1$")
    assert (
        await _scalar(wd_db.sm, "SELECT last_login_time FROM users WHERE id = :id", {"id": U1_ID})
        == U1_LAST_LOGIN_MS
    )
    assert (
        await _scalar(wd_db.sm, "SELECT last_login_time FROM users WHERE id = :id", {"id": U3_ID})
        is None
    )


async def test_second_run_is_idempotent(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(b) Drugi bieg: nic nowego, nic zmienionego, wszystko pominięte, liczba wierszy bez zmian."""
    await _migrate(source, wd_db, run_ctx)
    before = await _scalar(wd_db.sm, "SELECT COUNT(*) FROM users")
    second = await _migrate(source, wd_db, run_ctx)
    assert (second.created, second.updated, second.skipped) == (0, 0, SOURCE_USERS)
    assert second.source_count == SOURCE_USERS
    assert second.target_count == SOURCE_USERS
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM users") == before


async def test_dry_run_writes_nothing(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(c) `dry_run=True`: raport liczy wiersze, ale po biegu `users` jest pusty (rollback)."""
    result = await _migrate(source, wd_db, run_ctx, dry_run=True)
    assert result.created == SOURCE_USERS
    assert result.target_count == SOURCE_USERS
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM users") == 0


async def test_source_is_untouched(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(d) Liczniki `user`, `tenant` i `user_tenant` w źródle są identyczne przed i po biegu."""
    before = {table: source.count(table) for table in ("user", "tenant", "user_tenant")}
    await _migrate(source, wd_db, run_ctx)
    after = {table: source.count(table) for table in ("user", "tenant", "user_tenant")}
    assert after == before


async def test_login_with_migrated_passwords(
    source: Source, wd_db: WdDb, run_ctx: RunContext, expectations: dict[str, Any]
) -> None:
    """(e) Hasła werkzeug (pbkdf2 i scrypt) logują się po migracji; złe hasło i nieaktywny nie."""
    await _migrate(source, wd_db, run_ctx)
    auth = _auth_service(wd_db)
    users = expectations["users"]
    admin = await auth.login_password(
        U1_EMAIL, users[U1_EMAIL]["password"], ip=LOGGER_IP, user_agent="ua"
    )
    assert admin.user.id == U1_ID
    alice = await auth.login_password(
        U2_EMAIL, users[U2_EMAIL]["password"], ip=LOGGER_IP, user_agent="ua"
    )
    assert alice.user.id == U2_ID
    with pytest.raises(AuthenticationFailed):
        await auth.login_password(U1_EMAIL, SAFE_WRONG_PASSWORD, ip=LOGGER_IP, user_agent="ua")
    with pytest.raises(AccountDisabled):
        await auth.login_password(
            U3_EMAIL, users[U3_EMAIL]["password"], ip=LOGGER_IP, user_agent="ua"
        )


async def test_plan_writes_nothing_and_reports_tenants(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) `plan` nie pisze (`users` puste) i raportuje `tenant_defaults` t1/t2."""
    inventories = plan_all(source, run_ctx, only=["users"])
    assert [inventory.stage for inventory in inventories] == ["users"]
    inventory = inventories[0]
    assert inventory.source_counts == {
        "user": SOURCE_USERS,
        "tenant": SOURCE_USERS,
        "user_tenant": SOURCE_MEMBERSHIPS,
    }
    assert inventory.not_migrated == {}
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM users") == 0
    assert _issue_ids(inventory, "tenant_defaults") == {T1_ID, T2_ID}
    assert _issue_ids(inventory, "membership") == {T1_ID}
    assert _issue_ids(inventory, "email_collision") == set()
    assert _issue_ids(inventory, "tenant_without_user") == set()


def _issue_ids(inventory: StageInventory, code: str) -> set[str]:
    """Zbiór id uwag o danym kodzie."""
    return {row_id for issue in inventory.issues if issue.code == code for row_id in issue.ids}


async def test_email_collision_is_critical_and_row_is_not_written(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(g) Duplikat e-mailu (inna wielkość liter) → `critical email_collision` i brak zapisu."""
    with _source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO `user` (`id`, `create_time`, `create_date`, `update_time`,"
            " `update_date`, `nickname`, `password`, `email`, `language`, `is_authenticated`,"
            " `is_active`, `is_anonymous`, `status`) VALUES (%s, %s, NOW(), %s, NOW(), %s, %s,"
            " %s, %s, '1', '1', '0', '1')",
            (
                NEW_USER_ID,
                U1_LAST_LOGIN_MS,
                U1_LAST_LOGIN_MS,
                "twin",
                "pbkdf2:sha256:600000$e46aPbkdf2Salt01$2c894225cd675d1a03a194424b017ab951655d3323261fdce4ffc0662fb8bde3",
                UPPERCASE_ADMIN_EMAIL,
                "English",
            ),
        )
    result = await _migrate(source, wd_db, run_ctx)
    collisions = [issue for issue in result.issues if issue.code == "email_collision"]
    assert len(collisions) == 1
    assert collisions[0].severity == "critical"
    assert set(collisions[0].ids) == {U1_ID, NEW_USER_ID}
    assert result.source_count == SOURCE_USERS + 1
    # Cztery wiersze źródła: u1 i nowy twin kolidują (skipped), u2 i u3 zapisane (created).
    assert (result.created, result.updated, result.skipped) == (2, 0, 2)
    assert result.target_count == SOURCE_USERS - 1
    # Issue `critical` wstrzymuje commit całego biegu (kontrakt §2 runnera) — cel pusty.
    assert await _scalar(wd_db.sm, "SELECT COUNT(*) FROM users") == 0
    # Sam etap też nie pisze kolidujących wierszy: przy ręcznym commicie w celu są tylko u2 i u3.
    async with wd_db.sm() as session:
        direct = await stages.STAGES["users"].run(source, session, run_ctx)
        await session.commit()
    assert direct.created == SOURCE_USERS - 1
    assert await _ids(wd_db.sm) == {U2_ID, U3_ID}


async def test_plan_reports_tenant_without_user(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """`tenant` bez `user` o tym samym id → `warning tenant_without_user` i brak zapisu."""
    with _source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO `tenant` (`id`, `create_time`, `create_date`, `update_time`,"
            " `update_date`, `name`, `llm_id`, `embd_id`, `asr_id`, `img2txt_id`, `rerank_id`,"
            " `parser_ids`, `credit`, `status`) VALUES (%s, %s, NOW(), %s, NOW(), 'Orphan',"
            " '', '', '', '', '', '', 0, '1')",
            (ORPHAN_TENANT_ID, U1_LAST_LOGIN_MS, U1_LAST_LOGIN_MS),
        )
    inventory = plan_all(source, run_ctx, only=["users"])[0]
    warnings = [issue for issue in inventory.issues if issue.code == "tenant_without_user"]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert warnings[0].ids == [ORPHAN_TENANT_ID]
    assert _issue_ids(inventory, "tenant_defaults") == {T1_ID, T2_ID}
    result = await _migrate(source, wd_db, run_ctx)
    assert result.issues == inventory.issues
    assert await _ids(wd_db.sm) == {U1_ID, U2_ID, U3_ID}
