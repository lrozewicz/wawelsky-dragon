"""Test kontraktowy replay scenariusza file_legacy vs złoto v0.27.2 (E4-5b T1).

Odchyłki: ``deviations/file_legacy.yaml`` (K11 §5 p. 5). Wzór: ``test_files.py``.
"""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_file_legacy_matches_golden(replay, compare_dir) -> None:
    """Replay całego scenariusza file_legacy: zero niezaakceptowanych Diffów."""
    diffs = compare_dir(
        replay("file_legacy"), GOLDEN_DIR / "v0.27.2", "file_legacy", scenarios_dir=SCENARIOS_DIR
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "file_legacy.yaml"))
    assert problems == [], "\n".join(problems)
