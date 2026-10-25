"""Test scenariusza złota retrieval (kontrakt E1-9a C7; wzór: test_documents_parse.py)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_retrieval(replay, compare_dir) -> None:
    """Replay retrieval vs złoto v0.27.2: jedynie 2 odchyłki z CONTRACT C6."""
    diffs = compare_dir(
        replay("retrieval"),
        GOLDEN_DIR / "v0.27.2",
        "retrieval",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "retrieval.yaml"))
    assert problems == [], "\n".join(problems)
