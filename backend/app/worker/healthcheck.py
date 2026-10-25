"""Healthcheck workera — ``python -m app.worker.healthcheck`` (K5 §2.4, kontrakt C9).

Kod 0, gdy w ``worker_heartbeat`` jest świeże tętno tego hosta; inaczej 1. Wyjście ciche
(bez ``configure_logging``); wyjątek (np. brak DB) kończy proces kodem ≠ 0 bez try/except.
"""

import asyncio
import sys

from app.core.config import Settings
from app.core.timeutil import now_ms
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories.worker_heartbeat import has_recent
from app.db.uow import transaction
from app.worker.loop import host_name

HEALTH_MAX_AGE_S = 60


async def check(settings: Settings) -> bool:
    """True, gdy ten host ma tętno młodsze niż ``HEALTH_MAX_AGE_S`` (kontrakt C9)."""
    engine = make_engine(settings)
    try:
        async with transaction(make_sessionmaker(engine)) as session:
            return await has_recent(
                session, host=host_name(), since_ms=now_ms() - HEALTH_MAX_AGE_S * 1000
            )
    finally:
        await engine.dispose()


def main() -> int:
    """0 gdy świeże tętno, 1 w przeciwnym razie (kontrakt C9)."""
    return 0 if asyncio.run(check(Settings())) else 1


if __name__ == "__main__":
    sys.exit(main())
