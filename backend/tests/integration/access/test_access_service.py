"""Testy AccessService i AuditService na MariaDB (brief T2, kontrakt C2 i C3)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.db.repositories import assistant_access as access_repo
from app.db.repositories import audit_log as audit_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from app.services.access import AccessService
from app.services.audit import AuditService
from tests.fakes.clock import FrozenClock
from tests.integration.chat.conftest import seed_user

pytestmark = pytest.mark.db

TIME_MS = 1790157600000
AUTO_PROVISION = "hub-compat-auto-provisioning"


def _access(sm: async_sessionmaker[AsyncSession], settings: Settings) -> AccessService:
    """Usługa grantów na sessionmakerze testowym (kontrakt C3 — bez id_gen)."""
    return AccessService(sm, settings, FrozenClock())


def _audit(sm: async_sessionmaker[AsyncSession], settings: Settings) -> AuditService:
    """Usługa audytu na sessionmakerze testowym (kontrakt C3)."""
    return AuditService(sm, settings, FrozenClock())


async def _seed_chat(sm: async_sessionmaker[AsyncSession], tenant_id: str) -> str:
    """Wstawia czat przez `chats_repo.insert`; zwraca jego id (FK assistant_access.chat_id)."""
    chat_id = uuid.uuid4().hex
    row = ChatRow(
        id=chat_id,
        tenant_id=tenant_id,
        created_by=tenant_id,
        name=f"Czat testowy {chat_id[:8]}",
        language="Polish",
        llm_id="fake-chat",
        llm_setting={},
        prompt_config={},
        similarity_threshold=0.0,
        vector_similarity_weight=0.3,
        top_n=6,
        top_k=1024,
        rerank_candidates_count=64,
        rerank_id="",
        meta_data_filter=None,
        status="1",
    )
    async with transaction(sm) as session:
        await chats_repo.insert(session, row, now_ms=TIME_MS)
    return chat_id


async def _rows(sm: async_sessionmaker[AsyncSession], email: str) -> list[access_repo.AccessRow]:
    """Wiersze grantów wprost z repozytorium (żeby sprawdzić też zapis w bazie)."""
    async with transaction(sm) as session:
        return await access_repo.list_for_email(session, email)


async def _stored_email(sm: async_sessionmaker[AsyncSession], chat_id: str) -> str:
    """Surowy e-mail z bazy dla danego czatu — dowód normalizacji lowercase."""
    async with transaction(sm) as session:
        return str(
            (
                await session.execute(
                    text("SELECT email FROM assistant_access WHERE chat_id = :chat_id"),
                    {"chat_id": chat_id},
                )
            ).scalar_one()
        )


async def test_get_returns_empty_for_unknown_email(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    access = _access(sm, migrated_db)
    assert await access.get("nikt@x.pl") == []


async def test_replace_sets_created_by_actor_for_all_rows(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    """Najpierw auto-provisioning, potem replace z aktorem — wszystkie wiersze aktora."""
    access = _access(sm, migrated_db)
    owner = await seed_user(sm)
    chat_1 = await _seed_chat(sm, owner)
    chat_2 = await _seed_chat(sm, owner)
    assert await access.get("a@x.pl") == []

    await access.grant("a@x.pl", chat_1, AUTO_PROVISION)
    await access.grant("a@x.pl", chat_2, AUTO_PROVISION)

    # Przykład z briefu: duplikaty deduplikowane, aktor nadpisuje created_by.
    count = await access.replace("A@X.pl", [chat_1, chat_1, chat_2], "admin@x")

    assert count == len({chat_1, chat_2})
    rows = await _rows(sm, "a@x.pl")
    assert {row.chat_id for row in rows} == {chat_1, chat_2}
    assert {row.created_by for row in rows} == {"admin@x"}


async def test_replace_dedupes_and_returns_unique_count(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    access = _access(sm, migrated_db)
    owner = await seed_user(sm)
    chat_1 = await _seed_chat(sm, owner)
    chat_2 = await _seed_chat(sm, owner)

    count = await access.replace("a@x.pl", [chat_2, chat_1, chat_2, chat_1], "adm")

    assert count == len({chat_1, chat_2})
    entries = await access.get("a@x.pl")
    assert {entry.dialog_id for entry in entries} == {chat_1, chat_2}
    assert [entry.dialog_id for entry in entries] == sorted([chat_1, chat_2])


async def test_replace_unknown_chat_raises_and_keeps_set(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    access = _access(sm, migrated_db)
    owner = await seed_user(sm)
    chat_1 = await _seed_chat(sm, owner)
    await access.replace("a@x.pl", [chat_1], "adm")

    with pytest.raises(ValidationFailed, match=r"^Unknown dialog_ids: bad$"):
        await access.replace("a@x.pl", [chat_1, "bad"], None)

    rows = await _rows(sm, "a@x.pl")
    assert [row.chat_id for row in rows] == [chat_1]
    assert rows[0].created_by == "adm"


async def test_grant_is_idempotent_and_keeps_created_by(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    access = _access(sm, migrated_db)
    owner = await seed_user(sm)
    chat_1 = await _seed_chat(sm, owner)
    await access.grant("a@x.pl", chat_1, "adm")

    # Przykład z briefu: drugi grant bez błędu i bez nadpisania created_by.
    await access.grant("a@x.pl", chat_1, "other")

    rows = await _rows(sm, "a@x.pl")
    assert len(rows) == 1
    assert rows[0].created_by == "adm"


async def test_grant_unknown_chat_raises(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    access = _access(sm, migrated_db)
    with pytest.raises(ValidationFailed, match=r"^Unknown dialog_ids: nope$"):
        await access.grant("a@x.pl", "nope", "adm")


async def test_revoke_missing_row_is_no_error(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    access = _access(sm, migrated_db)
    owner = await seed_user(sm)
    chat_1 = await _seed_chat(sm, owner)
    await access.grant("a@x.pl", chat_1, "adm")

    await access.revoke("a@x.pl", chat_1)
    assert await access.get("a@x.pl") == []
    # Powtórne odebranie nieistniejącego wiersza też nie jest błędem.
    await access.revoke("a@x.pl", chat_1)


async def test_email_is_stored_lowercase(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    access = _access(sm, migrated_db)
    owner = await seed_user(sm)
    chat_1 = await _seed_chat(sm, owner)

    await access.grant("A@B.PL", chat_1, None)

    assert await _stored_email(sm, chat_1) == "a@b.pl"
    rows = await _rows(sm, "A@B.PL")
    assert len(rows) == 1
    assert rows[0].created_by is None


async def test_deleting_chat_cascades_grants(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    access = _access(sm, migrated_db)
    owner = await seed_user(sm)
    chat_1 = await _seed_chat(sm, owner)
    await access.grant("a@x.pl", chat_1, "adm")

    async with transaction(sm) as session:
        await session.execute(text("DELETE FROM chats WHERE id = :id"), {"id": chat_1})

    assert await access.get("a@x.pl") == []


async def test_audit_record_and_list_by_action(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    audit = _audit(sm, migrated_db)
    await audit.record(
        actor_label="admin@x",
        action="user_created",
        target_type="user",
        target_id="u1",
        details={"email": "a@b.pl"},
        actor_id="1" * 32,
        ip="10.0.0.1",
    )
    await audit.record(
        actor_label="admin@x", action="user_deleted", target_type="user", target_id="u2"
    )

    async with transaction(sm) as session:
        found = await audit_repo.list_by_action(session, "user_created")
        other = await audit_repo.list_by_action(session, "user_deleted")

    assert len(found) == 1
    assert found[0].ts == FrozenClock().now_ms()
    assert found[0].actor_id == "1" * 32
    assert found[0].actor_label == "admin@x"
    assert found[0].target_type == "user"
    assert found[0].target_id == "u1"
    assert found[0].details == {"email": "a@b.pl"}
    assert found[0].ip == "10.0.0.1"
    assert len(other) == 1
    assert other[0].details is None
    assert other[0].ip is None


async def test_audit_truncates_target_id_and_ip(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    audit = _audit(sm, migrated_db)
    await audit.record(
        actor_label="admin@x",
        action="access_granted",
        target_type="access",
        target_id="t" * 70,
        ip="9" * 50,
    )

    async with transaction(sm) as session:
        found = await audit_repo.list_by_action(session, "access_granted")

    assert found[0].target_id == "t" * 64
    assert found[0].ip == "9" * 45


async def test_audit_unknown_action_raises(
    sm: async_sessionmaker[AsyncSession], migrated_db: Settings
) -> None:
    audit = _audit(sm, migrated_db)
    with pytest.raises(ValueError, match=r"^Unknown audit action: nope$"):
        await audit.record(actor_label="admin@x", action="nope", target_type="user", target_id="u1")
