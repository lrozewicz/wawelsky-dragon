"""Test kontraktowy replay scenariusza file_legacy vs złoto v0.24.0 (E4-5b T4).

Odchyłki: ``deviations/v0.24.0/file_legacy.yaml`` (CONTRACT E4-5b §D5: DEC-201/202/203).
Wzór: ``test_errors_access.py`` (replay v0.24 z nagłówkiem zgodności, komparator złota).
"""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_V024_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_file_legacy_v024_matches_golden(replay, compare_dir) -> None:
    """Replay całego scenariusza file_legacy v0.24.0: zero niezaakceptowanych Diffów."""
    diffs = compare_dir(
        replay("file_legacy", "v0.24.0"),
        GOLDEN_DIR / "v0.24.0",
        "file_legacy",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_V024_DIR / "file_legacy.yaml"))
    assert problems == [], "\n".join(problems)
