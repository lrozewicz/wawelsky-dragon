"""Testy scenariusza E4-45g T1 (searches) — bez Dockera.

Zakres (``work/wp/E4-45g/tasks/_scenario-common.md``): poprawność YAML, komplet
podstawień ``{zmiennych}``, kroki przygotowawcze/sprzątające bez nagrywania oraz
— specyficzne dla tego zadania — pominięcie całej wersji v0.24.0 (brak tras
``/api/v1/searches*``) i komplet tras ``/searches*`` z ``reports/T1-routes.md``.
"""

import re
from pathlib import Path

from runner import ALL_VERSIONS, AUTH_MODES, METHODS, load_scenario

NAME = "searches"
SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / f"{NAME}.yaml"
_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
ZERO_ID = "0" * 32

# Wykaz tras z reports/T1-routes.md: wszystkie nagrywane kroki v0.27.2 to jedna z tych tras.
RECORDED_ROUTES = {
    ("POST", "/api/v1/searches"),
    ("GET", "/api/v1/searches"),
    ("GET", "/api/v1/searches/{search_id}"),
    ("PUT", "/api/v1/searches/{search_id}"),
    ("DELETE", "/api/v1/searches/{search_id}"),
    ("POST", "/api/v1/searches/{search_id}/completions"),
    ("POST", "/api/v1/searches/{search_id_2}/completions"),
    ("POST", "/api/v1/chat/recommendation"),
    ("GET", "/api/v1/searches/" + ZERO_ID),
    ("PUT", "/api/v1/searches/" + ZERO_ID),
    ("DELETE", "/api/v1/searches/" + ZERO_ID),
}
# Liczba kroków nagrywanych dla v0.27.2 (reports/T1-routes.md).
RECORDED_STEPS_V0_27 = 29
SETUP_STEP_IDS = ("create_dataset", "upload", "parse", "poll_parse_done")
CLEANUP_STEP_IDS = ("delete_search_second", "delete_dataset")


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


def test_v0_24_0_has_no_steps():
    """v0.24.0 nie ma tras ``/api/v1/searches*`` — cała wersja pominięta."""
    assert [step["id"] for step in _steps() if _applies(step, "v0.24.0")] == []
    assert _recorded_steps("v0.24.0") == []
    for step in _steps():
        assert step.get("versions") == ["v0.27.2"], step["id"]


def test_recorded_step_count():
    assert len(_recorded_steps("v0.27.2")) == RECORDED_STEPS_V0_27
    assert len(_recorded_steps()) == RECORDED_STEPS_V0_27


def test_setup_and_cleanup_are_not_recorded():
    steps = _steps()
    by_id = {step["id"]: step for step in steps}
    for step_id in SETUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id
    for step_id in CLEANUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id
    assert [step["id"] for step in steps[: len(SETUP_STEP_IDS)]] == list(SETUP_STEP_IDS)
    assert [step["id"] for step in steps[-2:]] == list(CLEANUP_STEP_IDS)


def test_preparation_poll_waits_for_parse():
    polls = [step for step in _steps() if "poll" in step]
    assert [step["id"] for step in polls] == ["poll_parse_done"]
    assert polls[0]["record"] is False
    assert polls[0]["poll"]["until"]["equals"] == "DONE"


def test_recorded_steps_declare_auth():
    for step in _recorded_steps():
        assert "auth" in step, step["id"]
        assert step["auth"] in AUTH_MODES, step["id"]


def test_recorded_routes_are_from_the_report():
    for step in _recorded_steps():
        assert (step["method"], step["path"]) in RECORDED_ROUTES, step["id"]


def test_versions_match_route_availability():
    """Wszystkie nagrywane trasy istnieją tylko w v0.27.2 (reports/T1-routes.md)."""
    for step in _recorded_steps():
        assert step["versions"] == ["v0.27.2"], step["id"]


def test_second_user_probes_target_the_created_search():
    second = [step for step in _recorded_steps() if step.get("auth") == "second"]
    assert {step["id"] for step in second} == {
        "completion_second_user",
        "get_search_second_user",
        "update_search_second_user",
        "delete_search_second_user",
    }
    # GET /searches/<id> cudzego zasobu to OPERATING_ERROR (103), reszta AUTHENTICATION_ERROR (109).
    expected = {
        "completion_second_user": ("/api/v1/searches/{search_id}/completions", 109),
        "get_search_second_user": ("/api/v1/searches/{search_id}", 103),
        "update_search_second_user": ("/api/v1/searches/{search_id}", 109),
        "delete_search_second_user": ("/api/v1/searches/{search_id}", 109),
    }
    for step in second:
        path, code = expected[step["id"]]
        assert step["path"] == path, step["id"]
        assert step["expect"] == {"status": 200, "code": code}, step["id"]


def test_names_use_e4_searches_prefix():
    """Każda niepusta nazwa zasobu w ciele ma prefiks ``wd_rec_e4_searches_``."""
    for step in _steps():
        body = step.get("json")
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            continue
        name = body["name"]
        if not name:  # krok błędu: pusta nazwa (code 102)
            continue
        assert name.startswith("wd_rec_e4_searches_"), (step["id"], name)


def test_completion_is_recorded_as_sse():
    completion = next(
        step for step in _recorded_steps() if step["id"] == "completion_sse"
    )
    assert completion["path"] == "/api/v1/searches/{search_id}/completions"
    assert completion.get("stream") is True
    assert completion["json"] == {"question": "smokwawelski"}


def test_completion_step_other_than_kb_ids_is_not_streamed():
    """Kroki błędów completion zwracają JSON, nie SSE — bez ``stream``."""
    for step in _steps():
        if step["id"].startswith("completion_") and step["id"] != "completion_sse":
            assert "stream" not in step, step["id"]


def test_variables_have_prior_capture():
    captured: set[str] = set()
    for step in _steps():
        missing = _step_variables(step) - captured
        assert not missing, (
            f"{step['id']}: brak wcześniejszego capture {sorted(missing)}"
        )
        captured.update(step.get("capture") or {})


def test_cleanup_removes_every_created_search():
    """Sprzątanie usuwa oba utworzone search appy (ten drugi nagrywany w kroku)."""
    deletes = [
        step
        for step in _steps()
        if step["method"] == "DELETE"
        and step["path"] == "/api/v1/searches/{search_id_2}"
    ]
    assert len(deletes) == 1
    assert deletes[0]["record"] is False
    assert deletes[0]["id"] in CLEANUP_STEP_IDS


def test_step_ids_are_snake_case():
    for step in _steps():
        assert re.fullmatch(r"[a-z0-9_]+", step["id"]), step["id"]
