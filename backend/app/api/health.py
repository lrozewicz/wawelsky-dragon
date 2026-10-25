"""Router zdrowia: liveness (kontrakt C11) i readiness (kontrakt C6)."""

from fastapi import APIRouter

from app.api.deps import ReadinessDep
from app.api.ragflow.schemas.common import WdError
from app.core.error_codes import RetCode
from app.core.errors import WDError

router = APIRouter(tags=["health"])


class NotReady(WDError):
    """Baza niegotowa: 503 w kopercie wd (K3 §2 nie definiuje 503 — klasa lokalna routera)."""

    code = RetCode.CONNECTION_ERROR
    http_status = 503
    slug = "not_ready"


@router.get("/health/live", operation_id="health_live")
async def live() -> dict[str, str]:
    """Proces działa — zawsze 200 {"status": "ok"}."""
    return {"status": "ok"}


@router.get(
    "/health/ready",
    operation_id="health_ready",
    responses={503: {"model": WdError, "description": "Baza niegotowa (koperta wd, K3 #4)"}},
)
async def ready(reason: ReadinessDep) -> dict[str, str]:
    """200 {"status": "ready"} gdy baza gotowa; inaczej 503 z przyczyną."""
    if reason is not None:
        raise NotReady(reason)
    return {"status": "ready"}
