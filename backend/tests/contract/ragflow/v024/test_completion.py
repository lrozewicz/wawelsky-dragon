"""Test kontraktowy replay completion vs złoto v0.24.0 (C5) — odchyłki w deviations/v0.24.0/completion.yaml."""  # noqa: E501

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_V024_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_completion_matches_golden(replay, compare_dir) -> None:
    """Replay completion zgadza się ze złotem v0.24.0 (JSON i SSE): zero niezaakceptowanych Diff."""
    diffs = compare_dir(
        replay("completion", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "completion",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "completion.yaml"))
    assert problems == [], "\n".join(problems)
