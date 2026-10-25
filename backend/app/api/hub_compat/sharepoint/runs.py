"""Trasy SVC historii synchronizacji `/api/integrations/runs*` (03 §5, kontrakt E4-3a §4).

Odpowiednik `hub-compat/raglow-service/sharepoint-sync/src/routes/runs.ts`. Router musi być
montowany PRZED `integrations.router` (`sharepoint/__init__.py`): ścieżka `/api/integrations/runs`
ma tyle samo segmentów co `/api/integrations/{id}`, więc kolejność decyduje o tym, że `runs`
nie jest czytane jako `id` integracji.

Parametry zapytania są deklarowane jako `str | None` i parsowane ręcznie — FastAPI nie waliduje
ich, więc trasa nigdy nie odpowiada 422, a komunikaty błędów są dosłownie z oryginału (§4).
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.hub_compat.envelope import data
from app.api.hub_compat.route import SvcRoute
from app.api.hub_compat.security import require_secret
from app.api.hub_compat.sharepoint.dto import event_dto, run_dto
from app.api.hub_compat.sharepoint.setup import integration_service
from app.core.errors import ValidationFailed

router = APIRouter(
    route_class=SvcRoute,
    include_in_schema=False,
    dependencies=[Depends(require_secret)],
)

INVALID_RUN_ID = "Invalid run id"
INVALID_INTEGRATION_ID = "Invalid integration_id"
INVALID_LEVEL = "Invalid level (use info|warn|error)"
VALID_LEVELS = frozenset({"info", "warn", "error"})

RUNS_LIMIT_FALLBACK = 50  # parseIntParam(limit, 50, 1, 200) — runs.ts:70
RUNS_LIMIT_MIN = 1
RUNS_LIMIT_MAX = 200
EVENTS_LIMIT_FALLBACK = 500  # parseIntParam(limit, 500, 1, 2000) — runs.ts:109
EVENTS_LIMIT_MIN = 1
EVENTS_LIMIT_MAX = 2000
AFTER_ID_FALLBACK = 0
AFTER_ID_MAX = 2**53 - 1  # Number.MAX_SAFE_INTEGER z oryginału — runs.ts:108


def _js_number(raw: str) -> float | None:
    """Liczba z query param jak `Number(raw)`; `None` gdy nie jest skończona (`!isFinite`).

    Odpowiednik JS: pusty string to `0`, a `Infinity`/`NaN`/tekst dają `None`. `Number` czyta
    też prefiksy typu `0x10` — tu odpadają (nieznaczące dla tras z liczbami dziesiętnymi).
    """
    try:
        number = float(raw.strip() or "0")
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _int_param(raw: str | None, fallback: int, minimum: int, maximum: int) -> int:
    """Liczba całkowita z query param z clampem (`parseIntParam`, runs.ts:44-49).

    Brak parametru albo wartość niebędąca liczbą → `fallback`; inaczej obcięcie do całości
    i clamp do `[minimum, maximum]`.
    """
    if raw is None:
        return fallback
    number = _js_number(raw)
    if number is None:
        return fallback
    return min(max(math.trunc(number), minimum), maximum)


def _run_id(raw: str) -> int:
    """`{run_id}`: nie-liczba lub wartość ≤ 0 → 400 „Invalid run id” (runs.ts:57-60)."""
    number = _js_number(raw)
    if number is None or number <= 0:
        raise ValidationFailed(INVALID_RUN_ID)
    return math.trunc(number)


@router.get("/api/integrations/runs")
async def list_runs(
    request: Request,
    integration_type: str | None = Query(default=None, alias="type"),
    integration_id: str | None = None,
    limit: str | None = None,
) -> JSONResponse:
    """Przebiegi wszystkich typów integracji malejąco po `id` (runs.ts:64-105)."""
    parsed_id: int | None = None
    if integration_id:
        number = _js_number(integration_id)
        if number is None:
            raise ValidationFailed(INVALID_INTEGRATION_ID)
        parsed_id = math.trunc(number)
    runs = await integration_service(request).list_runs(
        integration_type=integration_type or None,
        integration_id=parsed_id,
        limit=_int_param(limit, RUNS_LIMIT_FALLBACK, RUNS_LIMIT_MIN, RUNS_LIMIT_MAX),
    )
    return data([run_dto(run) for run in runs])


@router.get("/api/integrations/runs/{run_id}/events")
async def list_events(
    request: Request,
    run_id: str,
    after_id: str | None = None,
    level: str | None = None,
    limit: str | None = None,
) -> JSONResponse:
    """Zdarzenia przebiegu rosnąco po `id`, z `after_id` i filtrem `level` (runs.ts:107-133)."""
    parsed_run_id = _run_id(run_id)
    if level and level not in VALID_LEVELS:
        raise ValidationFailed(INVALID_LEVEL)  # przed odpytaniem bazy (kontrakt §4)
    events = await integration_service(request).list_events(
        parsed_run_id,
        after_id=_int_param(after_id, AFTER_ID_FALLBACK, 0, AFTER_ID_MAX),
        level=level or None,
        limit=_int_param(limit, EVENTS_LIMIT_FALLBACK, EVENTS_LIMIT_MIN, EVENTS_LIMIT_MAX),
    )
    return data([event_dto(event) for event in events])
