"""Trasa statystyk WD ``GET /api/wd/v1/stats`` (kontrakt E3-6a §2 ``stats_get``, §4).

Dane pochodzą z ``SystemInfoService`` (ten sam serwis obsługuje ``GET /system/status``
powierzchni ragflow: sondy bazy i storage oraz tętna workerów) i z zapytania o stany
kolejki; wersja z ``app.core.version``. Odpowiedź nie zawiera ścieżek storage ani sekretów
konfiguracji — modele ``schemas.py`` mają dokładnie pola z kontraktu §3.
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Request, status

from app.api.auth.principal import container_of
from app.api.hub_compat.sharepoint.dto import iso_ms
from app.api.wd.common import Envelope, require_admin, wd_responses
from app.api.wd.system.schemas import Probe, QueueInfo, Stats, Worker, WorkersInfo
from app.core.version import APP_VERSION
from app.services.system_info import ComponentProbe, SystemInfoService, SystemStatusRecord

router = APIRouter(
    prefix="/api/wd/v1",
    tags=["stats"],
    dependencies=[Depends(require_admin)],
)

# Okno aktywności workera: tętno nie starsze niż 60 s (kontrakt E3-6a §4).
WORKER_ACTIVE_WINDOW_MS = 60_000


def _probe(probe: ComponentProbe) -> Probe:
    """Sonda usługi → model odpowiedzi WD (kontrakt §3)."""
    return Probe(ok=probe.ok, elapsed_ms=probe.elapsed_ms)


def _worker(worker_id: str, beats: list[dict[str, object]], now_ms: int) -> Worker:
    """Pierwsze tętno workera → ``Worker``; ``active`` wg okna 60 s (kontrakt §3-§4)."""
    first = beats[0]
    heartbeat_at = cast(int, first["heartbeat_at"])
    return Worker(
        worker_id=worker_id,
        version=cast("str | None", first.get("version")),
        started_at=iso_ms(cast("int | None", first.get("started_at"))),
        heartbeat_at=iso_ms(heartbeat_at),
        active=now_ms - heartbeat_at <= WORKER_ACTIVE_WINDOW_MS,
        capabilities=first.get("capabilities"),
    )


def _workers(record: SystemStatusRecord, now_ms: int) -> WorkersInfo:
    """Tętna workerów → ``WorkersInfo`` (``items`` i liczba aktywnych; kontrakt §3)."""
    items = [_worker(worker_id, beats, now_ms) for worker_id, beats in record.heartbeats.items()]
    return WorkersInfo(active=sum(1 for worker in items if worker.active), items=items)


@router.get(
    "/stats",
    operation_id="stats_get",
    summary="Statystyki systemu",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[Stats],
    responses=wd_responses(400, 401, 403),
)
async def get_stats(request: Request) -> Envelope[Stats]:
    """Wersja, sondy bazy i storage, tętna workerów oraz stany kolejki (kontrakt §4)."""
    container = container_of(request)
    service = SystemInfoService(container)
    record = await service.status()
    queue = await service.queue_counts()
    return Envelope[Stats](
        data=Stats(
            version=APP_VERSION,
            database=_probe(record.database),
            storage=_probe(record.storage),
            workers=_workers(record, container.clock.now_ms()),
            queue=QueueInfo(
                queued=queue["queued"],
                running=queue["running"],
                dead=queue["dead"],
            ),
        )
    )
