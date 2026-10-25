"""Test kontraktowy replay scenariusza files vs złoto v0.27.2 (E4-5a T6).

Odchyłki: ``deviations/files.yaml`` (K11 §5 p. 5). Wzór: ``test_searches.py``.
"""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_files_matches_golden(replay, compare_dir) -> None:
    """Replay całego scenariusza files: zero niezaakceptowanych Diffów."""
    diffs = compare_dir(
        replay("files"), GOLDEN_DIR / "v0.27.2", "files", scenarios_dir=SCENARIOS_DIR
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "files.yaml"))
    assert problems == [], "\n".join(problems)
