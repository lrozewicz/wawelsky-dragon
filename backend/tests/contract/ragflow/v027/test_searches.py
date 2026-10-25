"""Test kontraktowy replay scenariusza searches vs złoto v0.27.2 (E4-4a T5).

Odchyłki: ``deviations/searches.yaml`` (K11 §5 p. 5). Wzór: ``test_completion.py``.
"""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_searches_matches_golden(replay, compare_dir) -> None:
    """Replay całego scenariusza searches: zero niezaakceptowanych Diffów."""
    diffs = compare_dir(
        replay("searches"), GOLDEN_DIR / "v0.27.2", "searches", scenarios_dir=SCENARIOS_DIR
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "searches.yaml"))
    assert problems == [], "\n".join(problems)
