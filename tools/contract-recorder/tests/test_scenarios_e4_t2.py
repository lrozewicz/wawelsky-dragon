"""Testy walidacyjne scenariusza T2 WP E4-45g (files.yaml) — bez Dockera.

Zakres (work/wp/E4-45g/tasks/_scenario-common.md, work/wp/E2-0/tasks/_scenario-common.md):
``load_scenario`` przechodzi, ``name`` == nazwa pliku, każdy krok jest ``record: false``
albo ma jawnie sensowne ``auth``/``expect``, a każda zmienna ``{x}`` w ``path``/``query``/
``json`` ma wcześniejszy ``capture``.

Dodatkowo dla T2: trasy ``/files*`` istnieją tylko w v0.27.2, więc każdy krok ma
``versions: [v0.27.2]``; scenariusz nagrywa pobranie binarne i sprząta po sobie
(``DELETE /api/v1/files`` oraz dataset bez nagrywania).
"""

import re
from pathlib import Path

import pytest
from runner import AUTH_MODES, load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
FILES = ("files.yaml",)
ONLY_VERSION = "v0.27.2"

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _scenario(filename: str) -> dict:
    return load_scenario(SCENARIOS_DIR / filename)


def _strings(value):
    """Wszystkie łańcuchy w strukturze (dict/list/skalar) — do szukania ``{zmiennych}``."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _referenced_variables(step: dict) -> set[str]:
    names: set[str] = set()
    for field in ("path", "query", "json"):
        for text in _strings(step.get(field)):
            names.update(_VAR_RE.findall(text))
    return names


@pytest.mark.parametrize("filename", FILES)
def test_name_matches_file_name(filename):
    assert _scenario(filename)["name"] == Path(filename).stem


@pytest.mark.parametrize("filename", FILES)
def test_description_is_set(filename):
    assert _scenario(filename)["description"].strip()


@pytest.mark.parametrize("filename", FILES)
def test_every_step_is_v0_27_2_only(filename):
    """Trasy ``/files*`` nie istnieją w v0.24.0 (tam jest ``/file/*`` — zadanie T3)."""
    for step in _scenario(filename)["steps"]:
        assert step.get("versions") == [ONLY_VERSION], step["id"]


@pytest.mark.parametrize("filename", FILES)
def test_recorded_steps_declare_auth_or_expect(filename):
    """Krok nagrywany musi mieć jawnie sensowne ``auth`` albo ``expect``."""
    for step in _scenario(filename)["steps"]:
        if step.get("record", True) is False:
            continue
        assert "auth" in step or "expect" in step, step["id"]
        if "auth" in step:
            assert step["auth"] in AUTH_MODES, step["id"]


@pytest.mark.parametrize("filename", FILES)
def test_variables_have_earlier_capture(filename):
    captured: set[str] = set()
    for step in _scenario(filename)["steps"]:
        missing = _referenced_variables(step) - captured
        assert not missing, (
            f"{step['id']}: brak wcześniejszego capture {sorted(missing)}"
        )
        captured.update(step.get("capture") or {})


@pytest.mark.parametrize("filename", FILES)
def test_binary_download_step_exists(filename):
    """Pobranie pliku nagrywamy jako odpowiedź binarną (status/content-type/sha256)."""
    binary = [step for step in _scenario(filename)["steps"] if step.get("binary")]
    assert binary, "brak kroku z 'binary: true'"
    assert any(step["method"].upper() == "GET" for step in binary), (
        "binary tylko dla GET"
    )


@pytest.mark.parametrize("filename", FILES)
def test_scenario_cleans_up_created_resources(filename):
    """Scenariusz usuwa utworzone pliki/folder i dataset (dataset bez nagrywania)."""
    steps = _scenario(filename)["steps"]
    # foldery/pliki: dwa skuteczne DELETE /files (bez expect) po identyfikatorach z capture
    cleanup = [
        step
        for step in steps
        if step["method"].upper() == "DELETE"
        and step["path"] == "/api/v1/files"
        and step.get("record", True)
        and "expect" not in step
    ]
    assert [step["id"] for step in cleanup] == ["delete_file", "delete_folder"]
    assert {step["json"]["ids"][0] for step in cleanup} == {"{file_id}", "{folder_id}"}
    # dataset: DELETE bez nagrywania
    dataset_delete = [step for step in steps if step["id"] == "delete_dataset"]
    assert len(dataset_delete) == 1
    assert dataset_delete[0].get("record") is False


@pytest.mark.parametrize("filename", FILES)
def test_preparation_poll_waits_for_linked_document(filename):
    """Krok linkowania czeka, aż dokument pojawi się w liście datasetu (poll)."""
    polls = [step for step in _scenario(filename)["steps"] if "poll" in step]
    assert len(polls) == 1
    poll = polls[0]
    assert poll["poll"]["until"] == {"path": "data.total", "equals": 1}
    assert poll["path"] == "/api/v1/datasets/{dataset_id}/documents"
