"""Test scenariusza złota documents_parse (kontrakt E1-9a C7; wzór: test_datasets_crud.py)."""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import DEVIATIONS_DIR, GOLDEN_DIR, SCENARIOS_DIR

pytestmark = pytest.mark.contract


def test_documents_parse(replay, compare_dir) -> None:
    """Replay documents_parse vs złoto v0.27.2: zero niezgodnych Diffów, zero odchyłek."""
    diffs = compare_dir(
        replay("documents_parse"),
        GOLDEN_DIR / "v0.27.2",
        "documents_parse",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "documents_parse.yaml"))
    assert problems == [], "\n".join(problems)
