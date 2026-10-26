"""Przerywanie pracy w toku po Stop: ``check_cancel`` odpytywany w tle, nie tylko między stronami.

Rozpoznawanie stron (OCR/VLM na zdalnym GPU) trwa długo, a ``check_cancel`` sprawdza flagę
w bazie dopiero przed KOLEJNĄ stroną — Stop czekał więc, aż skończą się wszystkie strony w toku
(u nas 16 naraz, ponad minutę). Obserwator anuluje je od razu po ustawieniu flagi.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

CANCEL_POLL_S = 2.0  # jedno tanie zapytanie o flagę co tyle sekund


async def _poll(check_cancel: Callable[[], Awaitable[None]]) -> None:
    while True:
        await asyncio.sleep(CANCEL_POLL_S)
        await check_cancel()  # rzuca TaskCancelled/TaskLost


async def run_with_cancel_watch[T](
    work: Awaitable[T], check_cancel: Callable[[], Awaitable[None]] | None
) -> T:
    """Czeka na ``work``; gdy ``check_cancel`` rzuci, anuluje ``work`` i propaguje wyjątek."""
    if check_cancel is None:
        return await work
    job = asyncio.ensure_future(work)
    watcher = asyncio.create_task(_poll(check_cancel), name="cancel-watch")
    try:
        await asyncio.wait({job, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if not job.done():
            watcher.result()  # obserwator zakończył się wyjątkiem (Stop) — rzuć go
        return job.result()
    finally:
        watcher.cancel()
        if not job.done():
            job.cancel()
        await asyncio.gather(job, watcher, return_exceptions=True)
