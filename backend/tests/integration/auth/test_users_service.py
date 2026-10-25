"""Testy UserService i bootstrap_admin (brief T4a, kontrakt C6 i C11)."""

import re

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import (
    AuthenticationFailed,
    Conflict,
    NotFound,
    OperationNotAllowed,
    ValidationFailed,
)
from app.db.repositories import users as users_repo
from app.db.repositories.users import UserRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.auth_passwords import verify_password
from app.services.users import UserService, validate_nickname
from app.tools.migrate import bootstrap_admin
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

pytestmark = pytest.mark.db

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
NEW_PASSWORD = "Nowe-haslo-1"  # noqa: S105 — celowa atrapa hasła w teście


@pytest.fixture
def svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> UserService:
    return UserService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


def _principal(user: UserRow) -> Principal:
    return Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")


async def test_register_normalizes_email_nickname(
    svc: UserService,
) -> None:
    row = await svc.register(email="Jan@X.pl", nickname=" Jan ", password=PASSWORD)
    assert row.email == "jan@x.pl"
    assert row.nickname == "Jan"
    assert row.auth_source == "local"
    assert row.password_hash is not None
    assert row.password_hash.startswith("$argon2id$")


async def test_register_invalid_email(svc: UserService) -> None:
    with pytest.raises(OperationNotAllowed, match=r"^Invalid email address: zly-email!$"):
        await svc.register(email="zly-email", nickname="jan", password=PASSWORD)


async def test_register_email_taken(svc: UserService) -> None:
    await svc.register(email="jan@x.pl", nickname="jan", password=PASSWORD)
    with pytest.raises(OperationNotAllowed, match=r"^Email: jan@x\.pl has already registered!$"):
        await svc.register(email="jan@x.pl", nickname="jan", password=PASSWORD)


@pytest.mark.parametrize(
    ("nickname", "message"),
    [
        ("", "Nickname cannot be empty."),
        ("a" * 101, "Nickname must be at most 100 characters."),
        ("<b>", "Nickname contains invalid characters."),
    ],
)
async def test_register_nickname_invalid(svc: UserService, nickname: str, message: str) -> None:
    with pytest.raises(ValidationFailed, match=f"^{re.escape(message)}$"):
        await svc.register(email="nick@x.pl", nickname=nickname, password=PASSWORD)


async def test_register_password_too_short(svc: UserService) -> None:
    with pytest.raises(ValidationFailed, match=r"^Password must be between 8 and 256 characters.$"):
        await svc.register(email="pw@x.pl", nickname="jan", password="short")  # noqa: S106 — atrapa


def test_validate_nickname_none() -> None:
    with pytest.raises(ValidationFailed, match=r"^Nickname is required.$"):
        validate_nickname(None)


def test_validate_nickname_not_a_string() -> None:
    with pytest.raises(ValidationFailed, match=r"^Nickname must be a string.$"):
        validate_nickname(5)


async def test_create_service_account_without_password(svc: UserService) -> None:
    row = await svc.create(email="svc@x.pl", password=None, is_service=True, is_superuser=True)
    assert row.password_hash is None
    assert row.nickname == "svc"
    assert row.is_service is True


async def test_create_email_taken(svc: UserService) -> None:
    await svc.create(email="svc@x.pl", password=None)
    with pytest.raises(Conflict, match=r"^Email: svc@x\.pl has already registered!$"):
        await svc.create(email="svc@x.pl", password=None)


async def test_get_missing_user(svc: UserService) -> None:
    with pytest.raises(NotFound, match=r"^User not found!$"):
        await svc.get("0" * 32)


async def test_update_profile_ignores_foreign_fields(svc: UserService) -> None:
    user = await svc.register(email="prof@x.pl", nickname="jan", password=PASSWORD)
    row = await svc.update_profile(
        _principal(user),
        {"nickname": "Nowy", "language": "English", "email": "hack@x.pl", "is_superuser": True},
    )
    assert row.nickname == "Nowy"
    assert row.language == "English"
    assert row.email == "prof@x.pl"
    assert row.is_superuser is False


async def test_change_password_bumps_token_version(svc: UserService) -> None:
    user = await svc.register(email="cp@x.pl", nickname="jan", password=PASSWORD)
    await svc.change_password(_principal(user), PASSWORD, NEW_PASSWORD)
    fresh = await svc.get(user.id)
    assert verify_password(fresh.password_hash, PASSWORD) is False
    assert verify_password(fresh.password_hash, NEW_PASSWORD) is True
    assert fresh.token_version == user.token_version + 1


async def test_change_password_wrong_old(svc: UserService) -> None:
    user = await svc.register(email="cp2@x.pl", nickname="jan", password=PASSWORD)
    with pytest.raises(AuthenticationFailed, match=r"^Password error!$"):
        await svc.change_password(_principal(user), "zle", NEW_PASSWORD)
    fresh = await svc.get(user.id)
    assert fresh.token_version == user.token_version
    assert verify_password(fresh.password_hash, PASSWORD) is True


async def test_change_password_without_old_for_passwordless(svc: UserService) -> None:
    user = await svc.create(email="oidc@x.pl", password=None, auth_source="oidc")
    await svc.change_password(_principal(user), None, NEW_PASSWORD)
    fresh = await svc.get(user.id)
    assert verify_password(fresh.password_hash, NEW_PASSWORD) is True


async def test_last_admin_cannot_be_deactivated_or_demoted(svc: UserService) -> None:
    admin = await svc.create(email="a@x.pl", password=PASSWORD, is_superuser=True)
    message = "^The last active administrator cannot be deactivated or demoted.$"
    with pytest.raises(OperationNotAllowed, match=message):
        await svc.set_active(admin.id, False)
    with pytest.raises(OperationNotAllowed, match=message):
        await svc.set_superuser(admin.id, False)


async def test_demote_one_of_two_admins(svc: UserService) -> None:
    a = await svc.create(email="a2@x.pl", password=PASSWORD, is_superuser=True)
    await svc.create(email="b@x.pl", password=PASSWORD, is_superuser=True)
    await svc.set_superuser(a.id, False)
    fresh = await svc.get(a.id)
    assert fresh.is_superuser is False
    assert fresh.token_version == a.token_version + 1


async def test_deactivate_regular_user(svc: UserService) -> None:
    user = await svc.create(email="u@x.pl", password=PASSWORD)
    await svc.set_active(user.id, False)
    fresh = await svc.get(user.id)
    assert fresh.is_active is False
    assert fresh.token_version == user.token_version + 1


async def test_ensure_admin_idempotent(
    svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    assert await svc.ensure_admin("root@x.pl", PASSWORD) is True
    assert await svc.ensure_admin("root@x.pl", PASSWORD) is False
    async with transaction(sm) as session:
        row = await users_repo.get_by_email(session, "root@x.pl")
    assert row is not None
    assert row.is_superuser is True
    assert verify_password(row.password_hash, PASSWORD) is True


async def test_ensure_admin_rejects_empty(
    svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    assert await svc.ensure_admin("", "x") is False
    assert await svc.ensure_admin("a@x.pl", "") is False
    async with transaction(sm) as session:
        assert await users_repo.get_by_email(session, "a@x.pl") is None


async def test_bootstrap_admin_idempotent(auth_settings: Settings) -> None:
    settings = auth_settings.model_copy(
        update={"admin_email": "boot@x.pl", "admin_password": SecretStr(PASSWORD)}
    )
    assert await bootstrap_admin(settings) is True
    assert await bootstrap_admin(settings) is False
