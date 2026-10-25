"""Unit testy `compare_dir` — pliki brakujące/nadmiarowe i reguły z właściwego kroku scenariusza."""

import json
from pathlib import Path

import yaml

from tests.contract.ragflow.compare import Diff, compare_dir

REQUEST = {"method": "GET", "path": "/api/v1/x", "query": {}, "body": None}


def _write(root: Path, relative: str, description: str) -> None:
    """Zapisuje plik odpowiedzi złota z jednym polem `description` pod body.data."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "request": REQUEST,
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {"code": 0, "data": {"description": description}},
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _scenario(path: Path, *, with_rules: bool) -> None:
    """Scenariusz YAML: krok 1 bez reguł, krok 2 z regułą exact na data.description."""
    steps: list[dict[str, object]] = [
        {"id": "one", "method": "GET", "path": "/api/v1/x"},
    ]
    if with_rules:
        steps.append(
            {
                "id": "two",
                "method": "GET",
                "path": "/api/v1/y",
                "rules": {"data.description": "exact"},
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"name": "sc", "steps": steps}), encoding="utf-8")


def test_missing_extra_and_step_rules(tmp_path: Path) -> None:
    """Tylko w złocie → missing, tylko w actual → extra; reguły z kroku n-1 (T4-harness p. 3)."""
    scenarios = tmp_path / "scenarios"
    _scenario(scenarios / "sc.yaml", with_rules=True)
    golden = tmp_path / "golden" / "v0.27.2"
    actual = tmp_path / "actual" / "v0.27.2"
    # Krok 1 bez reguł: inny opis → domyślnie type → brak Diffów (złe reguły kroku 2 dałyby value).
    _write(golden, "e/sc--01.json", "a")
    _write(actual, "e/sc--01.json", "b")
    # Krok 2 z regułą exact: inny opis → Diff value (dowód, że reguły pochodzą z właściwego kroku).
    _write(golden, "e/sc--02.json", "a")
    _write(actual, "e/sc--02.json", "b")
    _write(golden, "e/sc--03.json", "a")
    _write(actual, "e/sc--04.json", "b")
    assert compare_dir(actual, golden, "sc", scenarios_dir=scenarios) == [
        Diff("e/sc--02.json", "body.data.description", "value", "a", "b"),
        Diff("e/sc--03.json", "", "missing", "e/sc--03.json", None),
        Diff("e/sc--04.json", "", "extra", None, "e/sc--04.json"),
    ]


def test_empty_dirs(tmp_path: Path) -> None:
    """Brak plików po obu stronach → pusta lista."""
    scenarios = tmp_path / "scenarios"
    _scenario(scenarios / "sc.yaml", with_rules=False)
    golden = tmp_path / "golden" / "v0.27.2"
    golden.mkdir(parents=True)
    actual = tmp_path / "actual" / "v0.27.2"
    actual.mkdir(parents=True)
    assert compare_dir(actual, golden, "sc", scenarios_dir=scenarios) == []
