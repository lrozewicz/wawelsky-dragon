"""Testy SecurityHeadersMiddleware (H3, kontrakt WP E5-2a T1, DEC-213).

Tabela z briefu: JSON/SSE bez nagłówków; HTML/SVG/XML → nosniff + CSP sandbox;
PDF i inne typy → tylko nosniff. Odpowiedzi JSON/SSE pozostają bez zmian (parytet K11).

Wyrocznia: ``uv run pytest tests/unit/core/test_security_headers.py -q``.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.responses import Response
from starlette.testclient import TestClient

from app.core.config import Settings
from app.core.middleware import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_middleware,
)

NOSNIFF = "x-content-type-options"
CSP = "content-security-policy"
HTTP_OK = 200


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/json")
    async def json_route() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/html")
    async def html_route() -> Response:
        return Response("<html></html>", media_type="text/html")

    @app.get("/svg")
    async def svg_route() -> Response:
        return Response("<svg/>", media_type="image/svg+xml")

    @app.get("/pdf")
    async def pdf_route() -> Response:
        return Response(b"%PDF-1.4", media_type="application/pdf")

    @app.get("/sse")
    async def sse_route() -> Response:
        return Response("data: x\n\n", media_type="text/event-stream")

    app.add_middleware(SecurityHeadersMiddleware)
    return app


def test_install_middleware_mounts_security_headers_inside_request_context() -> None:
    """Montaż: SecurityHeaders jest, a RequestContext pozostaje najbardziej zewnętrzny (C9)."""
    app = FastAPI()
    install_middleware(app, Settings(env="test"))
    classes = [m.cls for m in app.user_middleware]
    assert SecurityHeadersMiddleware in classes
    assert app.user_middleware[0].cls is RequestContextMiddleware


def test_json_response_has_no_security_headers() -> None:
    r = TestClient(_app()).get("/json")
    assert r.status_code == HTTP_OK
    assert NOSNIFF not in r.headers
    assert CSP not in r.headers


def test_event_stream_has_no_security_headers() -> None:
    r = TestClient(_app()).get("/sse")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert NOSNIFF not in r.headers
    assert CSP not in r.headers


def test_pdf_gets_only_nosniff() -> None:
    r = TestClient(_app()).get("/pdf")
    assert r.headers[NOSNIFF] == "nosniff"
    assert CSP not in r.headers


def test_html_gets_nosniff_and_csp_sandbox() -> None:
    r = TestClient(_app()).get("/html")
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers[NOSNIFF] == "nosniff"
    assert r.headers[CSP] == "sandbox"


def test_svg_gets_nosniff_and_csp_sandbox() -> None:
    r = TestClient(_app()).get("/svg")
    assert r.headers[NOSNIFF] == "nosniff"
    assert r.headers[CSP] == "sandbox"
