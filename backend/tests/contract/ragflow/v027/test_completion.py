"""Test kontraktowy replay completion vs złoto v0.27.2 (K6 §6) — odchyłki w deviations/completion.yaml."""  # noqa: E501 (treść docstringa wiążąca dosłownie — CONTRACT C5)

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_completion_matches_golden(replay, compare_dir) -> None:
    """Replay completion zgadza się ze złotem v0.27.2: zero niezaakceptowanych Diff."""
    diffs = compare_dir(
        replay("completion"), GOLDEN_DIR / "v0.27.2", "completion", scenarios_dir=SCENARIOS_DIR
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "completion.yaml"))
    assert problems == [], "\n".join(problems)
