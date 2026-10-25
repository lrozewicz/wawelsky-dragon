"""Testy operacji SVC na kontach (brief T4a, kontrakt C4) — `UserService` po e-mailu."""

import re

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import Conflict, NotFound, OperationNotAllowed, ValidationFailed
from app.domain.policy import Principal
from app.services.auth_passwords import verify_password
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

pytestmark = pytest.mark.db

PASSWORD = "Sup3r-secret-pw"  # noqa: S105 — celowa atrapa hasła w teście
NEW_PASSWORD = "Nowe-haslo-1"  # noqa: S105 — celowa atrapa hasła w teście


@pytest.fixture
def svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> UserService:
    return UserService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


async def test_create_managed_example_from_brief(svc: UserService) -> None:
    """Przykład z briefu: e-mail normalizowany, nickname domyślny z części lokalnej."""
    row = await svc.create_managed(
        email="Ann+t@X.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    assert row.email == "ann+t@x.pl"
    assert row.nickname == "ann+t"
    assert row.auth_source == "local"
    assert row.is_superuser is False
    assert verify_password(row.password_hash, PASSWORD) is True


async def test_create_managed_default_nickname_keeps_plus(svc: UserService) -> None:
    row = await svc.create_managed(
        email="a+b@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    assert row.nickname == "a+b"


async def test_create_managed_nickname_from_argument_is_stripped(svc: UserService) -> None:
    row = await svc.create_managed(
        email="nick@x.pl", password=PASSWORD, nickname="  Kaśka + ", is_superuser=False
    )
    assert row.nickname == "Kaśka +"


async def test_create_managed_truncates_long_nickname(svc: UserService) -> None:
    row = await svc.create_managed(
        email="long@x.pl", password=PASSWORD, nickname="x" * 150, is_superuser=False
    )
    assert row.nickname == "x" * 100


async def test_create_managed_role_admin_sets_superuser(svc: UserService) -> None:
    """Rola `admin` z routera mapuje się na `is_superuser=True` (C8)."""
    row = await svc.create_managed(
        email="admin+1@x.pl", password=PASSWORD, nickname="Adm", is_superuser=True
    )
    assert row.is_superuser is True


async def test_create_managed_duplicate_case_insensitive(svc: UserService) -> None:
    await svc.create_managed(email="a+b@x.pl", password=PASSWORD, nickname=None, is_superuser=False)
    with pytest.raises(Conflict, match=r"^User already exists$"):
        await svc.create_managed(
            email="A+B@X.pl", password=PASSWORD, nickname=None, is_superuser=False
        )


@pytest.mark.parametrize("email", ["zly-email", "a@b", "a@b.c", "a b@x.pl", "a/b@x.pl"])
async def test_create_managed_invalid_email(svc: UserService, email: str) -> None:
    message = re.escape(f"Invalid email address: {email}")
    with pytest.raises(ValidationFailed, match=f"^{message}$"):
        await svc.create_managed(email=email, password=PASSWORD, nickname=None, is_superuser=False)


async def test_create_managed_email_too_long(svc: UserService) -> None:
    email = "a" * 251 + "@x.pl"  # 256 znaków (> 255)
    with pytest.raises(ValidationFailed, match=r"^Invalid email address: "):
        await svc.create_managed(email=email, password=PASSWORD, nickname=None, is_superuser=False)


async def test_create_managed_weak_password(svc: UserService) -> None:
    with pytest.raises(ValidationFailed, match=r"^Password must be between 8 and 256 characters.$"):
        await svc.create_managed(
            email="weak@x.pl",
            password="short",  # noqa: S106 — celowa atrapa hasła w teście
            nickname=None,
            is_superuser=False,
        )


async def test_require_by_email_case_insensitive(svc: UserService) -> None:
    await svc.create_managed(
        email="Case@X.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    row = await svc.require_by_email("CASE@x.PL")
    assert row.email == "case@x.pl"


async def test_require_by_email_missing(svc: UserService) -> None:
    with pytest.raises(NotFound, match=r"^User not found$"):
        await svc.require_by_email("brak@x.pl")


async def test_update_managed_example_from_brief(svc: UserService) -> None:
    await svc.create_managed(
        email="ANN+T@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    changes = await svc.update_managed(
        "ANN+T@X.pl", nickname="Ann", is_active=False, is_superuser=None
    )
    assert changes == ["nickname", "is_active"]
    row = await svc.require_by_email("ann+t@x.pl")
    assert row.nickname == "Ann"
    assert row.is_active is False


async def test_update_managed_returns_changes_in_contract_order(svc: UserService) -> None:
    await svc.create_managed(email="ord@x.pl", password=PASSWORD, nickname=None, is_superuser=False)
    changes = await svc.update_managed(
        "ord@x.pl", nickname="Ord", is_active=True, is_superuser=True
    )
    assert changes == ["nickname", "is_active", "is_superuser"]
    row = await svc.require_by_email("ord@x.pl")
    assert row.nickname == "Ord"
    assert row.is_superuser is True


async def test_update_managed_empty_nickname(svc: UserService) -> None:
    await svc.create_managed(
        email="empty@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    with pytest.raises(ValidationFailed, match=r"^nickname must be a non-empty string$"):
        await svc.update_managed("empty@x.pl", nickname="   ", is_active=None, is_superuser=None)


async def test_update_managed_demoting_last_admin_raises(svc: UserService) -> None:
    await svc.create_managed(
        email="only-admin@x.pl", password=PASSWORD, nickname="Adm", is_superuser=True
    )
    message = r"^The last active administrator cannot be deactivated or demoted.$"
    with pytest.raises(OperationNotAllowed, match=message):
        await svc.update_managed(
            "ONLY-ADMIN@x.pl", nickname=None, is_active=None, is_superuser=False
        )


async def test_update_managed_missing_user(svc: UserService) -> None:
    with pytest.raises(NotFound, match=r"^User not found$"):
        await svc.update_managed("brak@x.pl", nickname="x", is_active=None, is_superuser=None)


async def test_set_password_by_email_bumps_token_version(svc: UserService) -> None:
    user = await svc.create_managed(
        email="pw@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    await svc.set_password_by_email("PW@x.pl", NEW_PASSWORD)
    fresh = await svc.require_by_email("pw@x.pl")
    assert fresh.token_version == user.token_version + 1
    assert verify_password(fresh.password_hash, NEW_PASSWORD) is True
    assert verify_password(fresh.password_hash, PASSWORD) is False


async def test_set_password_by_email_missing_user(svc: UserService) -> None:
    with pytest.raises(NotFound, match=r"^User not found$"):
        await svc.set_password_by_email("brak@x.pl", NEW_PASSWORD)


async def test_set_password_by_email_weak_password(svc: UserService) -> None:
    await svc.create_managed(email="pw2@x.pl", password=PASSWORD, nickname=None, is_superuser=False)
    with pytest.raises(ValidationFailed, match=r"^Password must be between 8 and 256 characters.$"):
        await svc.set_password_by_email("pw2@x.pl", "short")


async def test_set_active_by_email(svc: UserService) -> None:
    user = await svc.create_managed(
        email="act@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    await svc.set_active_by_email("ACT@X.pl", False)
    fresh = await svc.require_by_email("act@x.pl")
    assert fresh.is_active is False
    assert fresh.token_version == user.token_version + 1
    await svc.set_active_by_email("act@x.pl", True)
    assert (await svc.require_by_email("act@x.pl")).is_active is True


async def test_set_active_by_email_missing_user(svc: UserService) -> None:
    with pytest.raises(NotFound, match=r"^User not found$"):
        await svc.set_active_by_email("brak@x.pl", False)


async def test_list_all_orders_by_create_time_and_id(svc: UserService) -> None:
    await svc.create(email="svc@x.pl", password=None, is_service=True)
    await svc.create_managed(email="a@x.pl", password=PASSWORD, nickname=None, is_superuser=False)
    rows = await svc.list_all()
    assert [row.email for row in rows] == ["svc@x.pl", "a@x.pl"]
    assert rows[0].is_service is True
    assert rows[1].is_service is False


async def test_principal_of_fields(svc: UserService) -> None:
    row = await svc.create(
        email="svc-admin@x.pl", password=None, is_service=True, is_superuser=True
    )
    principal = svc.principal_of(row)
    assert principal == Principal(row.id, "svc-admin@x.pl", True, True, "api_key")
    assert principal.auth_kind == "api_key"
    assert principal.user_id == row.id
    assert principal.email == "svc-admin@x.pl"
