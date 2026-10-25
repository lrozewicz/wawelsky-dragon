"""Katalogi SDK spoza zakresu E2 — jedna syntetyczna pozycja na katalog (E2-3b1/T4).

Plik **własny** Wawelsky Dragon (nie kopia upstreamu, patrz `README.md` sekcja „Klient SDK:
`test_sdk_api/`"). Upstreamowe katalogi `test_agent_management/`, `test_memory_management/`
i `test_message_management/` dotyczą przestrzeni tras, których WD w E2 nie ma i nie będzie mieć
(`docs/architecture/02-api.md` §5.6 „Nigdy — stuby": `/agents*`, `/memories*`, `/messages*`; nie ma
ich też w `backend/openapi.json`), więc ich kopii w `test_sdk_api/` nie ma — miejsce w raporcie
trzymają trzy pozycje poniżej (bez kopiowania plików upstreamu, CONTRACT WP E2-3b1 §Pominięcia).

Pomija je lista `SKIPPED` harnessu (`upstream/conftest.py`, stała zadania `_SDK_OUT_OF_SCOPE`,
wzór S-341/S-350): `pytest_collection_modifyitems` dokłada pozycjom spod `upstream/` marker
`contract` oraz marker `skip` z powodem `SKIPPED.md#S-44x`. Dzięki temu przy `-m contract -rs`
pominięcie jest jawne, a przy każdym innym `-m` (krok `binaries` verify-full) pozycje są
odfiltrowane. Pominięcie z markera nie sięga po fixture'y, więc plik nie startuje stosu WD.

`pytest.skip` w ciele testu to siatka bezpieczeństwa: gdyby wzorzec nodeidu przestał pasować do
pozycji, powód pominięcia nadal wskazuje wiersz `SKIPPED.md`.
"""

from __future__ import annotations

import pytest


def test_agent_management() -> None:
    """`test_agent_management/` (6 funkcji `def test_` w v0.27.2): trasy `/agents*` — S-440."""
    pytest.skip("SKIPPED.md#S-440")


def test_memory_management() -> None:
    """`test_memory_management/` (31 funkcji `def test_`): trasy `/memories*` — S-441."""
    pytest.skip("SKIPPED.md#S-441")


def test_message_management() -> None:
    """`test_message_management/` (25 funkcji `def test_`): trasy `/messages*` — S-442."""
    pytest.skip("SKIPPED.md#S-442")
