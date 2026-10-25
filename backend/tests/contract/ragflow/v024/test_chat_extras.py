"""Test kontraktowy replay chat_extras vs złoto v0.24.0 (CONTRACT C4, C5)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_chat_extras_v024_matches_golden(replay, compare_dir) -> None:
    """Replay chat_extras vs złoto v0.24.0 (PUT czatu, related_questions, ask SSE)."""
    diffs = compare_dir(
        replay("chat_extras", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "chat_extras",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "chat_extras.yaml"))
    assert problems == [], "\n".join(problems)
