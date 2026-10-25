"""Test kontraktowy replay datasets_crud vs złoto v0.24.0 (CONTRACT C0 p. 4)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_datasets_crud_v024_matches_golden(replay, compare_dir) -> None:
    """Replay datasets_crud vs złoto v0.24.0 (tworzenie, lista, aktualizacja, usunięcie)."""
    diffs = compare_dir(
        replay("datasets_crud", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "datasets_crud",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "datasets_crud.yaml"))
    assert problems == [], "\n".join(problems)
