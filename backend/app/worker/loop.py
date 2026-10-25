"""Pętla workera: sloty claim→handler, heartbeat zadań, reaper, graceful stop (K5 §2.3, C9).

Stałe modułowe (REAPER_INTERVAL_S, SHUTDOWN_GRACE_S, ERROR_BACKOFF_S) czytane z modułu
w chwili użycia — testy podmieniają je przez ``monkeypatch.setattr(loop, ...)``.
Wyjątki z bazy w claimie, zapisie wyniku, heartbeacie zadania, reapera i worker_heartbeat
nie zabijają pętli — są logowane, a pętla próbuje dalej (brief T6).
"""

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import Mapping
from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.errors import WDError
from app.core.logging import task_id_var
from app.core.version import APP_VERSION
from app.db.repositories import worker_heartbeat as worker_heartbeat_repo
from app.db.uow import transaction
from app.worker.context import Handler, TaskContext
from app.worker.errors import TaskCancelled, TaskLost
from app.worker.queue import DbTaskQueue, TaskQueue, TaskRow

REAPER_INTERVAL_S: float = 60.0
SHUTDOWN_GRACE_S: float = 60.0
ERROR_BACKOFF_S: float = 1.0

Outcome = Literal["complete", "cancelled", "lost", "fail_transient", "fail_permanent"]

logger = logging.getLogger("app.worker")


def host_name() -> str:
    """Nazwa hosta skrócona do 40 znaków — pierwsza część identyfikatora workera (C9)."""
    return socket.gethostname()[:40]


def make_worker_id(slot: int | None = None) -> str:
    """Identyfikator procesu (klucz worker_heartbeat) albo slotu: "host:pid[:slot]" (C9)."""
    process_id = f"{host_name()}:{os.getpid()}"
    return process_id if slot is None else f"{process_id}:{slot}"


def classify(exc: BaseException | None) -> Outcome:
    """Wynik handlera → outcome; WDError wg atrybutu transient, inny Exception → transient (C9)."""
    if exc is None:
        return "complete"
    if isinstance(exc, TaskCancelled):
        return "cancelled"
    if isinstance(exc, TaskLost):
        return "lost"
    if isinstance(exc, WDError):
        transient = getattr(exc, "transient", False) is True
        return "fail_transient" if transient else "fail_permanent"
    return "fail_transient"


def _capabilities(handlers: Mapping[str, Handler]) -> dict[str, Any]:
    """Zdolności workera do wpisu worker_heartbeat (kontrakt C10)."""
    return {"task_types": sorted(handlers), "ocr_available": False}


class Worker:
    """Pula slotów wykonujących zadania z DbTaskQueue + pętle reapera i worker_heartbeat (C9)."""

    def __init__(self, container: Container, handlers: Mapping[str, Handler]) -> None:
        """Składanie bez I/O; run() wymaga kontenera po start() (kontrakt C9)."""
        self._container = container
        self._handlers: dict[str, Handler] = dict(handlers)

    async def run(self, stop: asyncio.Event) -> None:
        """Startuje sloty, reapera i worker_heartbeat; po stop.set() wraca bez wyjątku (C9)."""
        sessionmaker = cast("async_sessionmaker[AsyncSession]", self._container.sessionmaker)
        queue = DbTaskQueue(sessionmaker, self._container.clock, self._container.id_gen)
        worker_id = make_worker_id()
        await self._container.storage.ensure_layout()
        # Zadania po padzie naszego hosta (ten sam host, inny pid) wracają do kolejki.
        released = await queue.release_own_host(make_worker_id(0))
        if released > 0:
            logger.info(
                "released tasks of previous worker incarnation",
                extra={"event": "task_released_own_host", "count": released},
            )
        now = self._container.clock.now_ms()
        async with transaction(sessionmaker) as session:
            await worker_heartbeat_repo.upsert(
                session,
                worker_id=worker_id,
                started_at=now,
                heartbeat_at=now,
                capabilities=_capabilities(self._handlers),
                version=APP_VERSION,
            )
        slots = [
            asyncio.create_task(self._run_slot(slot, stop, queue), name=f"worker-slot-{slot}")
            for slot in range(self._container.settings.worker_concurrency)
        ]
        reaper_task = asyncio.create_task(self._run_reaper(stop, queue), name="worker-reaper")
        beat_task = asyncio.create_task(
            self._run_worker_heartbeat(stop, sessionmaker, worker_id),
            name="worker-heartbeat",
        )
        await stop.wait()
        # Grace na dokończenie bieżących zadań; sloty bezczynne budzi samo stop.set().
        _, pending = await asyncio.wait(slots, timeout=SHUTDOWN_GRACE_S)
        for slot_task in pending:
            slot_task.cancel()
        reaper_task.cancel()
        beat_task.cancel()
        await asyncio.gather(*slots, reaper_task, beat_task, return_exceptions=True)

    async def _run_slot(self, slot: int, stop: asyncio.Event, queue: TaskQueue) -> None:
        """Pętla slotu: claim → wykonanie; bez zadania czeka poll_s na stop (C9)."""
        worker_id = make_worker_id(slot)
        while not stop.is_set():
            try:
                task = await queue.claim(worker_id, list(self._handlers))
            except Exception:
                # Przejściowy błąd DB przy claimie: log i ponowienie po backoffie (brief T6).
                logger.exception("claim failed")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), ERROR_BACKOFF_S)
                continue
            if task is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self._container.settings.worker_poll_s)
                continue
            await self._run_task(task, worker_id, queue)

    async def _run_task(self, task: TaskRow, worker_id: str, queue: TaskQueue) -> None:
        """Wykonanie jednego claimniętego zadania: handler + heartbeat w tle + zapis wyniku."""
        token = task_id_var.set(task.id)
        try:
            logger.info(
                "task claimed", extra={"event": "task_claimed", "task_type": task.task_type}
            )
            ctx_logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
                logging.getLogger("app.worker.task"), {"task_id": task.id}
            )
            ctx = TaskContext(
                task=task,
                worker_id=worker_id,
                container=self._container,
                logger=ctx_logger,
                queue=queue,
            )
            outcome, exc = await self._execute(task, worker_id, queue, ctx)
            await self._save_result(task, worker_id, queue, outcome, exc)
        finally:
            # Reset zawsze — także przy raise z gałęzi shutdown (brief T6, wymaganie 3).
            task_id_var.reset(token)

    async def _execute(
        self, task: TaskRow, worker_id: str, queue: TaskQueue, ctx: TaskContext
    ) -> tuple[Outcome, BaseException | None]:
        """Handler jako asyncio.Task + heartbeat w tle; zwraca wynik do zapisu (kontrakt C9)."""
        lost = False

        async def handler() -> None:
            await self._handlers[task.task_type](task, ctx)

        async def heartbeat() -> None:
            nonlocal lost
            while True:
                await asyncio.sleep(self._container.settings.task_heartbeat_s)
                try:
                    alive = await queue.heartbeat(task.id, worker_id, None, None)
                except Exception:
                    # Chwilowy błąd DB nie oznacza utraty zadania; następna próba po interwale.
                    logger.warning("task heartbeat failed", exc_info=True)
                    continue
                if not alive:
                    # Zadanie przejął reaper/obcy worker — przerywamy handler bez zapisu.
                    lost = True
                    handler_task.cancel()
                    return

        handler_task = asyncio.create_task(handler(), name=f"handler-{task.id}")
        hb_task = asyncio.create_task(heartbeat(), name=f"heartbeat-{task.id}")
        exc: BaseException | None = None
        outcome: Outcome = "complete"
        try:
            await handler_task
        except asyncio.CancelledError:
            if lost:
                outcome = "lost"
            else:
                # Anulowano slot (shutdown): handler do stopu, zadanie wraca do kolejki.
                handler_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await handler_task
                await queue.release(task.id, worker_id)
                raise
        except Exception as err:
            exc = err
            outcome = classify(err)
            logger.warning("handler failed", exc_info=err)
        else:
            outcome = classify(None)
        finally:
            hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb_task
        return outcome, exc

    async def _save_result(
        self,
        task: TaskRow,
        worker_id: str,
        queue: TaskQueue,
        outcome: Outcome,
        exc: BaseException | None,
    ) -> None:
        """Zapis wyniku; wyjątek z bazy tylko logujemy — zadanie przejmie reaper (brief T6)."""
        try:
            await self._record(task, worker_id, queue, outcome, exc)
        except Exception:
            logger.exception("recording task result failed")

    async def _record(
        self,
        task: TaskRow,
        worker_id: str,
        queue: TaskQueue,
        outcome: Outcome,
        exc: BaseException | None,
    ) -> None:
        """Zapis wyniku zadania w kolejce + zdarzenie logu (kontrakt C9)."""
        if outcome == "lost":
            return  # zadanie nie jest już nasze — worker nic nie zapisuje
        if outcome == "complete":
            await queue.complete(task.id, worker_id)
            return
        if outcome == "cancelled":
            await queue.mark_cancelled(task.id, worker_id)
            return
        err = cast("BaseException", exc)  # outcome fail_* powstaje tylko z wyjątku
        status = await queue.fail(task.id, worker_id, err, transient=outcome == "fail_transient")
        if status == "queued":
            logger.info(
                "task back to queue",
                extra={"event": "task_retried", "attempts": task.attempts + 1},
            )
        elif status == "dead":
            logger.warning("task exceeded attempts", extra={"event": "task_dead"})
        else:  # failed — brak zdarzenia w EVENTS, log bez `event` (kontrakt C9)
            logger.warning("task failed", extra={"task_id": task.id})

    async def _run_reaper(self, stop: asyncio.Event, queue: TaskQueue) -> None:
        """Co REAPER_INTERVAL_S: zadania bez tętna wracają do kolejki (kontrakt C9)."""
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), REAPER_INTERVAL_S)
            if stop.is_set():
                return
            try:
                reaped = await queue.reap_stale(self._container.settings.task_stale_s)
            except Exception:
                # Przejściowy błąd DB: reaper żyje, kolejna próba w następnym interwale (brief T6).
                logger.exception("reaping stale tasks failed")
                continue
            if reaped > 0:
                logger.info("reaped stale tasks", extra={"event": "task_reaped", "count": reaped})

    async def _run_worker_heartbeat(
        self,
        stop: asyncio.Event,
        sessionmaker: async_sessionmaker[AsyncSession],
        worker_id: str,
    ) -> None:
        """Upsert worker_heartbeat co task_heartbeat_s; startowy robi run() (kontrakt C9/C10)."""
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), self._container.settings.task_heartbeat_s)
            if stop.is_set():
                return
            try:
                now = self._container.clock.now_ms()
                async with transaction(sessionmaker) as session:
                    await worker_heartbeat_repo.upsert(
                        session,
                        worker_id=worker_id,
                        started_at=now,
                        heartbeat_at=now,
                        capabilities=_capabilities(self._handlers),
                        version=APP_VERSION,
                    )
            except Exception:
                # Przejściowy błąd DB: pętla worker_heartbeat żyje (brief T6).
                logger.exception("worker heartbeat failed")
