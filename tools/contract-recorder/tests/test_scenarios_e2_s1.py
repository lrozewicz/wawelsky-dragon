"""Testy walidacyjne scenariuszy S1 WP E2-0 (datasets_extras, system) — bez Dockera.

Zakres (work/wp/E2-0/tasks/_scenario-common.md): dla każdego pliku ``load_scenario``
przechodzi, ``name`` == nazwa pliku, każdy krok jest ``record: false`` albo ma jawnie
sensowne ``auth``/``expect``, a każda zmienna ``{x}`` w ``path``/``query``/``json``
ma wcześniejszy ``capture``.
"""

import re
from pathlib import Path

import pytest
from runner import AUTH_MODES, load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
FILES = ("datasets_extras.yaml", "system.yaml")

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
def test_versions_are_known(filename):
    for step in _scenario(filename)["steps"]:
        for version in step.get("versions", ()):
            assert version in ("v0.24.0", "v0.27.2"), step["id"]


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
def test_preparation_and_cleanup_steps_are_not_recorded(filename):
    """Krok tworzący zasób przed właściwym nagraniem i sprzątający nie trafiają do złota.

    Tylko ``datasets_extras.yaml`` ma przygotowanie (dataset) i sprzątanie (delete datasetu);
    ``system.yaml`` nie tworzy zasobów poza tokenami, a DELETE tokenu jest trasą z zakresu
    (nagrywaną), więc nie ma osobnego kroku sprzątającego.
    """
    if filename != "datasets_extras.yaml":
        return
    steps = _scenario(filename)["steps"]
    assert steps[0].get("record") is False, steps[0]["id"]
    assert steps[-1].get("record") is False, steps[-1]["id"]


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
def test_preparation_poll_waits_for_parse(filename):
    """Krok przygotowawczy parsowania czeka na ``DONE`` (jak w documents_parse.yaml)."""
    polls = [step for step in _scenario(filename)["steps"] if "poll" in step]
    if filename != "datasets_extras.yaml":
        assert polls == []
        return
    prepare = [step for step in polls if step["id"] == "poll_parse_done"]
    assert len(prepare) == 1
    assert prepare[0].get("record") is False, prepare[0]["id"]
    assert prepare[0]["poll"]["until"]["equals"] == "DONE", prepare[0]["id"]


@pytest.mark.parametrize("filename", FILES)
def test_token_steps_clean_up_the_created_token(filename):
    """Scenariusz z krokiem tworzącym token usuwa go dokładnie jednym DELETE-em."""
    if filename != "system.yaml":
        return
    steps = _scenario(filename)["steps"]
    creations = [
        step
        for step in steps
        if step["method"].upper() == "POST" and "token" in step.get("capture", {})
    ]
    assert len(creations) == 2  # v0.27.2 i v0.24.0
    for creation in creations:
        version = creation["versions"][0]
        deletes = [
            step
            for step in steps
            if step["method"].upper() == "DELETE"
            and step.get("versions") == [version]
            and "{token}" in step["path"]
        ]
        assert len(deletes) == 1, creation["id"]
