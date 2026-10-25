"""Test kształtów K6 §5 p. 4 (CONTRACT C4.2): odpowiedzi realnego serwera WD
vs modele 200 z openapi.json.

Kompletność jest sprawdzana przez fixture ``validated_components`` (scope="module"), a nie przez
globalny zbiór budowany przez osobne testy — dzięki temu wynik nie zależy od rozkładu testów
pytest-xdist (każdy worker, na którym wyląduje choć jeden test tego modułu, uruchamia całą sumę
przepływów).
"""

from collections.abc import Iterator

import httpx
import pytest

from tests.contract.ragflow.harness import start_server
from tests.integration.api import (
    shapes_chats,
    shapes_datasets,
    shapes_files,
    shapes_providers,
    shapes_searches,
)
from tests.integration.api.openapi_shapes import response_components

pytestmark = [pytest.mark.db, pytest.mark.fakellm]
ADMIN = ("admin@wd.test", "wd-test-admin-1")


@pytest.fixture(scope="module")
def wd_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[httpx.Client]:
    """Klient HTTP stawiającego się serwera WD (świeża baza, klucz API z resetu K9)."""
    with start_server(tmp_path_factory.mktemp("shapes")) as server:
        api_key = server.reset()
        with httpx.Client(
            base_url=server.base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=120
        ) as client:
            yield client


@pytest.fixture(scope="module")
def validated_components(wd_client: httpx.Client) -> set[str]:
    """Suma komponentów zwalidowanych przez 5 przepływów — raz na worker, niezależnie od rozkładu
    testów.

    Przepływy: T2 (K6 §5 p. 4 — ``datasets``/``documents``/``chunks``/``retrieval``), T3
    (``auth``/``users``/``system``/``chats``/``sessions``/``completions``), T5 (K13 §3 — instancje
    dostawcy i modele instancji), T2b (K15 §3 — trasy wyszukiwania), T10 (K16 §2 — menedżer plików).
    """
    validated: set[str] = set()
    validated.update(shapes_datasets.flow(wd_client))
    validated.update(shapes_chats.flow(wd_client, ADMIN))
    validated.update(shapes_providers.flow(wd_client))
    validated.update(shapes_searches.flow(wd_client))
    validated.update(shapes_files.flow(wd_client))
    return validated


def test_datasets_shapes(validated_components: set[str]) -> None:
    """Przepływ T2 waliduje kształty datasets/documents/chunks/retrieval (K6 §5 p. 4)."""
    assert validated_components


def test_chats_shapes(validated_components: set[str]) -> None:
    """Przepływ T3 waliduje kształty auth/users/system/chats/sessions/completions."""
    assert validated_components


def test_providers_shapes(validated_components: set[str]) -> None:
    """Przepływ T5 waliduje kształty instancji dostawcy i modeli instancji (K13 §3)."""
    assert validated_components


def test_searches_shapes(validated_components: set[str]) -> None:
    """Przepływ T2b waliduje kształty tras wyszukiwania (K15 §3)."""
    assert validated_components


def test_files_shapes(validated_components: set[str]) -> None:
    """Przepływ T10 waliduje kształty tras menedżera plików (K16 §2)."""
    assert validated_components


def test_all_response_components_validated(validated_components: set[str]) -> None:
    """Asercja kompletności (K6 §5 p. 4): każdy komponent odpowiedzi /api/v1 zwalidowany."""
    assert response_components() == validated_components, (
        f"brak walidacji: {sorted(response_components() - validated_components)}; "
        f"nadmiar: {sorted(validated_components - response_components())}"
    )
