"""Test scenariusza złota openai_dify w profilu v0.24.0 (brief T4 p. 1; wzór: v027)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_V024_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_openai_dify_v024(replay, compare_dir) -> None:
    """Replay openai_dify vs złoto v0.24.0: zero niezgodnych Diffów, zero martwych odchyłek."""
    diffs = compare_dir(
        replay("openai_dify", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "openai_dify",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "openai_dify.yaml"))
    assert problems == [], "\n".join(problems)
