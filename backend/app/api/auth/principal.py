"""Rozpoznawanie podmiotu z nagłówka Authorization i wspólne zależności tras (C9, 07 §2)."""

import json
from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.container import Container
from app.core.error_codes import MSG_AUTH_HEADER_MISSING
from app.core.errors import Unauthorized
from app.domain.policy import Principal
from app.services.auth import AuthService

# Porównanie case-insensitive na pierwszych 7 znakach nagłówka (07 §2 p. 1).
_BEARER = "bearer "


async def get_principal(request: Request) -> Principal:
    """Principal z tokenu w nagłówku Authorization; wynik cache'owany w request.state (07 §2 p. 5).

    Gdy request.state ma już principal — zwracamy go bez ponownego uwierzytelniania.
    """
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cast(Principal, cached)
    # 07 §2: prefiks sprawdzany na surowej wartości — samo „Bearer ” daje pusty token → 401.
    value = request.headers.get("authorization", "")
    value = value[7:].strip() if value[:7].lower() == _BEARER else value.strip()
    if not value:
        raise Unauthorized(MSG_AUTH_HEADER_MISSING)
    container = container_of(request)
    principal = await cast(AuthService, container.auth).authenticate(value)
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def container_of(request: Request) -> Container:
    """Kontener aplikacji z obiektu request (C9)."""
    return cast(Container, request.app.state.container)


def client_ip(request: Request) -> str:
    """IP klienta albo pusty string, gdy brak (C9)."""
    return request.client.host if request.client else ""


async def json_body(request: Request) -> dict[str, object]:
    """Ciało JSON żądania: puste, uszkodzone albo nie-dict → {} (C9)."""
    raw = await request.body()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
