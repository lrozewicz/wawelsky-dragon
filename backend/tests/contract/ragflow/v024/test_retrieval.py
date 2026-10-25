"""Test kontraktowy replay retrieval vs złoto v0.24.0 (CONTRACT C0 p. 4)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_retrieval_v024_matches_golden(replay, compare_dir) -> None:
    """Replay retrieval vs złoto v0.24.0 (POST /retrieval na sparsowanym datasecie)."""
    diffs = compare_dir(
        replay("retrieval", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "retrieval",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "retrieval.yaml"))
    assert problems == [], "\n".join(problems)
