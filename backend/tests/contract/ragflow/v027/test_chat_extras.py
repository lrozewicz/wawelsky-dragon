"""Test scenariusza złota chat_extras (kontrakt E2-1 C1; wzór: test_datasets_crud.py)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_chat_extras(replay, compare_dir) -> None:
    """Replay chat_extras vs złoto v0.27.2: zero niezgodnych Diffów, zero odchyłek."""
    diffs = compare_dir(
        replay("chat_extras"),
        GOLDEN_DIR / "v0.27.2",
        "chat_extras",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "chat_extras.yaml"))
    assert problems == [], "\n".join(problems)
