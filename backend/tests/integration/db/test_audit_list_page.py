"""Strona wpisów audytu ``audit_log.list_page`` na MariaDB (brief T4, kontrakt E3-6a §4).

Sprawdzamy: kolejność ``id DESC`` i łączny licznik, filtr ``actor`` bez rozróżniania wielkości
liter, filtr ``action``, przedział ``from_ms``/``to_ms`` (domknięty z obu stron) oraz ``limit``
z ``offset``. Wiersze wstawiamy wprost repozytorium — bez usługi i bez tras.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import audit_log as audit_repo
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

BASE_MS = 1790157600000
_ROWS = 3  # wpisy w testach kolejności i przedziału czasu
_ALICE_ROWS = 2  # wpisy Aliny w teście filtra aktora
_LIMIT = 2  # rozmiar strony w teście limit/offset
_PAGES = 5  # łączna liczba wpisów w teście limit/offset
_ALICE = "ala@example.com"
_BOB = "bob@example.com"


@pytest.fixture
async def db(fresh_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Zmigrowana świeża baza; fabryka sesji, engine zamknięty po teście."""
    await asyncio.to_thread(command.upgrade, alembic_cfg(fresh_db), "head")
    engine = make_engine(fresh_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def _insert(
    db: async_sessionmaker[AsyncSession],
    *,
    ts: int,
    actor: str,
    action: str,
    details_json: str | None = None,
) -> None:
    """Wpis audytu wprost przez repo; kolejność wstawień wyznacza rosnące ``id``."""
    async with transaction(db) as session:
        await audit_repo.insert(
            session,
            ts=ts,
            actor_id=None,
            actor_label=actor,
            action=action,
            target_type="access",
            target_id="ktos@example.com",
            details_json=details_json,
            ip=None,
        )


async def _page(  # noqa: PLR0913 — filtry z kontraktu §4
    db: async_sessionmaker[AsyncSession],
    *,
    actor: str | None = None,
    action: str | None = None,
    from_ms: int | None = None,
    to_ms: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[int], int]:
    """``(id wierszy, total)`` z ``list_page`` — asercje czytają tylko identyfikatory."""
    async with transaction(db) as session:
        rows, total = await audit_repo.list_page(
            session,
            actor=actor,
            action=action,
            from_ms=from_ms,
            to_ms=to_ms,
            limit=limit,
            offset=offset,
        )
    return [row.id for row in rows], total


async def test_list_page_orders_desc_and_counts_all(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """Trzy wpisy: kolejność ``id DESC`` i ``total`` równy liczbie pasujących (nie stronie)."""
    for index in range(_ROWS):
        await _insert(db, ts=BASE_MS + index, actor=_ALICE, action="access_granted")

    ids, total = await _page(db)

    assert total == _ROWS
    assert len(ids) == _ROWS
    assert ids == sorted(ids, reverse=True)


async def test_actor_filter_ignores_case_and_action_filter_is_exact(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """``actor`` bez wielkości liter, ``action`` dokładnie; oba naraz zawężają zbiór."""
    await _insert(db, ts=BASE_MS, actor=_ALICE, action="access_granted")
    await _insert(db, ts=BASE_MS + 1, actor=_BOB, action="access_granted")
    await _insert(db, ts=BASE_MS + 2, actor=_ALICE, action="access_revoked")

    alice_ids, alice_total = await _page(db, actor="ALA@Example.COM")
    assert alice_total == _ALICE_ROWS
    assert len(alice_ids) == _ALICE_ROWS

    granted_ids, granted_total = await _page(db, actor=_ALICE, action="access_granted")
    (granted_id,) = granted_ids
    assert granted_total == 1
    assert granted_id == min(alice_ids)

    assert await _page(db, actor="ktos@example.com") == ([], 0)


async def test_time_window_is_inclusive_and_filters_both_ways(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """``from_ms``/``to_ms`` domknięte z obu stron; okno poza zakresem → pusto."""
    for index in range(_ROWS):
        await _insert(db, ts=BASE_MS + index, actor=_ALICE, action="access_granted")

    ids, total = await _page(db, from_ms=BASE_MS + 1, to_ms=BASE_MS + 1)
    assert total == 1
    assert len(ids) == 1

    _, wide_total = await _page(db, from_ms=BASE_MS, to_ms=BASE_MS + _ROWS - 1)
    assert wide_total == _ROWS

    _, late_total = await _page(db, from_ms=BASE_MS + 10)
    assert late_total == 0

    _, early_total = await _page(db, to_ms=BASE_MS - 1)
    assert early_total == 0


async def test_limit_and_offset_do_not_change_the_total(
    db: async_sessionmaker[AsyncSession],
) -> None:
    """``limit``/``offset`` stronicują wiersze, a ``total`` liczy wszystkie pasujące."""
    for index in range(_PAGES):
        await _insert(db, ts=BASE_MS + index, actor=_ALICE, action="access_granted")

    first_ids, first_total = await _page(db, limit=_LIMIT)
    second_ids, second_total = await _page(db, limit=_LIMIT, offset=_LIMIT)

    assert first_total == second_total == _PAGES
    assert len(first_ids) == len(second_ids) == _LIMIT
    assert set(first_ids).isdisjoint(second_ids)
    assert first_ids == sorted(first_ids, reverse=True)


async def test_details_are_returned_decoded_and_full(db: async_sessionmaker[AsyncSession]) -> None:
    """Repo nie redaguje ``details`` — to robi trasa; dekodowanie JSON jest po stronie repo."""
    await _insert(
        db, ts=BASE_MS, actor=_ALICE, action="access_granted", details_json='{"email": "a@x.pl"}'
    )
    await _insert(db, ts=BASE_MS + 1, actor=_ALICE, action="access_revoked")

    async with transaction(db) as session:
        rows, _ = await audit_repo.list_page(
            session, actor=None, action=None, from_ms=None, to_ms=None, limit=20, offset=0
        )

    assert rows[0].details is None
    assert rows[1].details == {"email": "a@x.pl"}
