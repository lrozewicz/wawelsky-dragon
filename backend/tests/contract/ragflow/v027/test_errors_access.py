"""Test scenariusza złota errors_access (kontrakt E2-1 C1; wzór: test_datasets_crud.py)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_errors_access(replay, compare_dir) -> None:
    """Replay errors_access vs złoto v0.27.2: zero niezgodnych Diffów, zero odchyłek."""
    diffs = compare_dir(
        replay("errors_access"),
        GOLDEN_DIR / "v0.27.2",
        "errors_access",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "errors_access.yaml"))
    assert problems == [], "\n".join(problems)
