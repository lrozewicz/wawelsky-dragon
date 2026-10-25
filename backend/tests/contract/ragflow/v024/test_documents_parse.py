"""Test kontraktowy replay documents_parse vs złoto v0.24.0 (CONTRACT C0 p. 4)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_documents_parse_v024_matches_golden(replay, compare_dir) -> None:
    """Replay documents_parse vs złoto v0.24.0 (upload, start parsowania, pobranie)."""
    diffs = compare_dir(
        replay("documents_parse", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "documents_parse",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "documents_parse.yaml"))
    assert problems == [], "\n".join(problems)
