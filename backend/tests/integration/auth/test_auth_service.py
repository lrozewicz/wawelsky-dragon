"""Testy AuthService (brief T4b, kontrakt C8) — login, sesje refresh, logout, authenticate."""

import logging

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import (
    AuthenticationFailed,
    OperationNotAllowed,
    RateLimited,
    Unauthorized,
)
from app.db.repositories import refresh_sessions as sessions_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.api_keys import ApiKeyService
from app.services.auth import AccountDisabled, AuthService
from app.services.auth_ratelimit import LoginGuard
from app.services.auth_tokens import decode_token, issue_token, sha256_hex
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

pytestmark = pytest.mark.db

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
BAD_PASSWORD = "Wrong-pass1"  # noqa: S105 — celowa atrapa hasła w teście
ANY_PASSWORD = "x"  # noqa: S105 — celowa atrapa hasła w teście
LOGGER_NAME = "app.services.auth"
ACCESS_TTL_S = 900  # access_token_ttl_min=15
REFRESH_TTL_S = 14 * 86400  # refresh_token_ttl_days=14
REFRESH_TTL_MS = REFRESH_TTL_S * 1000


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


async def _login(auth: AuthService, email: str = "jan@x.pl", password: str = PASSWORD):
    return await auth.login_password(email, password, ip="1.1.1.1", user_agent="ua")


async def _scalar(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> object:
    """Pojedyncza wartość z bazy w świeżej transakcji (commit utrwalony)."""
    async with transaction(sm) as session:
        result = await session.execute(text(sql), params)
        return result.scalar_one()


async def _row_by_hash(
    sm: async_sessionmaker[AsyncSession], refresh_token: str
) -> sessions_repo.RefreshSessionRow | None:
    async with transaction(sm) as session:
        return await sessions_repo.get_by_hash(session, sha256_hex(refresh_token))


# --- login_password ------------------------------------------------------------


async def test_login_password_success(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    # E-mail jak w briefie: mieszana wielkość liter, konto znalezione (lookup lowercase).
    t = await auth.login_password("Jan@x.pl", PASSWORD, ip="1.1.1.1", user_agent="ua")
    assert t.user.email == "jan@x.pl"
    assert t.expires_in == ACCESS_TTL_S
    assert t.refresh_max_age == REFRESH_TTL_S
    assert t.user.last_login_time == clock.now_ms()
    assert decode_token(auth_settings, clock.now_ms(), t.access_token).typ == "access"
    assert decode_token(auth_settings, clock.now_ms(), t.legacy_token).typ == "legacy"
    assert await _scalar(sm, "SELECT COUNT(*) FROM refresh_sessions") == 1


async def test_login_empty_email_is_unauthorized(auth: AuthService) -> None:
    for email in (None, ""):
        with pytest.raises(AuthenticationFailed, match=r"^Unauthorized!$"):
            await auth.login_password(email, ANY_PASSWORD, ip="1.1.1.1", user_agent="ua")


async def test_login_unknown_email(auth: AuthService) -> None:
    with pytest.raises(AuthenticationFailed, match=r"^Email: nikt@x\.pl is not registered!$"):
        await _login(auth, email="nikt@x.pl", password=ANY_PASSWORD)


async def test_login_bad_password(auth: AuthService, jan: users_repo.UserRow) -> None:
    with pytest.raises(AuthenticationFailed, match=r"^Email and password do not match!$"):
        await _login(auth, password=BAD_PASSWORD)


async def test_login_disabled_account(
    users_svc: UserService, auth: AuthService, jan: users_repo.UserRow
) -> None:
    await users_svc.set_active(jan.id, False)
    with pytest.raises(AccountDisabled) as exc:
        await _login(auth)
    assert exc.value.message == "This account has been disabled, please contact the administrator!"
    assert exc.value.code == 403  # noqa: PLR2004 — dosłownie z briefu (upstream)


async def test_login_password_disabled(
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
    jan: users_repo.UserRow,
) -> None:
    settings = auth_settings.model_copy(update={"password_login_enabled": False})
    auth = AuthService(sm, settings, clock, SeqIdGenerator(), LoginGuard("100/min", clock, sm))
    with pytest.raises(OperationNotAllowed, match=r"^Password login is disabled!$"):
        await _login(auth)


async def test_login_rate_limited(
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
    jan: users_repo.UserRow,
) -> None:
    auth = AuthService(sm, auth_settings, clock, SeqIdGenerator(), LoginGuard("2/min", clock, sm))
    for _ in range(2):
        with pytest.raises(AuthenticationFailed):
            await _login(auth, password=BAD_PASSWORD)
    with pytest.raises(RateLimited):
        await _login(auth, password=BAD_PASSWORD)


async def test_lockout_hides_good_password(
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
    jan: users_repo.UserRow,
) -> None:
    """Po 10 porażkach dobre hasło daje ten sam komunikat (blokada bez ujawnienia, 07 §9)."""
    auth = AuthService(sm, auth_settings, clock, SeqIdGenerator(), LoginGuard("100/min", clock, sm))
    for _ in range(10):
        with pytest.raises(AuthenticationFailed):
            await _login(auth, password=BAD_PASSWORD)
    with pytest.raises(AuthenticationFailed, match=r"^Email and password do not match!$"):
        await _login(auth)


async def test_login_logs_success_and_failure_without_secrets(
    auth: AuthService,
    jan: users_repo.UserRow,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Logi wg wymagań briefu p. 3: login_success (info) i login_failure (warning, reason); B8."""
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with pytest.raises(AuthenticationFailed):
            await _login(auth, password=BAD_PASSWORD)
        with pytest.raises(AuthenticationFailed):
            await _login(auth, email="nikt@x.pl", password=ANY_PASSWORD)
        await _login(auth)
    failures = [rec for rec in caplog.records if getattr(rec, "event", None) == "login_failure"]
    assert [getattr(rec, "reason", None) for rec in failures] == [
        "bad_password",
        "not_registered",
    ]
    successes = [rec for rec in caplog.records if getattr(rec, "event", None) == "login_success"]
    assert len(successes) == 1
    assert getattr(successes[0], "user_id", None) == jan.id
    assert PASSWORD not in caplog.text  # nigdy hasło ani token (B8)


async def test_login_rehashes_legacy_hash(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Konto z hashem pbkdf2 (RAGFlow): login przelicza hash na argon2id (07 §12 p. 4a)."""
    legacy_hash = (
        "pbkdf2:sha256:1000$5puxVbVe8jVXvmXN$"
        "2eb391738a99e70a6de98be41da2410de93f5f1010c118622579afa8de6b798d"
    )
    async with transaction(sm) as session:
        await users_repo.update_fields(session, jan.id, {"password_hash": legacy_hash}, 0)
    t = await _login(auth)
    assert t.user.email == "jan@x.pl"
    stored = await _scalar(sm, "SELECT password_hash FROM users WHERE id = :id", id=jan.id)
    assert str(stored).startswith("$argon2id$")


# --- refresh -------------------------------------------------------------------


async def test_refresh_rotates_token_in_same_family(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    t = await _login(auth)
    old_token = t.refresh_token
    r = await auth.refresh(old_token, ip="1.1.1.1", user_agent="ua")
    assert r.access_token != t.access_token
    assert r.refresh_token != old_token
    old_row = await _row_by_hash(sm, old_token)
    assert old_row is not None
    assert old_row.revoked_at is not None
    new_row = await _row_by_hash(sm, r.refresh_token)
    assert new_row is not None
    assert new_row.revoked_at is None
    assert new_row.family_id == old_row.family_id
    assert new_row.id != old_row.id


async def test_refresh_reuse_revokes_family(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    t = await _login(auth)
    r = await auth.refresh(t.refresh_token, ip="1.1.1.1", user_agent="ua")
    with (
        caplog.at_level(logging.WARNING, logger=LOGGER_NAME),
        pytest.raises(Unauthorized),
    ):
        await auth.refresh(t.refresh_token, ip="1.1.1.1", user_agent="ua")
    reused = [
        rec for rec in caplog.records if getattr(rec, "event", None) == "refresh_reuse_detected"
    ]
    assert len(reused) == 1
    assert reused[0].user_id == jan.id
    family_id = reused[0].family_id
    # Cała rodzina unieważniona, commit utrwalony (odczyt w nowej transakcji).
    active = await _scalar(
        sm,
        "SELECT COUNT(*) FROM refresh_sessions WHERE family_id = :family_id AND revoked_at IS NULL",
        family_id=family_id,
    )
    assert active == 0
    # Obrócony token z tej rodziny też już nie działa.
    with pytest.raises(Unauthorized):
        await auth.refresh(r.refresh_token, ip="1.1.1.1", user_agent="ua")


async def test_refresh_none_or_unknown_is_unauthorized(auth: AuthService) -> None:
    for token in (None, "nieznany"):
        with pytest.raises(Unauthorized):
            await auth.refresh(token, ip="1.1.1.1", user_agent="ua")


async def test_refresh_expired_is_unauthorized(
    auth: AuthService, jan: users_repo.UserRow, clock: FrozenClock
) -> None:
    t = await _login(auth)
    clock.advance(REFRESH_TTL_MS)
    with pytest.raises(Unauthorized):
        await auth.refresh(t.refresh_token, ip="1.1.1.1", user_agent="ua")


# --- authenticate --------------------------------------------------------------


async def test_authenticate_jwt_access(auth: AuthService, jan: users_repo.UserRow) -> None:
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    assert p == Principal(
        user_id=jan.id, email="jan@x.pl", is_superuser=False, is_service=False, auth_kind="jwt"
    )
    assert p.api_key_id is None


async def test_authenticate_legacy_token(auth: AuthService, jan: users_repo.UserRow) -> None:
    t = await _login(auth)
    p = await auth.authenticate(t.legacy_token)
    assert p.auth_kind == "legacy_token"
    assert p.user_id == jan.id


# Scenariusz „Bearer ..." — nie dotyczy usługi (odcięcie „Bearer" robi trasa, brief: pomiń).


async def test_authenticate_expired_jwt(
    auth: AuthService, jan: users_repo.UserRow, clock: FrozenClock
) -> None:
    t = await _login(auth)
    clock.advance(ACCESS_TTL_S * 1000)
    with pytest.raises(Unauthorized):
        await auth.authenticate(t.access_token)


async def test_authenticate_wrong_signature(
    auth: AuthService,
    jan: users_repo.UserRow,
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    other_settings = auth_settings.model_copy(update={"secret_key": SecretStr("t" * 48)})
    forged = issue_token(
        other_settings,
        clock.now_ms(),
        user_id=jan.id,
        token_version=jan.token_version,
        typ="access",
        jti="f" * 32,
    )
    with pytest.raises(Unauthorized):
        await auth.authenticate(forged)


async def test_authenticate_bad_token_version(
    auth: AuthService, jan: users_repo.UserRow, sm: async_sessionmaker[AsyncSession]
) -> None:
    t = await _login(auth)
    async with transaction(sm) as session:
        await users_repo.bump_token_version(session, jan.id, 0)
    with pytest.raises(Unauthorized):
        await auth.authenticate(t.access_token)


async def test_authenticate_inactive_user(
    auth: AuthService, jan: users_repo.UserRow, users_svc: UserService
) -> None:
    t = await _login(auth)
    await users_svc.set_active(jan.id, False)
    with pytest.raises(Unauthorized):
        await auth.authenticate(t.access_token)


async def test_authenticate_api_key(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    keys = ApiKeyService(sm, auth_settings, clock, SeqIdGenerator())
    k = await keys.create(p)
    principal = await auth.authenticate(k.token)
    assert principal.auth_kind == "api_key"
    assert principal.api_key_id == k.id
    assert principal.user_id == jan.id
    last_used = await _scalar(sm, "SELECT last_used_at FROM api_keys WHERE id = :id", id=k.id)
    assert last_used == clock.now_ms()


async def test_api_key_touch_throttled(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    keys = ApiKeyService(sm, auth_settings, clock, SeqIdGenerator())
    k = await keys.create(p)
    await auth.authenticate(k.token)  # pierwszy dotyk: last_used_at = T
    clock.advance(30_000)
    await auth.authenticate(k.token)
    last_used = await _scalar(sm, "SELECT last_used_at FROM api_keys WHERE id = :id", id=k.id)
    assert last_used == clock.now_ms() - 30_000  # bez zmian (< API_KEY_TOUCH_MS)
    clock.advance(60_000)
    await auth.authenticate(k.token)
    last_used = await _scalar(sm, "SELECT last_used_at FROM api_keys WHERE id = :id", id=k.id)
    assert last_used == clock.now_ms()  # ≥ 60 s od poprzedniego → dotknięte


async def test_authenticate_api_key_with_future_expiry(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    """`expires_at` w przyszłości → Principal jak dla klucza bezterminowego (K14 §2 p. 1)."""
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    keys = ApiKeyService(sm, auth_settings, clock, SeqIdGenerator())
    k = await keys.create(p, expires_at=clock.now_ms() + 1)
    principal = await auth.authenticate(k.token)
    assert principal.auth_kind == "api_key"
    assert principal.api_key_id == k.id
    assert principal.user_id == jan.id


async def test_authenticate_expired_api_key_is_invalid_token(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    """`expires_at == now` i `< now` → Unauthorized identyczne jak dla nieistniejącego klucza."""
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    keys = ApiKeyService(sm, auth_settings, clock, SeqIdGenerator())
    at_now = await keys.create(p, expires_at=clock.now_ms())
    in_past = await keys.create(p, expires_at=clock.now_ms() - 1)
    with pytest.raises(Unauthorized) as unknown:
        await auth.authenticate("ragflow-nieznany")
    for token in (at_now.token, in_past.token):
        with pytest.raises(Unauthorized) as error:
            await auth.authenticate(token)
        assert error.value.message == unknown.value.message == "Invalid token"


async def test_expired_api_key_keeps_last_used_at_null(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    """Odrzucony klucz wygasły nie dotyka `last_used_at` (K14 §2 p. 3)."""
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    keys = ApiKeyService(sm, auth_settings, clock, SeqIdGenerator())
    k = await keys.create(p, expires_at=clock.now_ms() - 1)
    with pytest.raises(Unauthorized):
        await auth.authenticate(k.token)
    last_used = await _scalar(sm, "SELECT last_used_at FROM api_keys WHERE id = :id", id=k.id)
    assert last_used is None


async def test_authenticate_api_key_without_expiry(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    """`expires_at=None` działa jak dotąd (K14 §1: NULL = klucz bezterminowy)."""
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    keys = ApiKeyService(sm, auth_settings, clock, SeqIdGenerator())
    k = await keys.create(p)
    assert k.expires_at is None
    principal = await auth.authenticate(k.token)
    assert principal.api_key_id == k.id


async def test_authenticate_revoked_or_unknown_key(
    auth: AuthService,
    jan: users_repo.UserRow,
    sm: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
    clock: FrozenClock,
) -> None:
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    keys = ApiKeyService(sm, auth_settings, clock, SeqIdGenerator())
    k = await keys.create(p)
    assert await keys.delete(p, k.token) == 1
    for token in (k.token, "ragflow-nieznany", "cokolwiek"):
        with pytest.raises(Unauthorized):
            await auth.authenticate(token)


# --- logout --------------------------------------------------------------------


async def test_logout_revokes_only_current_session(
    auth: AuthService, jan: users_repo.UserRow, sm: async_sessionmaker[AsyncSession]
) -> None:
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    await auth.logout(p, t.refresh_token, all_sessions=False)
    row = await _row_by_hash(sm, t.refresh_token)
    assert row is not None
    assert row.revoked_at is not None
    principal = await auth.authenticate(t.access_token)  # access token nadal ważny
    assert principal.user_id == jan.id


async def test_logout_all_bumps_token_version(
    auth: AuthService,
    jan: users_repo.UserRow,
    users_svc: UserService,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    t = await _login(auth)
    p = await auth.authenticate(t.access_token)
    await auth.logout(p, None, all_sessions=True)
    version = await _scalar(sm, "SELECT token_version FROM users WHERE id = :id", id=jan.id)
    assert version == jan.token_version + 1
    for token in (t.access_token, t.legacy_token):
        with pytest.raises(Unauthorized):
            await auth.authenticate(token)
    active = await _scalar(
        sm,
        "SELECT COUNT(*) FROM refresh_sessions WHERE user_id = :uid AND revoked_at IS NULL",
        uid=jan.id,
    )
    assert active == 0
