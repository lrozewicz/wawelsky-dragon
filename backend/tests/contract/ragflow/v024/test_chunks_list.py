"""Test kontraktowy replay chunks_list vs złoto v0.24.0 (CONTRACT C0 p. 4)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_chunks_list_v024_matches_golden(replay, compare_dir) -> None:
    """Replay chunks_list vs złoto v0.24.0 (lista chunków sparsowanego dokumentu)."""
    diffs = compare_dir(
        replay("chunks_list", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "chunks_list",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "chunks_list.yaml"))
    assert problems == [], "\n".join(problems)
