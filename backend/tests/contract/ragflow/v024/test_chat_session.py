"""Test kontraktowy replay chat_session vs złoto v0.24.0 (CONTRACT C4, C5)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_chat_session_matches_golden(replay, compare_dir) -> None:
    """Replay chat_session zgadza się ze złotem v0.24.0 (JSON i SSE): zero niezaakceptowanych Diff."""  # noqa: E501
    diffs = compare_dir(
        replay("chat_session", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "chat_session",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "chat_session.yaml"))
    assert problems == [], "\n".join(problems)
