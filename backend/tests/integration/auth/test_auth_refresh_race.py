"""Współbieżny refresh: przeplot wymuszony barierą — dokładnie jeden zwycięzca (kontrakt C4)."""

import asyncio
import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import Unauthorized
from app.db.repositories import refresh_sessions as sessions_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.services.auth import AuthService, SessionTokens
from app.services.auth_ratelimit import LoginGuard
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

pytestmark = pytest.mark.db

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
LOGGER_NAME = "app.services.auth"


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def users_svc(
    sm: async_sessionmaker[AsyncSession], auth_settings: Settings, clock: FrozenClock
) -> UserService:
    return UserService(sm, auth_settings, clock, SeqIdGenerator())


@pytest.fixture
def auth(
    sm: async_sessionmaker[AsyncSession], auth_settings: Settings, clock: FrozenClock
) -> AuthService:
    """AuthService wg briefu: LoginGuard 100/min (limity testujemy osobno)."""
    return AuthService(sm, auth_settings, clock, SeqIdGenerator(), LoginGuard("100/min", clock, sm))


@pytest.fixture
async def jan(users_svc: UserService) -> users_repo.UserRow:
    return await users_svc.create(email="jan@x.pl", password=PASSWORD)


async def _scalar(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> object:
    """Pojedyncza wartość z bazy w świeżej transakcji (commit utrwalony)."""
    async with transaction(sm) as session:
        result = await session.execute(text(sql), params)
        return result.scalar_one()


async def test_concurrent_refresh_single_winner_revokes_family(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await auth.login_password("jan@x.pl", PASSWORD, ip="1.1.1.1", user_agent="ua")
    barrier = asyncio.Barrier(2)
    original = sessions_repo.get_by_hash

    async def gated(
        session: AsyncSession, token_hash: str
    ) -> sessions_repo.RefreshSessionRow | None:
        row = await original(session, token_hash)
        await barrier.wait()  # oba refreshy odczytują wiersz, zanim cokolwiek pójdzie dalej
        return row

    monkeypatch.setattr(sessions_repo, "get_by_hash", gated)
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        async with asyncio.timeout(30):
            results = await asyncio.gather(
                auth.refresh(t.refresh_token, ip="1.1.1.1", user_agent="ua"),
                auth.refresh(t.refresh_token, ip="1.1.1.1", user_agent="ua"),
                return_exceptions=True,
            )
    monkeypatch.undo()
    tokens = [r for r in results if isinstance(r, SessionTokens)]
    unauthorized = [r for r in results if isinstance(r, Unauthorized)]
    if len(tokens) + len(unauthorized) != len(results):
        raise AssertionError(f"nieoczekiwany wynik: {results!r}")
    assert len(tokens) == 1  # dokładnie jeden zwycięzca wyścigu
    assert len(unauthorized) == 1  # przegrany dostaje Unauthorized (reuse)
    # Cała rodzina unieważniona — także nowo wydana sesja zwycięzcy (odczyt po commitach).
    active = await _scalar(
        sm,
        "SELECT COUNT(*) FROM refresh_sessions WHERE user_id = :uid AND revoked_at IS NULL",
        uid=jan.id,
    )
    assert active == 0
    total = await _scalar(
        sm, "SELECT COUNT(*) FROM refresh_sessions WHERE user_id = :uid", uid=jan.id
    )
    assert total == 2  # noqa: PLR2004 — stara + jedna nowa sesja
    reused = [
        rec for rec in caplog.records if getattr(rec, "event", None) == "refresh_reuse_detected"
    ]
    assert len(reused) == 1
    assert reused[0].user_id == jan.id
    # Token zwycięzcy już nie działa (rodzina unieważniona przez przegranego).
    winner = tokens[0]
    with pytest.raises(Unauthorized):
        await auth.refresh(winner.refresh_token, ip="1.1.1.1", user_agent="ua")
