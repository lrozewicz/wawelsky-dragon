"""Locki przebiegów integracji — cienka warstwa transakcyjna nad repozytorium (K12 §5, C6).

Każda funkcja to jedna krótka transakcja; czas wstrzykiwany parametrem ``now_ms``.
``recover_stale`` domyka przebiegi ``running`` odzyskanej integracji i zapisuje zdarzenie
``error "stale lock recovered"`` w tej samej transakcji.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import integrations as repo
from app.db.repositories.integrations import NewEvent
from app.db.uow import transaction

if TYPE_CHECKING:
    from app.core.container import Container

STALE_LOCK_MESSAGE = "stale lock recovered"


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera (wzorzec ``SyncEngine._sessionmaker``)."""
    return cast("async_sessionmaker[AsyncSession]", container.sessionmaker)


async def acquire(container: Container, integration_id: int, *, owner: str, now_ms: int) -> bool:
    """Zakłada lock integracji; ``False`` = ktoś inny prowadzi przebieg (kontrakt C6)."""
    async with transaction(_sessionmaker(container)) as session:
        return await repo.try_lock(session, integration_id, owner=owner, now_ms=now_ms)


async def heartbeat(container: Container, integration_id: int, *, owner: str, now_ms: int) -> bool:
    """Odświeża ``lock_acquired_at`` właściciela aktywnego locka (kontrakt C6)."""
    async with transaction(_sessionmaker(container)) as session:
        return await repo.heartbeat_lock(session, integration_id, owner=owner, now_ms=now_ms)


async def release(
    container: Container, integration_id: int, *, owner: str, now_ms: int, status: str
) -> bool:
    """Zwalnia lock właściciela i zapisuje ``last_sync_at``/``last_sync_status`` (kontrakt C6)."""
    async with transaction(_sessionmaker(container)) as session:
        return await repo.release_lock(
            session, integration_id, owner=owner, now_ms=now_ms, status=status
        )


async def recover_stale(container: Container, *, now_ms: int, stale_ms: int) -> list[int]:
    """Odzyskuje locki starsze niż ``stale_ms``; runy ``running`` → ``failed`` + zdarzenie (C6)."""
    async with transaction(_sessionmaker(container)) as session:
        recovered = await repo.recover_stale(session, now_ms=now_ms, stale_ms=stale_ms)
        for integration_id in recovered:
            row = await repo.get_integration(session, integration_id)
            run_ids = await repo.running_run_ids(session, integration_id)
            if row is None or not run_ids:
                continue
            await repo.mark_running_runs(session, integration_id, status="failed", now_ms=now_ms)
            await repo.insert_events(
                session,
                [
                    NewEvent(
                        run_id=run_id,
                        integration_id=integration_id,
                        integration_type=row.type,
                        level="error",
                        message=STALE_LOCK_MESSAGE,
                        file_path=None,
                        container_id=None,
                        container_name=None,
                        created_at=now_ms,
                    )
                    for run_id in run_ids
                ],
            )
    return recovered
