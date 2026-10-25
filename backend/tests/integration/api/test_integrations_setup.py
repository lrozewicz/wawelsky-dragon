"""Instalacja i montowanie powierzchni integracji w `create_app` (brief T4 p. 7, 8, 11).

Baza nie jest potrzebna: `create_app` bez wejścia w lifespan nie otwiera połączeń.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.integrations import registry
from app.main import create_app
from app.services.integrations import IntegrationService


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Rejestr konektorów jest globalny — czyścimy przed i po teście (kontrakt §5)."""
    registry.clear()
    yield
    registry.clear()


def _route_paths(app: FastAPI) -> set[str]:
    """Ścieżki tras aplikacji; routery z `include_router` to leniwe `_IncludedRouter`.

    Wzorzec z `tests/unit/api/test_test_reset_routes.py::_route_paths`.
    """
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
            continue
        for candidate in route.effective_candidates():
            paths.add(str(candidate.path))
    return paths


def test_create_app_registers_sharepoint_and_service() -> None:
    """`integrations_enabled=True` → konektor w rejestrze i usługa w `app.state` (brief p. 7)."""
    app = create_app(Settings(env="test", hub_compat_routes=True, integrations_enabled=True))
    assert registry.registered_types() == ["sharepoint"]
    assert isinstance(app.state.integrations, IntegrationService)


def test_create_app_without_integrations_skips_setup() -> None:
    """`integrations_enabled=False` → pusty rejestr i brak `app.state.integrations`."""
    app = create_app(Settings(env="test", hub_compat_routes=True, integrations_enabled=False))
    assert registry.registered_types() == []
    assert not hasattr(app.state, "integrations")


def test_integration_routes_mounted_under_both_prefixes() -> None:
    """Trasy integracji są pod `""` i `/sharepoint-sync-api` (brief p. 8, 11)."""
    app = create_app(Settings(env="test", hub_compat_routes=True, integrations_enabled=True))
    paths = _route_paths(app)
    assert "/api/integrations" in paths
    assert "/sharepoint-sync-api/api/integrations" in paths
    assert "/sharepoint-sync-api/api/integrations/{id}/sync" in paths
    assert "/sharepoint-sync-api/api/health" in paths
    assert "/sharepoint-sync-api/{rest:path}" in paths
