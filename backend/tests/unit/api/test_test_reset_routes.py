"""Rejestracja trasy resetu testowego — tylko przy WD_ENV=test (K9 §1, §5 p. 2).

Bez bazy: TestClient bez ``with`` — lifespan nie startuje, 404 nie dotyka kontenera.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container
from app.main import create_app

_NOT_FOUND = 404

_RESET = "/api/wd/v1/test/reset"

# Sekrety produkcyjne wymagane przez walidator Settings w env="prod" (K8 część A).
_PROD = {
    "db_password": "x",
    "secret_key": "s" * 48,
    "crypto_key": "ab" * 32,
    "llm_base_url": "http://llm",
}


@pytest.fixture(autouse=True)
def _clean_wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Izolacja od WD_* z env procesu — Settings() czyta tylko to, co test ustawi."""
    for name in list(os.environ):
        if name.startswith("WD_"):
            monkeypatch.delenv(name)


def _route_paths(app: FastAPI) -> Iterator[str]:
    """Ścieżki wszystkich tras aplikacji.

    ``route.path`` działa dla płaskich tras; routery dołączone ``include_router``
    to na FastAPI 0.141 leniwe ``_IncludedRouter`` bez ``.path`` — ich ścieżki
    czytamy z ``effective_candidates().path``.
    """
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            yield path
            continue
        for candidate in route.effective_candidates():
            yield str(candidate.path)


def _client(settings: Settings) -> tuple[TestClient, FastAPI]:
    """Aplikacja bez startu lifespan; zwraca (client, app)."""
    app = create_app(settings, Container(settings))
    return TestClient(app), app


def test_reset_route_absent_in_dev() -> None:
    """WD_ENV=dev: POST /test/reset → 404 w kopercie wd; trasy brak w routes i OpenAPI."""
    client, app = _client(Settings(env="dev"))
    response = client.post(_RESET)
    assert response.status_code == _NOT_FOUND
    assert response.json() == {
        "error": {"code": "not_found", "message": f"Not Found: {_RESET}", "details": None}
    }
    assert _RESET not in set(_route_paths(app))
    assert _RESET not in app.openapi()["paths"]


def test_reset_route_absent_in_prod() -> None:
    """WD_ENV=prod: POST /test/reset → 404 w kopercie wd; trasy brak w routes i OpenAPI."""
    client, app = _client(Settings(env="prod", **_PROD))
    response = client.post(_RESET)
    assert response.status_code == _NOT_FOUND
    assert response.json() == {
        "error": {"code": "not_found", "message": f"Not Found: {_RESET}", "details": None}
    }
    assert _RESET not in set(_route_paths(app))
    assert _RESET not in app.openapi()["paths"]


def test_reset_route_present_in_test() -> None:
    """WD_ENV=test: trasa /test/reset obecna w app.routes i w OpenAPI (K9 §1)."""
    _unused_client, app = _client(Settings(env="test"))
    assert _RESET in set(_route_paths(app))
    assert _RESET in app.openapi()["paths"]
