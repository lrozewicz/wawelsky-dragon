"""Testy scenariusza E2 S4 (errors_access) — bez Dockera.

Sprawdzają to, czego nie da się sprawdzić runnerem bez stosu: poprawność YAML,
komplet podstawień ``{zmiennych}``, brak kolizji plików złota, liczby nagrywanych
kroków per wersję (wykaz tras „jest/brak” w ``work/wp/E2-0/reports/S4-routes.md``)
oraz kolejność kroków niszczących (DELETE drugiego użytkownika na końcu).
"""

import re
from pathlib import Path

import pytest
import runner
from runner import ALL_VERSIONS, AUTH_MODES, METHODS, load_scenario

NAME = "errors_access"
SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / f"{NAME}.yaml"
_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
ZERO_ID = "0" * 32

# Kroki przygotowawcze i sprzątające — zawsze bez nagrywania.
SETUP_STEP_IDS = (
    "create_dataset",
    "upload",
    "parse_v0_24",
    "parse_v0_27",
    "poll_parse_done",
    "list_chunks_setup",
    "create_chat",
    "create_session",
    "seed_completion",
)
CLEANUP_STEP_IDS = ("delete_chat", "delete_dataset")
# DELETE drugiego użytkownika mogące zniszczyć zasoby — dopiero po wszystkich innych krokach.
DESTRUCTIVE_STEP_IDS = (
    "chunks_delete_second",
    "documents_delete_second",
    "sessions_delete_second",
    "chats_delete_second",
    "datasets_delete_second",
)
# Liczba kroków nagrywanych per wersja (reports/S4-routes.md).
RECORDED_STEPS = {"v0.24.0": 34, "v0.27.2": 40}
# Minimalna liczba różnych tras wywołanych kluczem drugiego użytkownika (brief: 20).
MIN_SECOND_ROUTES = 20


def _scenario() -> dict:
    return load_scenario(SCENARIO_PATH)


def _steps() -> list[dict]:
    return _scenario()["steps"]


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


def _applies(step: dict, version: str) -> bool:
    return version in step.get("versions", ALL_VERSIONS)


def _recorded_steps(version: str | None = None) -> list[dict]:
    steps = _steps()
    if version is None:
        return [step for step in steps if step.get("record", True)]
    return [
        step for step in steps if step.get("record", True) and _applies(step, version)
    ]


def test_name_matches_file_name():
    assert _scenario()["name"] == SCENARIO_PATH.stem


def test_description_is_set():
    assert _scenario()["description"].strip()


def test_steps_are_valid():
    ids = [step["id"] for step in _steps()]
    assert len(ids) == len(set(ids))
    for step in _steps():
        assert step["method"] in METHODS, step["id"]
        assert step["path"].startswith("/"), step["id"]
        assert step.get("auth", "key") in AUTH_MODES, step["id"]
        versions = step.get("versions", list(ALL_VERSIONS))
        assert versions and set(versions) <= set(ALL_VERSIONS), step["id"]


def test_recorded_steps_declare_expect_any():
    """Krok nagrywany to zawsze przypadek błędu/odmowy — ``expect: any``."""
    for step in _recorded_steps():
        assert step.get("expect") == "any", step["id"]


def test_setup_and_cleanup_are_not_recorded():
    steps = _steps()
    by_id = {step["id"]: step for step in steps}
    for step_id in SETUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id
    for step_id in CLEANUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id
    assert [step["id"] for step in steps[-2:]] == list(CLEANUP_STEP_IDS)
    assert steps[-1]["method"] == "DELETE"


def test_recorded_step_count_per_version():
    assert {
        version: len(_recorded_steps(version)) for version in ALL_VERSIONS
    } == RECORDED_STEPS


def test_both_versions_are_covered():
    for version in ALL_VERSIONS:
        assert _recorded_steps(version), f"brak nagrywanych kroków dla {version}"


def test_second_user_probes_cover_at_least_twenty_routes():
    routes = {
        (step["method"], step["path"])
        for step in _recorded_steps()
        if step.get("auth") == "second"
    }
    assert len(routes) >= MIN_SECOND_ROUTES, sorted(routes)


def test_destructive_deletes_run_after_every_other_recorded_step():
    steps = _steps()
    order = {step["id"]: number for number, step in enumerate(steps, start=1)}
    first_destructive = min(order[step_id] for step_id in DESTRUCTIVE_STEP_IDS)
    for step in steps:
        if step["id"] in DESTRUCTIVE_STEP_IDS or step["id"] in CLEANUP_STEP_IDS:
            continue
        if step.get("record", True):
            assert order[step["id"]] < first_destructive, step["id"]


def test_names_use_e2_prefix():
    create_dataset = next(step for step in _steps() if step["id"] == "create_dataset")
    create_chat = next(step for step in _steps() if step["id"] == "create_chat")
    assert create_dataset["json"]["name"] == f"wd_rec_e2_{NAME}_ds"
    assert create_chat["json"]["name"] == f"wd_rec_e2_{NAME}_chat"


def test_versions_match_route_availability():
    """Trasy istniejące tylko w jednej wersji mają jawne ``versions``."""
    by_id = {step["id"]: step for step in _steps()}
    only_v0_27 = (
        "datasets_get_second",
        "document_patch_second",
        "parse_second_v0_27",
        "stop_parse_second_v0_27",
        "chat_get_second",
        "chat_patch_second",
        "session_get_second",
        "session_patch_second",
        "chat_completions_second",
        "dataset_get_missing",
    )
    only_v0_24 = (
        "document_put_second",
        "parse_second_v0_24",
        "stop_parse_second_v0_24",
        "session_put_second",
    )
    for step_id in only_v0_27:
        assert by_id[step_id]["versions"] == ["v0.27.2"], step_id
    for step_id in only_v0_24:
        assert by_id[step_id]["versions"] == ["v0.24.0"], step_id


def test_missing_id_probes_use_zero_id():
    missing = [step for step in _steps() if step["id"].endswith("_missing")]
    assert len(missing) == 7
    for step in missing:
        assert ZERO_ID in step["path"], step["id"]


def test_variables_have_prior_capture():
    captured: set[str] = set()
    for step in _steps():
        missing = _step_variables(step) - captured
        assert not missing, f"{step['id']}: brak capture dla {missing}"
        for variable, dotted in (step.get("capture") or {}).items():
            assert isinstance(dotted, str) and dotted
            captured.add(variable)
    assert "chunk_id" in captured, "scenariusz nie przechwytuje id chunki"


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_endpoint_dirs_avoid_collisions(version):
    """Kroki nagrywane nie mogą trafić do jednego pliku złota."""
    targets = [
        (runner.endpoint_dir(step["path"]), number)
        for number, step in enumerate(_steps(), start=1)
        if step.get("record", True) and _applies(step, version)
    ]
    assert len(targets) == len(set(targets))
