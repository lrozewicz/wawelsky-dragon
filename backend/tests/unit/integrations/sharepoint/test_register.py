"""Testy rejestracji konektora SharePoint (WP E4-2b/T4, wymaganie 0) — unit, bez bazy."""

from collections.abc import Iterator

import pytest

from app.core.config import Settings
from app.core.container import Container
from app.integrations import registry
from app.integrations.sharepoint.connector import SharePointConnector
from app.integrations.sharepoint.register import register_sharepoint
from app.worker.main import create_worker


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """Rejestr jest globalny — czyścimy przed i po teście (kontrakt register.py)."""
    registry.clear()
    yield
    registry.clear()


def test_register_sharepoint_uses_given_connector() -> None:
    """Podany konektor i loader z kontenera lądują pod typem ``sharepoint`` (wymaganie 0)."""
    connector = SharePointConnector()

    register_sharepoint(Container(Settings(env="test")), connector)

    registered, load_config = registry.get("sharepoint")
    assert registered is connector
    assert callable(load_config)
    assert registry.registered_types() == ["sharepoint"]


def test_register_sharepoint_defaults_to_production_connector() -> None:
    """Bez argumentu rejestruje produkcyjny ``SharePointConnector`` (kontrakt register.py)."""
    register_sharepoint(Container(Settings(env="test")))

    registered, _ = registry.get("sharepoint")
    assert isinstance(registered, SharePointConnector)
    assert registered.type == "sharepoint"


def test_create_worker_registers_sharepoint() -> None:
    """``create_worker`` woła rejestrację — typ ``sharepoint`` jest w rejestrze (wymaganie 0)."""
    create_worker(Settings(env="test"))

    assert "sharepoint" in registry.registered_types()
    registered, _ = registry.get("sharepoint")
    assert isinstance(registered, SharePointConnector)
