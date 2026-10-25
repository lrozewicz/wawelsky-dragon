"""Testy repozytorium `dataset_imports` na MariaDB (CONTRACT E7-1f §5, K19 §4).

Wszystkie testy asynchroniczne — świeża baza migrowana do head przez fixture `migrated_db`.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import dataset_imports as repo
from app.db.uow import transaction
from tests.integration.conftest import _root_connection
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME, TIME_MS

pytestmark = pytest.mark.db

LATER = TIME_MS + 5_000
EXPIRES = TIME_MS + 86_400_000
IMPORT_ID = "a" * 32
DAY_MS = 86_400_000
SIZE_BYTES = 2048
CHUNK_BYTES = 512


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head (sync — env.py Alembic robi asyncio.run, C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def _seed_user(sm: async_sessionmaker[AsyncSession], *, nickname: str = "seed") -> str:
    """Wstawia `users` (FK sesji importu); zwraca id."""
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


async def _insert(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    sm: async_sessionmaker[AsyncSession],
    user_id: str,
    *,
    id: str = IMPORT_ID,
    size_bytes: int = SIZE_BYTES,
    expires_at: int = EXPIRES,
    now_ms: int = TIME_MS,
) -> None:
    """Sesja importu w stanie `uploading` (CONTRACT §5)."""
    async with transaction(sm) as session:
        await repo.insert(
            session,
            id=id,
            user_id=user_id,
            file_name="baza.wdkb.zip",
            size_bytes=size_bytes,
            expires_at=expires_at,
            now_ms=now_ms,
        )


async def test_insert_then_get_defaults(sm: async_sessionmaker[AsyncSession]) -> None:
    """`insert` → `get`: stan początkowy `uploading`, 0 bajtów, puste `errors` (§5)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner, size_bytes=SIZE_BYTES)
    async with transaction(sm) as session:
        row = await repo.get(session, IMPORT_ID)
    assert row is not None
    assert row["id"] == IMPORT_ID
    assert row["user_id"] == owner
    assert row["file_name"] == "baza.wdkb.zip"
    assert row["size_bytes"] == SIZE_BYTES
    assert row["received_bytes"] == 0
    assert row["state"] == "uploading"
    assert row["errors"] == []
    assert row["summary"] is None
    assert row["task_id"] is None
    assert row["expires_at"] == EXPIRES
    assert (row["create_time"], row["update_time"]) == (TIME_MS, TIME_MS)


async def test_get_unknown_returns_none(sm: async_sessionmaker[AsyncSession]) -> None:
    """`get` nieznanego id → None (§5)."""
    async with transaction(sm) as session:
        assert await repo.get(session, uuid.uuid4().hex) is None


async def test_add_received_accumulates_and_extends_expiry(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`add_received` dolicza porcję, przedłuża `expires_at` i podbija `update_time` (§5)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner, size_bytes=SIZE_BYTES)
    async with transaction(sm) as session:
        await repo.add_received(
            session,
            import_id=IMPORT_ID,
            received_bytes=CHUNK_BYTES,
            expires_at=EXPIRES + DAY_MS,
            now_ms=LATER,
        )
        after_first = await repo.get(session, IMPORT_ID)
    assert after_first is not None
    assert after_first["received_bytes"] == CHUNK_BYTES
    assert after_first["expires_at"] == EXPIRES + DAY_MS
    assert after_first["update_time"] == LATER
    async with transaction(sm) as session:
        await repo.add_received(
            session,
            import_id=IMPORT_ID,
            received_bytes=CHUNK_BYTES,
            expires_at=EXPIRES + 2 * DAY_MS,
            now_ms=LATER + 1,
        )
        after_second = await repo.get(session, IMPORT_ID)
    assert after_second is not None
    assert after_second["received_bytes"] == 2 * CHUNK_BYTES
    assert after_second["expires_at"] == EXPIRES + 2 * DAY_MS


async def test_set_state_ready_with_summary(sm: async_sessionmaker[AsyncSession]) -> None:
    """`set_state` zapisuje stan, `summary` (JSON → dict) i `task_id` (§5)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner)
    summary = {"name": "Korpus", "documents": 3, "chunks": 7, "schema_version": 1}
    async with transaction(sm) as session:
        await repo.set_state(
            session, import_id=IMPORT_ID, state="ready", summary=summary, now_ms=LATER
        )
        row = await repo.get(session, IMPORT_ID)
    assert row is not None
    assert row["state"] == "ready"
    assert row["summary"] == summary
    assert row["errors"] == []
    assert row["update_time"] == LATER


async def test_set_state_invalid_with_errors_and_task(sm: async_sessionmaker[AsyncSession]) -> None:
    """`set_state` zapisuje `errors` (JSON → list[dict]) i `task_id` (§5)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner)
    errors = [{"code": "invalid_archive", "message": "Uszkodzone archiwum"}]
    async with transaction(sm) as session:
        await repo.set_state(
            session,
            import_id=IMPORT_ID,
            state="started",
            errors=errors,
            task_id="t" * 32,
            now_ms=LATER,
        )
        row = await repo.get(session, IMPORT_ID)
    assert row is not None
    assert row["state"] == "started"
    assert row["errors"] == errors
    assert row["task_id"] == "t" * 32
    assert row["summary"] is None


async def test_delete_returns_true_then_false(sm: async_sessionmaker[AsyncSession]) -> None:
    """`delete` zwraca True raz, potem False; wiersz znika (§5)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner)
    async with transaction(sm) as session:
        assert await repo.delete(session, IMPORT_ID) is True
        assert await repo.get(session, IMPORT_ID) is None
        assert await repo.delete(session, IMPORT_ID) is False


async def test_delete_cascades_on_user_removal(sm: async_sessionmaker[AsyncSession]) -> None:
    """FK `user_id` ON DELETE CASCADE: usunięcie użytkownika zabiera jego sesje (§4)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner)
    async with transaction(sm) as session:
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": owner})
        assert await repo.get(session, IMPORT_ID) is None


async def test_expire_older_marks_and_returns_ids(sm: async_sessionmaker[AsyncSession]) -> None:
    """`expire_older` przestawia tylko wygasłe nie-`expired` wiersze i zwraca ich id (§5)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner, id="a" * 32, expires_at=TIME_MS + 1000)
    await _insert(sm, owner, id="b" * 32, expires_at=TIME_MS + 9000)
    async with transaction(sm) as session:
        expired = await repo.expire_older(session, before_ms=TIME_MS + 5000, now_ms=LATER)
    assert expired == ["a" * 32]
    async with transaction(sm) as session:
        first = await repo.get(session, "a" * 32)
        second = await repo.get(session, "b" * 32)
    assert first is not None
    assert second is not None
    assert first["state"] == "expired"
    assert first["update_time"] == LATER
    assert second["state"] == "uploading"
    # Powtórny przebieg nie zwraca już przestawionego wiersza (idempotencja).
    async with transaction(sm) as session:
        assert await repo.expire_older(session, before_ms=TIME_MS + 5000, now_ms=LATER) == []
        # Wiersz niewygasły nigdy nie trafia do wyniku.
        assert await repo.expire_older(session, before_ms=TIME_MS + 500, now_ms=LATER) == []


def _lock_wait(connection_id: int) -> bool:
    """Czy transakcja MariaDB o tym id czeka na blokadę wiersza (``LOCK WAIT``).

    ``information_schema.INNODB_TRX`` czytamy połączeniem root — użytkownik ``wawelsky`` nie ma
    ``PROCESS``. Filtr po ``trx_mysql_thread_id`` (z ``SELECT CONNECTION_ID()``) zawęża wynik do
    transakcji tego testu, więc równoległe testy (xdist) nie fałszują warunku.
    """
    connection = _root_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.INNODB_TRX"
                " WHERE trx_mysql_thread_id = %s AND trx_state = 'LOCK WAIT'",
                (connection_id,),
            )
            return cursor.fetchone() is not None
    finally:
        connection.close()


async def _wait_until(
    pred: Callable[[], Awaitable[bool]],
    *,
    label: str,
    timeout: float = 15.0,  # noqa: ASYNC109 — nazwa `timeout` z helpera test_worker.wait_until
) -> None:
    """Czeka, aż ``pred()`` zwróci ``True`` (pętla 50 ms z limitem); inaczej ``AssertionError``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await pred():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{label} nie został spełniony w {timeout} s")


async def test_expire_older_ignores_row_changed_under_lock(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`expire_older` atomowe: wiersz zmieniony stanem pod blokadą nie wraca (CONTRACT E7-1z §4).

    Trzymający transakcję blokuje wiersz „a” ``FOR UPDATE``, a ``expire_older`` (w innej sesji)
    biegnie równolegle i czeka na ``SELECT … FOR UPDATE``. Zmianę „a” na ``expired`` wykonujemy
    dopiero, gdy serwer potwierdzi, że transakcja zadania czeka na blokadę (``INNODB_TRX`` →
    ``LOCK WAIT``) — kolejność wymusza serwer, nie zgadywany czas (dawne ``asyncio.sleep(0.3)``
    słabło przy obciążeniu i było niedeterministyczne). Gdy „a” zmieni stan pod trzymaną blokadą,
    kandydat „a” nie pasuje już do kryterium — nie może wrócić w wyniku, bo zwracane są dokładnie
    wiersze faktycznie przestawione na ``expired``. Wiersz ``expired`` („d”) i wiersz ``uploading``
    z przedłużonym ``expires_at`` („b”) nie są kandydatami.
    """
    owner = await _seed_user(sm)
    await _insert(sm, owner, id="a" * 32, expires_at=TIME_MS + 1000)  # zmieniony pod blokadą
    await _insert(sm, owner, id="b" * 32, expires_at=TIME_MS + 9000)  # przedłużony — niewygasły
    await _insert(sm, owner, id="c" * 32, expires_at=TIME_MS + 2000)  # zwykły kandydat
    await _insert(sm, owner, id="d" * 32, expires_at=TIME_MS + 1500)  # kandydat na papierze

    connections: list[int] = []

    async def _expire() -> list[str]:
        async with transaction(sm) as session:
            id_row = await session.execute(text("SELECT CONNECTION_ID()"))
            connections.append(int(id_row.scalar_one()))
            return await repo.expire_older(session, before_ms=TIME_MS + 5000, now_ms=LATER)

    async def _waiting_on_lock() -> bool:
        """Czy transakcja zadania czeka już na blokadę (id znane po jej pierwszym zapytaniu)."""
        return bool(connections) and await asyncio.to_thread(_lock_wait, connections[0])

    async with sm() as holder:
        await holder.begin()
        await holder.execute(
            text("SELECT id FROM dataset_imports WHERE id = CAST(:i AS BINARY) FOR UPDATE"),
            {"i": "a" * 32},
        )
        # „d” jest już `expired` (stan zmieniony wcześniej) — mimo `expires_at` w oknie nie wraca.
        await holder.execute(
            text("UPDATE dataset_imports SET state = 'expired' WHERE id = CAST(:i AS BINARY)"),
            {"i": "d" * 32},
        )
        task = asyncio.create_task(_expire())
        await _wait_until(_waiting_on_lock, label="expire_older czeka na blokadę wiersza")
        # „a” zmienia stan pod trzymaną blokadą, przed commitem.
        await holder.execute(
            text("UPDATE dataset_imports SET state = 'expired' WHERE id = CAST(:i AS BINARY)"),
            {"i": "a" * 32},
        )
        await holder.commit()
        expired = await task

    # Tylko „c” — „a” zmienione pod blokadą, „b” przedłużone, „d” już `expired`.
    assert set(expired) == {"c" * 32}, expired
    async with transaction(sm) as session:
        first = await repo.get(session, "a" * 32)
        second = await repo.get(session, "b" * 32)
        third = await repo.get(session, "c" * 32)
        fourth = await repo.get(session, "d" * 32)
    assert first is not None and first["state"] == "expired"
    assert second is not None and second["state"] == "uploading"
    assert third is not None and third["state"] == "expired"
    assert fourth is not None and fourth["state"] == "expired"


async def test_set_state_errors_none_keeps_and_empty_clears(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`set_state(errors=None)` zachowuje poprzednie błędy, `errors=[]` czyści
    (CONTRACT E7-1z §5)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner)
    errors = [{"code": "invalid_archive", "message": "Uszkodzone archiwum"}]
    async with transaction(sm) as session:
        await repo.set_state(
            session, import_id=IMPORT_ID, state="invalid", errors=errors, now_ms=LATER
        )
        kept = await repo.get(session, IMPORT_ID)
    assert kept is not None and kept["errors"] == errors
    # `errors` pominięte (None) → poprzednia wartość zostaje.
    async with transaction(sm) as session:
        await repo.set_state(session, import_id=IMPORT_ID, state="started", now_ms=LATER + 1)
        unchanged = await repo.get(session, IMPORT_ID)
    assert unchanged is not None and unchanged["errors"] == errors
    # `errors=[]` jawnie → czyszczenie.
    async with transaction(sm) as session:
        await repo.set_state(
            session, import_id=IMPORT_ID, state="ready", errors=[], now_ms=LATER + 2
        )
        cleared = await repo.get(session, IMPORT_ID)
    assert cleared is not None and cleared["errors"] == []


async def test_set_final_state_requires_uploading_and_full_received(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """`set_final_state` domyka tylko wiersz `uploading` z `received_bytes == size_bytes` (§6)."""
    owner = await _seed_user(sm)
    await _insert(sm, owner, size_bytes=SIZE_BYTES)  # received_bytes = 0
    summary = {"name": "Korpus", "documents": 1, "chunks": 0, "schema_version": 1}
    # Niepełny rozmiar → warunek nie zachodzi, stan bez zmian.
    async with transaction(sm) as session:
        applied = await repo.set_final_state(
            session, import_id=IMPORT_ID, state="ready", errors=[], summary=summary, now_ms=LATER
        )
        row = await repo.get(session, IMPORT_ID)
    assert applied is False
    assert row is not None and row["state"] == "uploading" and row["summary"] is None
    # Dopełnienie rozmiaru → domknięcie przechodzi.
    async with transaction(sm) as session:
        await repo.add_received(
            session,
            import_id=IMPORT_ID,
            received_bytes=SIZE_BYTES,
            expires_at=EXPIRES,
            now_ms=LATER,
        )
    async with transaction(sm) as session:
        applied = await repo.set_final_state(
            session,
            import_id=IMPORT_ID,
            state="ready",
            errors=[],
            summary=summary,
            now_ms=LATER + 1,
        )
        row = await repo.get(session, IMPORT_ID)
    assert applied is True
    assert row is not None
    assert row["state"] == "ready" and row["summary"] == summary and row["errors"] == []
    # Ponowne domknięcie (stan != `uploading`) → warunek nie zachodzi.
    async with transaction(sm) as session:
        again = await repo.set_final_state(
            session,
            import_id=IMPORT_ID,
            state="invalid",
            errors=[{"code": "x", "message": "y"}],
            summary=None,
            now_ms=LATER + 2,
        )
        row = await repo.get(session, IMPORT_ID)
    assert again is False
    assert row is not None and row["state"] == "ready"
