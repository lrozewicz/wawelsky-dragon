"""Przegląd workera uzupełniający profile spisu istniejących dokumentów (K21 §2 p. 4).

Worker przy starcie i potem co ``WD_OUTLINE_SWEEP_S`` sekund (domyślnie 600; 0 = wyłączone)
kolejkuje zadania ``build_outline`` dla dokumentów ``run='3'`` bez wiersza w
``document_profiles`` — porcjami ≤ 50, bez duplikatów (zadanie ``queued``/``running`` z tym
samym ``document_id`` już w kolejce → pomijamy). Kolejne przeglądy podejmują resztę porcji,
bo po wykonaniu zadania dokument ma już profil. Priorytet ``-1`` (tło). Wzorzec pętli jak
``app.worker.kb_cleanup``: pierwszy przebieg zaraz po starcie, zegar wstrzykiwany, błąd
przebiegu logowany bez zatrzymywania pętli.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.container import Container
from app.core.timeutil import Clock
from app.db.repositories import document_profiles, task_lookup
from app.db.uow import transaction
from app.worker.queue import DbTaskQueue, NewTask

# Porcja przeglądu: najwyżej tyle dokumentów na jeden przebieg (K21 §2 p. 4).
SWEEP_BATCH = 50

logger = logging.getLogger("app.worker")


async def sweep_once(container: Container) -> int:
    """Jeden przebieg przeglądu: kolejkuje ``build_outline`` dla porcji bez profilu (K21 §2 p. 4).

    Zwraca liczbę zakolejkowanych zadań. Dokument z zadaniem ``build_outline`` w stanie
    ``queued``/``running`` jest pomijany (bez duplikatów).
    """
    sessionmaker = container.sessionmaker
    if sessionmaker is None:  # pragma: no cover — kontener workera zawsze po start()
        raise RuntimeError("container not started")
    async with transaction(sessionmaker) as session:
        document_ids = await document_profiles.ids_without_profile(session, SWEEP_BATCH)
        active = await task_lookup.active_build_outline_documents(session, document_ids)
    queue = DbTaskQueue(sessionmaker, container.clock, container.id_gen)
    enqueued = 0
    for document_id in document_ids:
        if document_id in active:
            continue
        await queue.enqueue(
            NewTask(
                task_type="build_outline",
                payload={"document_id": document_id},
                document_id=document_id,
                priority=-1,
            )
        )
        enqueued += 1
    if enqueued:
        logger.info("outline sweep enqueued", extra={"event": "outline_sweep", "count": enqueued})
    return enqueued


async def outline_sweep_loop(
    container: Container,
    stop: asyncio.Event,
    *,
    interval_s: float | None = None,
    clock: Clock | None = None,
) -> None:
    """Przegląd przy starcie, potem co ``interval_s`` aż do ``stop`` (K21 §2 p. 4).

    ``interval_s`` domyślnie z ``Settings.outline_sweep_s``; wartość ≤ 0 wyłącza przegląd
    (pętla kończy się od razu). Czekanie to ``stop.wait()`` z limitem, nie ``sleep`` —
    zatrzymanie workera kończy pętlę natychmiast, a brak ``stop`` nie blokuje pierwszego
    przebiegu. Błąd jednego przebiegu (np. restart MariiDB) jest logowany i nie zabija pętli.
    """
    interval = interval_s if interval_s is not None else container.settings.outline_sweep_s
    if interval <= 0:
        logger.info("outline sweep disabled")
        return
    while not stop.is_set():
        try:
            await sweep_once(container)
        except Exception:
            logger.exception("outline sweep pass failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), interval)
