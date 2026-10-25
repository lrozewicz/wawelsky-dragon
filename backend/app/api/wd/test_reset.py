"""Trasa resetu testowego (K9) — router rejestrowany tylko gdy ``settings.env == "test"``.

Bez uwierzytelniania (07 B14 — wyjątek jawnie dopuszczony dla trybu test).
"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import container_of, json_body
from app.services.reset import ResetService

router = APIRouter(prefix="/api/wd/v1/test")

# Wywołania resetu serializowane w procesie api (K9 §3).
_LOCK = asyncio.Lock()


@router.post("/reset")
async def reset(request: Request) -> JSONResponse:
    """Pełny reset stanu testowego; wynik w kopercie ``{"data": ...}`` (K9 §4)."""
    body = await json_body(request)
    settings = container_of(request).settings
    email = body.get("admin_email")
    admin_email = (
        email if isinstance(email, str) and email else settings.admin_email or "admin@wd.test"
    )
    password = body.get("admin_password")
    admin_password = (
        password
        if isinstance(password, str) and password
        else settings.admin_password.get_secret_value() or "wd-test-admin-1"
    )
    async with _LOCK:
        result = await ResetService(container_of(request)).reset(
            admin_email=admin_email, admin_password=admin_password
        )
    return JSONResponse({"data": result})
