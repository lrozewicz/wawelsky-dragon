"""Orkiestracja etapów: ``plan_all`` i ``run_all`` (kontrakt §2, WP E4-6a)."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.keys import StorageKey
from app.tools.ragflow_migrate import stages
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageInventory, StageResult


def _selected(only: Sequence[str] | None) -> list[str]:
    """Nazwy etapów w kolejności ``ORDER``; nieznana nazwa w ``only`` → ValueError."""
    if only is None:
        return [name for name in stages.ORDER if name in stages.STAGES]
    unknown = [name for name in only if name not in stages.ORDER]
    if unknown:
        raise ValueError(f"Nieznany etap: {', '.join(unknown)}")
    wanted = set(only)
    return [name for name in stages.ORDER if name in wanted and name in stages.STAGES]


def plan_all(
    src: Source, ctx: RunContext, only: Sequence[str] | None = None
) -> list[StageInventory]:
    """Inwentarz wszystkich (albo wskazanych) etapów; nic nie pisze do celu."""
    return [stages.STAGES[name].plan(src, ctx) for name in _selected(only)]


async def run_all(
    src: Source,
    sessionmaker: async_sessionmaker[AsyncSession],
    ctx: RunContext,
    only: Sequence[str] | None = None,
    dry_run: bool = False,
) -> list[StageResult]:
    """Jeden bieg w jednej transakcji; commit chyba że ``dry_run`` albo Issue krytyczne."""
    ctx.dry_run = dry_run
    names = _selected(only)  # walidacja nazw przed otwarciem sesji
    session = sessionmaker()
    results: list[StageResult] = []
    try:
        for name in names:
            results.append(await stages.STAGES[name].run(src, session, ctx))
        if dry_run or _any_critical(results):
            await session.rollback()
            await discard_new_blobs(ctx)
        else:
            await session.commit()
    except Exception:  # błąd etapu → rollback i propagacja (kontrakt §2)
        await session.rollback()
        await discard_new_blobs(ctx)
        raise
    finally:
        await session.close()
    return results


async def discard_new_blobs(ctx: RunContext) -> None:
    """Usuwa bloby nowo zapisane w tym biegu i czyści listę kluczy (kontrakt §2)."""
    keys: list[str] = ctx.shared.get("new_blob_keys", [])
    if ctx.storage is not None:
        for key in keys:
            await ctx.storage.delete(StorageKey(key))
    keys.clear()


def _any_critical(results: Sequence[StageResult]) -> bool:
    return any(issue.severity == "critical" for result in results for issue in result.issues)
