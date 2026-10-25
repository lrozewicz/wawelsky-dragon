"""Test scenariusza złota metadata_e6 (K11 §10f; wzór: test_documents_extras.py).

Scenariusz recordera: ``tools/contract-recorder/scenarios/metadata_e6.yaml`` — metadane
(``metadata_condition`` na liście dokumentów, ``metadata/config`` dokumentu, ``meta_data_filter``
w ``/retrieval`` i w completions czatu, auto-metadane przez ``parser_config.enable_metadata``).
Kroki czatu wymagają modelu — koperta resetu (K9 §3 p. 4) zasiewa modele ``fake-*``, tak samo jak
``test_completion.py``; harness ``start_server`` nie wymaga tu niczego więcej.

Oznaczenie ``xfail`` zdjęto po T3b (E6-1a): luki K11 §10f naprawione (T2/T3/T3b,
``work/wp/E6-1a/reports/T1-gaps.md``); pozostałe różnice to odchyłki w
``deviations/metadata_e6.yaml``.
"""

import pytest

from tests.contract.ragflow.compare import load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_DIR,
    GOLDEN_DIR,
    SCENARIOS_DIR,
    load_runner,
)

pytestmark = pytest.mark.contract


def test_metadata_e6(replay, compare_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replay metadata_e6 vs złoto v0.27.2: komunikat podaje listę niezgodnych Diffów."""
    # DEC-299: runner przerywa replay na pierwszym kroku z `expect` innym niż złoto (kroki 30,
    # 34, 37-39 — WD nie odtwarza kwirków upstreamu, np. KeyError('value') → code 100), więc
    # compare_dir nigdy nie liczy Diffów. Wyłączamy tylko `check_expect`; `status` i `body.code`
    # i tak porównuje compare_dir. Kroki bez `expect` nadal chroni runner (HTTP>=400/code!=0).
    monkeypatch.setattr(load_runner(), "check_expect", lambda *args, **kwargs: None)
    diffs = compare_dir(
        replay("metadata_e6"),
        GOLDEN_DIR / "v0.27.2",
        "metadata_e6",
        scenarios_dir=SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "metadata_e6.yaml"))
    assert problems == [], "\n".join(problems)
