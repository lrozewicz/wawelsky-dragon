"""Catch-all powierzchni hub-compat — montowany wyłącznie pod `/user-api` (kontrakt C7).

Pod `""` catch-allu nie ma: `/api/v1/*` (RF) i `/api/wd/v1/*` (WD) muszą zostać swoje
(AG-31) — dlatego ten router nie trafia do pętli prefiksów w `include_hub_compat_routers`.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.hub_compat.route import SvcRoute
from app.api.hub_compat.security import require_secret
from app.core.errors import NotFound

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]

router = APIRouter(
    route_class=SvcRoute,
    include_in_schema=False,
    dependencies=[Depends(require_secret)],
)


@router.api_route("/{rest:path}", methods=_METHODS)
async def fallback(rest: str) -> JSONResponse:
    """Nieznana trasa pod `/user-api` → 404 `{"error": "Not found"}` (C7, AG-31)."""
    raise NotFound("Not found")
