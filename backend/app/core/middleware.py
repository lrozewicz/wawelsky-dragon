"""Middleware kontekstu żądania: X-Request-ID, request.state, log dostępu (kontrakt C9)."""

import logging
import re
import time

from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import api_space
from app.core.ids import new_id
from app.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")


def is_valid_request_id(value: str) -> bool:
    """True dla 1-128 znaków [A-Za-z0-9._-] (K3 §4)."""
    return _REQUEST_ID_RE.fullmatch(value) is not None


class RequestContextMiddleware:
    """Czysty ASGI: nadaje/przepisuje X-Request-ID, ustawia state i loguje dostęp."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = Headers(scope=scope).get(REQUEST_ID_HEADER) or ""
        if not is_valid_request_id(rid):
            rid = new_id()
        space = api_space(scope["path"])
        # Przez scope["state"], żeby request.state.request_id widział też handler 500
        # z ServerErrorMiddleware, który leży NA ZEWNĄTRZ tego middleware (C9 pkt 3).
        state = scope.setdefault("state", {})
        state["request_id"] = rid
        state["api_space"] = space
        token = request_id_var.set(rid)
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = rid
            await send(message)

        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status = 500
            raise
        finally:
            logging.getLogger("app.http").info(
                "http_request",
                extra={
                    "event": "http_request",
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "api_space": space,
                },
            )
            request_id_var.reset(token)


# Media type'y, dla których dokładamy CSP: typy aktywne renderowane przez przeglądarkę.
_ACTIVE_MEDIA_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/xml",
        "application/xml",
    }
)
# Odpowiedzi maszynowe — parytet K11, bez zmian nagłówków.
_MACHINE_MEDIA_TYPES = frozenset({"application/json", "text/event-stream"})


class SecurityHeadersMiddleware:
    """Czysty ASGI: nagłówki bezpieczeństwa dla odpowiedzi plikowych (H3, DEC-213).

    ``nosniff`` dla każdej odpowiedzi poza JSON/SSE, a ``CSP: sandbox`` dodatkowo dla typów
    aktywnych (HTML/XML/SVG). Media type bierzemy z ``Content-Type`` odpowiedzi (nie żądania).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                content_type = headers.get("content-type", "")
                media_type = content_type.split(";", 1)[0].strip().lower()
                if media_type not in _MACHINE_MEDIA_TYPES:
                    headers["X-Content-Type-Options"] = "nosniff"
                    if media_type in _ACTIVE_MEDIA_TYPES:
                        headers["Content-Security-Policy"] = "sandbox"
            await send(message)

        await self.app(scope, receive, send_wrapper)


def install_middleware(app: FastAPI, settings: Settings) -> None:
    """CORS (opcjonalnie), potem SecurityHeaders, na końcu RequestContext (zewnętrzny)."""
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
