"""Test kontraktowy replay errors_access vs złoto v0.24.0 (K11 §10c-§10d, golden-E2)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_errors_access_v024_matches_golden(replay, compare_dir) -> None:
    """Replay errors_access vs złoto v0.24.0: niezgodne Diffy tylko z sankcjonowanych odchyłek."""
    diffs = compare_dir(
        replay("errors_access", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "errors_access",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "errors_access.yaml"))
    assert problems == [], "\n".join(problems)
