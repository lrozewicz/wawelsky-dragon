"""Testy scenariuszy E2 S2 (documents_extras, chunks_extras) — bez Dockera.

Sprawdzają to, czego nie da się sprawdzić runnerem bez stosu: poprawność YAML,
nazwy zasobów, jawną autoryzację tras legacy, komplet podstawień ``{zmiennych}``
i liczbę nagrywanych kroków per wersję (wykaz tras „jest/brak”).
"""

import re
from pathlib import Path

import pytest
import runner
from runner import ALL_VERSIONS, AUTH_MODES, METHODS, load_scenario

SCENARIO_NAMES = ("chunks_extras", "documents_extras")
SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Kroki przygotowawcze i sprzątające — zawsze bez nagrywania.
SETUP_STEP_IDS = (
    "create_dataset",
    "upload",
    "parse_v0_24",
    "parse_v0_27",
    "poll_parse_done",
    "delete_dataset",
)

# Liczba kroków nagrywanych per wersja (wykaz tras: jest/brak — patrz reports/S2-routes.md).
RECORDED_STEPS = {
    "documents_extras": {"v0.24.0": 14, "v0.27.2": 17},
    "chunks_extras": {"v0.24.0": 8, "v0.27.2": 13},
}


def _load(name: str) -> dict:
    return load_scenario(SCENARIOS_DIR / f"{name}.yaml")


def _variables(value: object) -> set[str]:
    """Nazwy zmiennych ``{x}`` w łańcuchu, mapie albo liście."""
    if isinstance(value, str):
        return set(_VAR_RE.findall(value))
    if isinstance(value, dict):
        found: set[str] = set()
        for item in value.values():
            found |= _variables(item)
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            found |= _variables(item)
        return found
    return set()


def _step_variables(step: dict) -> set[str]:
    return _variables([step["path"], step.get("query"), step.get("json")])


def _steps(name: str) -> list[dict]:
    return _load(name)["steps"]


def _applies(step: dict, version: str) -> bool:
    return version in step.get("versions", ALL_VERSIONS)


def _recorded_ids(name: str, version: str) -> list[str]:
    return [
        step["id"]
        for step in _steps(name)
        if step.get("record", True) and _applies(step, version)
    ]


def _all_steps() -> list[tuple[str, dict]]:
    return [(name, step) for name in SCENARIO_NAMES for step in _steps(name)]


class TestScenarioFiles:
    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_name_matches_file_and_steps_are_valid(self, name):
        scenario = _load(name)
        assert scenario["name"] == name
        steps = scenario["steps"]
        ids = [step["id"] for step in steps]
        assert len(ids) == len(set(ids))
        for step in steps:
            assert step["method"] in METHODS
            assert step["path"].startswith("/")
            assert step.get("auth", "key") in AUTH_MODES
            versions = step.get("versions", list(ALL_VERSIONS))
            assert versions and set(versions) <= set(ALL_VERSIONS)

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_both_versions_are_covered(self, name):
        for version in ALL_VERSIONS:
            assert _recorded_ids(name, version), (
                f"brak nagrywanych kroków dla {version}"
            )

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_recorded_step_count_per_version(self, name):
        assert {
            version: len(_recorded_ids(name, version)) for version in ALL_VERSIONS
        } == RECORDED_STEPS[name]

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_setup_and_cleanup_are_not_recorded(self, name):
        steps = _steps(name)
        setup = [step for step in steps if step["id"] in SETUP_STEP_IDS]
        assert len(setup) == len(SETUP_STEP_IDS)
        for step in setup:
            assert step["record"] is False
        assert steps[-1]["id"] == "delete_dataset"
        assert steps[-1]["method"] == "DELETE"

    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_dataset_names_use_e2_prefix(self, name):
        create = next(step for step in _steps(name) if step["id"] == "create_dataset")
        assert create["json"]["name"] == f"wd_rec_e2_{name}_ds"


class TestStepContracts:
    def test_legacy_v1_steps_declare_jwt(self):
        legacy = [
            (name, step["id"], step.get("auth"))
            for name, step in _all_steps()
            if step["path"].startswith("/v1/") and step.get("record", True)
        ]
        assert legacy, "oczekiwano tras legacy /v1/* w scenariuszach E2 S2"
        for name, step_id, auth in legacy:
            assert auth == "jwt", f"{name}/{step_id}: trasa legacy wymaga auth: jwt"

    def test_error_probes_declare_expect(self):
        probes = [
            (name, step["id"], step.get("expect"))
            for name, step in _all_steps()
            if step["id"].endswith("_missing") or "_cancel" in step["id"]
        ]
        assert len(probes) == 3, probes
        for name, step_id, expect in probes:
            assert expect == "any", f"{name}/{step_id}: krok nietypowy bez expect: any"

    def test_expect_only_on_recorded_steps(self):
        for name, step in _all_steps():
            if "expect" in step:
                assert step.get("record", True) is not False, f"{name}/{step['id']}"

    def test_binary_steps_are_recorded(self):
        for name, step in _all_steps():
            if step.get("binary"):
                assert step.get("record", True) is not False, f"{name}/{step['id']}"

    def test_variables_have_prior_capture(self):
        for name in SCENARIO_NAMES:
            captured: set[str] = set()
            for step in _steps(name):
                missing = _step_variables(step) - captured
                assert not missing, f"{name}/{step['id']}: brak capture dla {missing}"
                for variable, dotted in (step.get("capture") or {}).items():
                    assert isinstance(dotted, str) and dotted
                    captured.add(variable)
            assert captured == {"dataset_id", "document_id"} | (
                {"chunk_id"} if name == "chunks_extras" else set()
            )

    def test_switch_chunks_variants_use_source_field_names(self):
        ids = [step["id"] for step in _steps("chunks_extras")]
        switch_int = _steps("chunks_extras")[ids.index("switch_chunks_available_int")]
        switch_bool = _steps("chunks_extras")[ids.index("switch_chunks_available")]
        assert set(switch_int["json"]) == {"chunk_ids", "available_int"}
        assert set(switch_bool["json"]) == {"chunk_ids", "available"}
        for step in (switch_int, switch_bool):
            assert step["versions"] == ["v0.27.2"]

    def test_endpoint_dirs_avoid_collisions(self):
        """Ścieżki tego samego kroku nie mogą trafić do jednego pliku golden."""
        for name in SCENARIO_NAMES:
            for version in ALL_VERSIONS:
                targets = [
                    (
                        runner.endpoint_dir(step["path"]),
                        number,
                    )
                    for number, step in enumerate(_steps(name), start=1)
                    if step.get("record", True) and _applies(step, version)
                ]
                assert len(targets) == len(set(targets))
