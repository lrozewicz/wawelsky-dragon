"""Test kontraktowy replay documents_extras vs złoto v0.24.0 (CONTRACT C0 p. 4)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_documents_extras_v024_matches_golden(replay, compare_dir) -> None:
    """Replay documents_extras vs złoto v0.24.0 (ingest, statusy, metadane, preview)."""
    diffs = compare_dir(
        replay("documents_extras", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "documents_extras",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "documents_extras.yaml"))
    assert problems == [], "\n".join(problems)
