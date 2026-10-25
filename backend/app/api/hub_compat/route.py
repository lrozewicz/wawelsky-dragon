"""APIRoute powierzchni hub-compat — jedyne miejsce zamiany wyjątku na kopertę SVC (kontrakt C7)."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

from app.api.hub_compat.envelope import svc_error
from app.core.errors import WDError

# Kształt handlera trasy w FastAPI/Starlette (APIRoute.get_route_handler).
RouteHandler = Callable[[Request], Coroutine[Any, Any, Response]]


class SvcRoute(APIRoute):
    """Trasa routerów hub-compat: `WDError` i `RequestValidationError` → `svc_error` (C7).

    Wyjątki z zależności (np. `require_secret`) wracają tą samą drogą, bo FastAPI
    rozwiązuje zależności wewnątrz handlera zwróconego przez `get_route_handler`.
    """

    def get_route_handler(self) -> RouteHandler:
        """Handler z własnym `try/except` — reszta aplikacji widzi tylko kopertę SVC."""
        original = super().get_route_handler()

        async def svc_handler(request: Request) -> Response:
            try:
                return await original(request)
            except (WDError, RequestValidationError) as exc:
                return svc_error(exc)

        return svc_handler
