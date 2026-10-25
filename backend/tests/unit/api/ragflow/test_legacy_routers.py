"""Testy routerów legacy ``/v1`` i ``/api/v1`` (K11 §10d p. 18-19, CONTRACT C6).

Rejestracja obu routerów nie może zmienić ``backend/openapi.json``: ``legacy_v1``
jest poza schematem (``include_in_schema=False``) i niesie trasy systemowe oraz dokumentów
v0.24 (E2-2a T3-T4); ``legacy_v024`` niesie trasę ``/sessions/ask`` (T6a, CONTRACT C4).
"""

from typing import cast
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.routing import APIRoute, _IncludedRouter

from app.api.auth.principal import get_principal
from app.api.ragflow.routes import include_ragflow_routes, legacy_v024, legacy_v1
from app.core.config import Settings
from app.main import create_app

# Trasy ``legacy_v1`` w kolejności deklaracji (E2-2a T3 i T4) — ścieżki i metody ze złota v0.24.0
# scenariuszy system (kroki 16-25) i documents_extras (kroki 17-32). ``GET /v1/system/healthz``
# ma alias w ``routes/system.py`` (krok ``versions: ALL``) i nie jest tu duplikowany.
LEGACY_V1_ROUTES: tuple[tuple[str, str], ...] = (
    ("/v1/system/ping", "GET"),
    ("/v1/system/version", "GET"),
    ("/v1/system/config", "GET"),
    ("/v1/system/status", "GET"),
    ("/v1/system/token_list", "GET"),
    ("/v1/system/new_token", "POST"),
    ("/v1/system/token/{token:path}", "DELETE"),
    ("/v1/api/stats", "GET"),
    ("/v1/llm/my_llms", "GET"),
    ("/v1/document/change_status", "POST"),
    ("/v1/document/run", "POST"),
    ("/v1/document/upload_info", "POST"),
    ("/v1/document/get/{document_id}", "GET"),
    ("/v1/document/thumbnails", "GET"),
)

# Kroki scenariusza system z ``auth: none`` (złoto 16, 18, 19) — tylko one są publiczne;
# reszta /v1/* idzie JWT-em (upstream ``@login_required``, krok ``auth: jwt``).
LEGACY_V1_PUBLIC_PATHS: tuple[str, ...] = ("/v1/system/ping", "/v1/system/config")


def test_legacy_v1_has_v024_alias_routes_and_is_hidden() -> None:
    """legacy_v1: prefiks /v1, trasy system v0.24, poza schematem OpenAPI (K11 §10d p. 17)."""
    assert legacy_v1.router.prefix == "/v1"
    assert legacy_v1.router.include_in_schema is False
    routes = tuple((route.path, next(iter(route.methods))) for route in legacy_v1.router.routes)
    assert routes == LEGACY_V1_ROUTES
    assert "/v1/system/healthz" not in [path for path, _method in routes]


def test_legacy_v1_auth_matches_scenario() -> None:
    """Tylko ``ping`` i ``config`` są publiczne; pozostałe trasy /v1 wymagają JWT (16-25)."""
    for route in legacy_v1.router.routes:
        api_route = cast(APIRoute, route)
        requires_auth = any(dep.call is get_principal for dep in api_route.dependant.dependencies)
        assert requires_auth is (api_route.path not in LEGACY_V1_PUBLIC_PATHS), api_route.path


def test_legacy_v024_has_ask_route() -> None:
    """legacy_v024: prefiks /api/v1 i jedyna trasa ``POST /sessions/ask`` (E2-2b T6a)."""
    assert legacy_v024.router.prefix == "/api/v1"
    assert [route.path for route in legacy_v024.router.routes] == ["/api/v1/sessions/ask"]


def test_legacy_routers_registered_last() -> None:
    """include_ragflow_routes dołącza oba routery legacy na końcu (identyczność obiektów)."""
    recorder = MagicMock()
    include_ragflow_routes(recorder)  # type: ignore[arg-type]
    included = [call.args[0] for call in recorder.include_router.call_args_list]
    assert included[-2:] == [legacy_v1.router, legacy_v024.router]


def test_legacy_routers_in_app() -> None:
    """Oba routery trafiają do aplikacji FastAPI (wpis ``_IncludedRouter``).

    FastAPI 0.141 dołącza routery leniwie — pusty router nie wnosi trasy ``Route``,
    więc obecność sprawdzamy po ``original_router`` wpisu księgowego.
    """
    app: FastAPI = create_app(Settings(env="test"))
    included = [route.original_router for route in app.routes if isinstance(route, _IncludedRouter)]
    assert legacy_v1.router in included
    assert legacy_v024.router in included
