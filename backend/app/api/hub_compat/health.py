"""Health powierzchni hub-compat — `GET /api/health` bez auth i bez koperty (kontrakt C7)."""

from fastapi import APIRouter

router = APIRouter(include_in_schema=False)


@router.get("/api/health")
async def health() -> dict[str, str]:
    """`{"status": "ok"}` — jedyna trasa SVC bez `X-API-Secret` (AG-30)."""
    return {"status": "ok"}
