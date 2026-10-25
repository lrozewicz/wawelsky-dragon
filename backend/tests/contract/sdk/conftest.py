"""Fixture'y smoke'u oficjalnego SDK (T3, E2-2z).

``tests/contract/ragflow/conftest.py`` nie obejmuje katalogu ``sdk/``, więc fixture
sesyjny ``wd_server`` jest tu zdefiniowany od nowa (te same 4 linie, bez importowania
cudzego conftestu).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.contract.ragflow.harness import WdServer, start_server


@pytest.fixture(scope="session")
def wd_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[WdServer]:
    """Stos WD (api+worker) na świeżej bazie — jeden na sesję pytest."""
    tmp = tmp_path_factory.mktemp("wd_server")
    with start_server(tmp) as server:
        yield server
