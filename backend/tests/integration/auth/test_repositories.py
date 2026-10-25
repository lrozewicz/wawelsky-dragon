"""Testy repozytoriów auth: users, refresh_sessions, api_keys (brief T3, kontrakt C5)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import api_keys, refresh_sessions, users
from app.db.uow import transaction

pytestmark = pytest.mark.db

NOW = 1790157600000
UID = "u" * 32
SESSION_ID = "r1" + "0" * 30
FAMILY = "f" * 32


async def _user(s: AsyncSession, user_id: str = UID, email: str = "Jan@X.PL") -> None:
    """Użytkownik do FK (brief: użytkownika do FK wstawiaj przez users.insert)."""
    await users.insert(
        s,
        user_id=user_id,
        email=email,
        nickname="jan",
        password_hash=None,
        auth_source="local",
        oidc_sub=None,
        is_superuser=False,
        is_service=False,
        now_ms=NOW,
    )


async def test_insert_then_get_by_email(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await users.insert(
            s,
            user_id="u" * 32,
            email="Jan@X.PL",
            nickname="jan",
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=False,
            is_service=False,
            now_ms=1790157600000,
        )
        row = await users.get_by_email(s, "jan@x.pl")
        assert row == users.UserRow(
            id="u" * 32,
            email="jan@x.pl",
            nickname="jan",
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=False,
            is_active=True,
            is_service=False,
            language="Polish",
            timezone=None,
            avatar=None,
            last_login_time=None,
            token_version=0,
            create_time=1790157600000,
            update_time=1790157600000,
        )


async def test_get_by_email_lookup_is_lowercase(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        first = await users.get_by_email(s, "jan@x.pl")
        assert await users.get_by_email(s, "JAN@x.pl") == first


async def test_duplicate_email_raises_integrity_error(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(IntegrityError):
        async with transaction(sm) as s:
            await _user(s)
            await users.insert(
                s,
                user_id="v" * 32,
                email="jan@x.pl",
                nickname="jan",
                password_hash=None,
                auth_source="local",
                oidc_sub=None,
                is_superuser=False,
                is_service=False,
                now_ms=NOW,
            )


async def test_get_missing_returns_none(sm: async_sessionmaker[AsyncSession]) -> None:
    async with transaction(sm) as s:
        assert await users.get_by_id(s, "z" * 32) is None
        assert await users.get_by_oidc_sub(s, "brak") is None


async def test_update_fields(sm: async_sessionmaker[AsyncSession]) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await users.update_fields(
            s,
            UID,
            {"nickname": "Jan K", "is_superuser": True, "oidc_sub": "sub-1", "auth_source": "both"},
            NOW + 5,
        )
        row = await users.get_by_id(s, UID)
        assert row is not None
        assert row.nickname == "Jan K"
        assert row.is_superuser is True
        assert row.oidc_sub == "sub-1"
        assert row.auth_source == "both"
        assert row.update_time == NOW + 5
        assert await users.get_by_oidc_sub(s, "sub-1") == row


async def test_update_fields_rejects_non_updatable_column(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        with pytest.raises(ValueError, match="column not updatable: email"):
            await users.update_fields(s, UID, {"email": "x"}, NOW)


async def test_bump_token_version_twice(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await users.bump_token_version(s, UID, NOW + 1)
        await users.bump_token_version(s, UID, NOW + 2)
        row = await users.get_by_id(s, UID)
        assert row is not None
        assert row.token_version == 2  # noqa: PLR2004 — bump_token_version x2


async def test_count_active_superusers(sm: async_sessionmaker[AsyncSession]) -> None:
    async with transaction(sm) as s:
        for name in ("a", "b", "c", "d"):
            await users.insert(
                s,
                user_id=name * 32,
                email=f"{name}@x.pl",
                nickname=name,
                password_hash=None,
                auth_source="local",
                oidc_sub=None,
                is_superuser=name != "d",
                is_service=False,
                now_ms=NOW,
            )
        await users.update_fields(s, "c" * 32, {"is_active": False}, NOW + 1)
        assert await users.count_active_superusers(s) == 2  # noqa: PLR2004 — 2 aktywnych adminów


async def test_refresh_session_insert_and_get_by_hash(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await refresh_sessions.insert(
            s,
            session_id="r1" + "0" * 30,
            user_id=UID,
            token_hash="h" * 64,
            family_id="f" * 32,
            expires_at=NOW + 1000,
            user_agent="x" * 300,
            ip="1.2.3.4",
            now_ms=NOW,
        )
        row = await refresh_sessions.get_by_hash(s, "h" * 64)
        assert row is not None
        assert row.id == SESSION_ID
        assert row.revoked_at is None
        assert row.expires_at == NOW + 1000
        result = await s.execute(
            text("SELECT CHAR_LENGTH(user_agent) FROM refresh_sessions WHERE id = :id"),
            {"id": SESSION_ID},
        )
        assert result.scalar_one() == 255  # noqa: PLR2004 — LIMIT VARCHAR(255) kolumny


async def test_revoke_twice_keeps_first_timestamp(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await refresh_sessions.insert(
            s,
            session_id=SESSION_ID,
            user_id=UID,
            token_hash="h" * 64,
            family_id=FAMILY,
            expires_at=NOW + 1000,
            user_agent=None,
            ip=None,
            now_ms=NOW,
        )
        assert await refresh_sessions.revoke(s, SESSION_ID, NOW + 1) == 1
        assert await refresh_sessions.revoke(s, SESSION_ID, NOW + 2) == 0
        row = await refresh_sessions.get_by_hash(s, "h" * 64)
        assert row is not None
        assert row.revoked_at == NOW + 1


async def test_revoke_family_counts_only_active(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        for i in range(3):
            await refresh_sessions.insert(
                s,
                session_id=str(i + 1) * 32,
                user_id=UID,
                token_hash=str(i) * 64,
                family_id=FAMILY,
                expires_at=NOW + 1000,
                user_agent=None,
                ip=None,
                now_ms=NOW,
            )
        await refresh_sessions.revoke(s, "1" * 32, NOW + 1)
        assert await refresh_sessions.revoke_family(s, FAMILY, NOW + 2) == 2  # noqa: PLR2004 — 2 aktywne z 3
        for i in range(3):
            row = await refresh_sessions.get_by_hash(s, str(i) * 64)
            assert row is not None
            assert row.revoked_at is not None


async def test_revoke_all_for_user_returns_active_count(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        for i in range(3):
            await refresh_sessions.insert(
                s,
                session_id=str(i + 1) * 32,
                user_id=UID,
                token_hash=str(i) * 64,
                family_id=str(i + 1) * 32,
                expires_at=NOW + 1000,
                user_agent=None,
                ip=None,
                now_ms=NOW,
            )
        await refresh_sessions.revoke(s, "1" * 32, NOW + 1)
        assert await refresh_sessions.revoke_all_for_user(s, UID, NOW + 2) == 2  # noqa: PLR2004 — aktywne przed wywołaniem


async def test_api_key_insert_and_get_active_by_hash(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await api_keys.insert(
            s,
            key_id="k" * 32,
            user_id=UID,
            token_hash="t" * 64,
            token_enc=b"\x01\x02",
            prefix="ragflow-abcdefgh",
            name=None,
            now_ms=NOW,
        )
        row = await api_keys.get_active_by_hash(s, "t" * 64)
        assert row is not None
        assert row.token_enc == b"\x01\x02"
        assert row.prefix == "ragflow-abcdefgh"
        assert row.revoked_at is None
        assert row.last_used_at is None


async def test_api_key_revoke_hides_key(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await api_keys.insert(
            s,
            key_id="k" * 32,
            user_id=UID,
            token_hash="t" * 64,
            token_enc=b"\x01\x02",
            prefix="ragflow-abcdefgh",
            name=None,
            now_ms=NOW,
        )
        await api_keys.revoke(s, "k" * 32, NOW + 1)
        assert await api_keys.get_active_by_hash(s, "t" * 64) is None
        assert await api_keys.list_active_for_user(s, UID) == []


async def test_list_active_for_user_orders_by_create_time(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await api_keys.insert(
            s,
            key_id="a" * 32,
            user_id=UID,
            token_hash="t1" + "0" * 62,
            token_enc=b"\x01",
            prefix="ragflow-aaaaaaaa",
            name=None,
            now_ms=NOW,
        )
        await api_keys.insert(
            s,
            key_id="b" * 32,
            user_id=UID,
            token_hash="t2" + "0" * 62,
            token_enc=b"\x02",
            prefix="ragflow-bbbbbbbb",
            name=None,
            now_ms=NOW + 1,
        )
        rows = await api_keys.list_active_for_user(s, UID)
        assert [row.id for row in rows] == ["a" * 32, "b" * 32]


async def test_find_active_for_user_by_each_criterion(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await users.insert(
            s,
            user_id="o" * 32,
            email="other@x.pl",
            nickname="other",
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=False,
            is_service=False,
            now_ms=NOW,
        )
        await api_keys.insert(
            s,
            key_id="k" * 32,
            user_id=UID,
            token_hash="t" * 64,
            token_enc=b"\x01\x02",
            prefix="ragflow-abcdefgh",
            name=None,
            now_ms=NOW,
        )
        for criteria in (
            {"token_hash": "t" * 64},
            {"key_id": "k" * 32},
            {"prefix": "ragflow-abcdefgh"},
        ):
            found = await api_keys.find_active_for_user(s, UID, **criteria)
            assert [row.id for row in found] == ["k" * 32]
            assert await api_keys.find_active_for_user(s, "o" * 32, **criteria) == []


async def test_find_active_for_user_requires_exactly_one_criterion(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        with pytest.raises(ValueError, match="exactly one criterion required"):
            await api_keys.find_active_for_user(s, UID)
        with pytest.raises(ValueError, match="exactly one criterion required"):
            await api_keys.find_active_for_user(
                s, UID, token_hash="t" * 64, prefix="ragflow-abcdefgh"
            )


async def test_touch_last_used_keeps_update_time(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(sm) as s:
        await _user(s)
        await api_keys.insert(
            s,
            key_id="k" * 32,
            user_id=UID,
            token_hash="t" * 64,
            token_enc=b"\x01\x02",
            prefix="ragflow-abcdefgh",
            name=None,
            now_ms=NOW,
        )
        await api_keys.touch_last_used(s, "k" * 32, NOW + 60000)
        row = await api_keys.get_active_by_hash(s, "t" * 64)
        assert row is not None
        assert row.last_used_at == NOW + 60000
        assert row.update_time == NOW
