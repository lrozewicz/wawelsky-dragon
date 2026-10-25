"""Rejestr konektorów integracji (K12 §3).

W E4-1 rejestr produkcyjny jest pusty — SharePoint rejestruje E4-2, testy rejestrują
``FakeConnector`` (``tests/fakes/integrations.py``).
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.integrations.base import Connector

if TYPE_CHECKING:
    from app.db.repositories.integrations import IntegrationRow

# Wiersz integracji (+ tabela typu) -> cfg konektora z odszyfrowanym sekretem.
ConfigLoader = Callable[["IntegrationRow"], Awaitable[object]]

_registry: dict[str, tuple[Connector, ConfigLoader]] = {}


def register(type_: str, connector: Connector, load_config: ConfigLoader) -> None:
    """Rejestruje konektor i loader konfiguracji pod typem."""
    _registry[type_] = (connector, load_config)


def get(type_: str) -> tuple[Connector, ConfigLoader]:
    """Zwraca (konektor, loader) dla typu; nieznany typ -> ``KeyError``."""
    return _registry[type_]


def registered_types() -> list[str]:
    """Zwraca posortowane typy zarejestrowanych konektorów."""
    return sorted(_registry)


def clear() -> None:
    """Czyści rejestr (tylko testy)."""
    _registry.clear()
