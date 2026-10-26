"""Pętla workera prowadząca pody RunPod: postęp stanów, start parsowania i kasowanie po pracy.

Wzorzec jak ``outline_sweep``: przebieg co ``INTERVAL_S`` aż do ``stop``; błąd przebiegu jest
logowany i nie zatrzymuje pętli. Bez aktywnych wdrożeń przebieg to jedno zapytanie do bazy.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.container import Container
from app.services.runpod.lifecycle import tick

INTERVAL_S: float = 15.0

logger = logging.getLogger("app.worker")


async def runpod_loop(
    container: Container, stop: asyncio.Event, *, interval_s: float | None = None
) -> None:
    """Przebieg ``tick`` co ``interval_s`` (domyślnie ``INTERVAL_S``) do ``stop.set()``."""
    wait_s = INTERVAL_S if interval_s is None else interval_s
    while not stop.is_set():
        try:
            await tick(container)
        except Exception:
            logger.exception("runpod loop failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=wait_s)
