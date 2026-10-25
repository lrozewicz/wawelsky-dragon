"""Test scenariusza złota chunks_list (kontrakt E1-9a C7; wzór: test_documents_parse.py)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_chunks_list(replay, compare_dir) -> None:
    """Replay chunks_list vs złoto v0.27.2: jedynie 2 odchyłki z C6 (content, positions)."""
    diffs = compare_dir(
        replay("chunks_list"),
        GOLDEN_DIR / "v0.27.2",
        "chunks_list",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "chunks_list.yaml"))
    assert problems == [], "\n".join(problems)
