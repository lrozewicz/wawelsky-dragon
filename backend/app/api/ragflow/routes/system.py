"""Trasy /api/v1/system/*, /api/v1/language i alias /v1/system/healthz (złoto system--01..06, 10).

Kształty odpowiedzi: schemas/system.py; sondy i tętna workerów: services/system_info.py.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.api.auth.principal import PrincipalDep, container_of
from app.api.ragflow.envelope import ok
from app.api.ragflow.schemas.common import RagflowOk
from app.api.ragflow.schemas.system import Language, SystemHealthz, SystemStats, SystemStatus
from app.services.system_info import ComponentProbe, SystemInfoService, SystemStatusRecord

router = APIRouter(prefix="/api/v1", tags=["system"])
# Alias zgodności /v1/system/healthz — bez wpisu w OpenAPI (K11 §10c p. 12, K6 §2 p. 12).
legacy_router = APIRouter(tags=["system"])

# Wersja protokołu zgodności: upstream v0.27.2 oddaje własny tag (common/versions.py), a złoto
# (system--02.json) wymaga dosłownie "v0.27.2" (brief SYS p. 1).
COMPAT_VERSION = "v0.27.2"

# Blok doc_engine sondy /system/status: WD nie ma wyszukiwarki dokumentów (chunki i wektory
# trzyma MariaDB), więc sonda nie jest wykonywana, a kształt bierzemy 1:1 ze złota
# (system--06.json) — pole bez odpowiednika w WD (brief SYS p. 2).
DOC_ENGINE: dict[str, Any] = {
    "type": "elasticsearch",
    "status": "green",
    "cluster_name": "docker-cluster",
    "active_primary_shards": 4,
    "active_shards": 4,
    "active_shards_percent_as_number": 100.0,
    "delayed_unassigned_shards": 0,
    "initializing_shards": 0,
    "number_of_data_nodes": 1,
    "number_of_in_flight_fetch": 0,
    "number_of_nodes": 1,
    "number_of_pending_tasks": 0,
    "relocating_shards": 0,
    "task_max_waiting_in_queue_millis": 0,
    "timed_out": False,
    "unassigned_shards": 0,
    "elapsed": "0.0",
}

# Typ magazynu w sondzie storage: WD trzyma pliki na lokalnym systemie plików
# (FilesystemStorage, K5 §1.3) — odpowiednik upstreamowego `settings.STORAGE_IMPL_TYPE`.
STORAGE_TYPE = "local"


def _nok(ok_flag: bool) -> str:
    """Wartość sondy healthz jak upstream (health_utils._ok_nok): „ok”/„nok”."""
    return "ok" if ok_flag else "nok"


def _elapsed(probe: ComponentProbe) -> str:
    """Czas sondy w formacie upstreamu: milisekundy z jednym miejscem po przecinku."""
    return f"{probe.elapsed_ms:.1f}"


def healthz_body(db_ok: bool, storage_ok: bool) -> dict[str, str]:
    """Surowe ciało /system/healthz (bez koperty, złoto system--04.json).

    Sondy WD są dwie (baza, storage). `doc_engine` i `redis` nie mają odpowiednika w WD
    (brak wyszukiwarki dokumentów i Redisa — kolejka zadań siedzi w MariaDB, K5 §2), więc
    oddajemy „ok”, tak jak sondy k8s i frontend upstreamu (brief SYS p. 2).
    """
    return {
        "db": _nok(db_ok),
        "doc_engine": "ok",
        "redis": "ok",
        "status": _nok(db_ok and storage_ok),
        "storage": _nok(storage_ok),
    }


def status_body(record: SystemStatusRecord) -> dict[str, Any]:
    """Data /system/status (upstream system_api.py:73, złoto system--06.json).

    `database.database` = "mysql": WD stoi na MariaDB (protokół MySQL). `redis` jest blokiem
    zgodności (elapsed 0.0 — sondy nie ma w WD), a `storage` pokazuje realny magazyn WD.
    """
    return {
        "database": {
            "database": "mysql",
            "status": "green" if record.database.ok else "red",
            "elapsed": _elapsed(record.database),
        },
        "doc_engine": dict(DOC_ENGINE),
        "redis": {"status": "green", "elapsed": "0.0"},
        "storage": {
            "storage": STORAGE_TYPE,
            "status": "green" if record.storage.ok else "red",
            "elapsed": _elapsed(record.storage),
        },
        "task_executor_heartbeats": record.heartbeats,
    }


def stats_body() -> dict[str, list[object]]:
    """Data /system/stats (upstream stats_api.py:24, złoto system--10.json).

    Serie dotyczą konwersacji API (upstream `API4ConversationService`); WD ich nie prowadzi
    (metryki operacyjne są w `/api/wd/v1/stats`, 02 §12) — sześć pustych serii.
    """
    return {"pv": [], "uv": [], "speed": [], "tokens": [], "round": [], "thumb_up": []}


@router.get(
    "/system/ping",
    operation_id="system_ping",
    responses={
        200: {
            "description": "Zawsze „pong” jako text/html (upstream Quart; złoto system--01.json)",
            "content": {"text/html": {"schema": {"type": "string"}}},
        }
    },
)
async def ping() -> Response:
    """Sonda życia bez uwierzytelnienia: dosłownie „pong” (złoto system--01.json)."""
    return Response("pong", media_type="text/html")


@router.get(
    "/system/version",
    operation_id="system_version",
    responses={200: {"model": RagflowOk[str]}},
)
async def version() -> JSONResponse:
    """Wersja protokołu zgodności (złoto system--02.json)."""
    return ok(COMPAT_VERSION)


@router.get(
    "/system/healthz",
    operation_id="system_healthz",
    responses={
        200: {"model": SystemHealthz},
        500: {"model": SystemHealthz, "description": "Komponent nieosiągalny (upstream: 500)"},
    },
)
async def healthz(request: Request) -> JSONResponse:
    """Surowe (bez koperty) zdrowie komponentów; 200 gdy wszystko ok, inaczej 500."""
    db_ok, storage_ok = await SystemInfoService(container_of(request)).healthz()
    status_code = 200 if db_ok and storage_ok else 500
    return JSONResponse(healthz_body(db_ok, storage_ok), status_code=status_code)


@router.get(
    "/system/status",
    operation_id="system_status",
    responses={200: {"model": RagflowOk[SystemStatus]}},
)
async def status(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Status komponentów i tętna workerów; wymaga klucza API (złoto system--06.json)."""
    return ok(status_body(await SystemInfoService(container_of(request)).status()))


@router.get(
    "/system/stats",
    operation_id="system_stats",
    responses={200: {"model": RagflowOk[SystemStats]}},
)
async def stats(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Puste serie statystyk konwersacji API (złoto system--10.json)."""
    return ok(stats_body())


@router.get(
    "/language",
    operation_id="system_language",
    responses={200: {"model": RagflowOk[Language]}},
)
async def language() -> JSONResponse:
    """Język backendu dla SPA (upstream v0.27.2 system_api.py:66; złoto system--05.json)."""
    return ok({"language": "python"})


@legacy_router.get(
    "/v1/system/healthz", operation_id="system_healthz_legacy", include_in_schema=False
)
async def healthz_legacy(request: Request) -> JSONResponse:
    """Alias zgodności /v1/system/healthz — istnieje w obu wersjach (złoto system--19.json)."""
    return await healthz(request)
