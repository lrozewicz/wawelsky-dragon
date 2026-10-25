"""Testy scenariusza E6-0 T2 (agents) — bez Dockera.

Zakres (``work/wp/E6-0/tasks/_scenario-common.md``): poprawność YAML, komplet
podstawień ``{zmiennych}``, kroki przygotowawcze/sprzątające bez nagrywania,
wyłącznie v0.27.2 (brak shimu v0.24.0), trasy z ``reports/T2-routes.md``,
graf DSL Begin -> Agent -> Message (liniowy i z narzędziem Retrieval) oraz
komplet wariantów ``POST /agents/chat/completions`` (nowa sesja/istniejąca,
SSE/JSON, wariant Retrieval, błędy).
"""

import re
from pathlib import Path

from runner import ALL_VERSIONS, AUTH_MODES, METHODS, load_scenario

NAME = "agents"
RECORDER_DIR = Path(__file__).resolve().parent.parent
SCENARIO_PATH = RECORDER_DIR / "scenarios" / f"{NAME}.yaml"
ZERO_ID = "0" * 32
_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_COMPLETIONS = "/api/v1/agents/chat/completions"

# Wykaz tras z reports/T2-routes.md: każdy nagrywany krok v0.27.2 to jedna z tych tras.
RECORDED_ROUTES = {
    ("GET", "/api/v1/agents"),
    ("POST", "/api/v1/agents"),
    ("GET", "/api/v1/agents/templates"),
    ("GET", "/api/v1/agents/{agent_id}"),
    ("GET", "/api/v1/agents/" + ZERO_ID),
    ("PUT", "/api/v1/agents/{agent_id}"),
    ("PUT", "/api/v1/agents/" + ZERO_ID),
    ("DELETE", "/api/v1/agents/{agent_id}"),
    ("DELETE", "/api/v1/agents/" + ZERO_ID),
    ("GET", "/api/v1/agents/{agent_retrieval_id}"),
    ("GET", "/api/v1/agents/{agent_id}/sessions"),
    ("POST", "/api/v1/agents/{agent_id}/sessions"),
    ("DELETE", "/api/v1/agents/{agent_id}/sessions"),
    ("GET", "/api/v1/agents/{agent_id}/sessions/{session_id}"),
    ("GET", "/api/v1/agents/{agent_id}/sessions/{session_id_2}"),
    ("GET", "/api/v1/agents/{agent_id}/sessions/" + ZERO_ID),
    ("DELETE", "/api/v1/agents/{agent_id}/sessions/{session_id}"),
    ("GET", "/api/v1/agents/" + ZERO_ID + "/sessions"),
    ("POST", "/api/v1/agents/" + ZERO_ID + "/sessions"),
    ("DELETE", "/api/v1/agents/" + ZERO_ID + "/sessions"),
    ("POST", _COMPLETIONS),
}
# Trasy z listy poza zakresem T2 — nie mogą wystąpić w scenariuszu.
OUT_OF_SCOPE_ROUTES = {
    ("GET", "/api/v1/agents/prompts"),
    ("GET", "/api/v1/agents/download"),
    ("GET", "/api/v1/agents/tags"),
    ("PUT", "/api/v1/agents/{agent_id}/tags"),
    ("POST", "/api/v1/agents/{agent_id}/upload"),
    ("GET", "/api/v1/agents/{agent_id}/components/{component_id}/input-form"),
    ("POST", "/api/v1/agents/{agent_id}/components/{component_id}/debug"),
    ("GET", "/api/v1/agents/{agent_id}/versions"),
    ("GET", "/api/v1/agents/{agent_id}/versions/{version_id}"),
    ("GET", "/api/v1/agents/{agent_id}/logs/{message_id}"),
    ("POST", "/api/v1/agents/{agent_id}/reset"),
    ("POST", "/api/v1/agents/rerun"),
    ("POST", "/api/v1/agents/test_db_connection"),
}

TOTAL_STEPS = 72
RECORDED_STEPS = 63
SETUP_STEP_IDS = ("create_dataset", "upload", "parse", "poll_parse_done")
CLEANUP_STEP_IDS = (
    "clear_sessions_agent",
    "clear_sessions_retrieval",
    "delete_agent_retrieval",
    "delete_agent_empty",
    "delete_dataset",
)
STREAM_STEP_IDS = (
    "completions_stream",
    "completions_session_stream",
    "completions_retrieval_stream",
)
# Nagrywane kroki sukcesu bez jawnego ``expect`` (sukces sprawdzany domyślnie przez runner).
PLAIN_SUCCESS_IDS = {
    "list_templates",
    "create_agent",
    "create_agent_retrieval",
    "list_agents",
    "list_agents_page",
    "list_agents_keywords",
    "list_agents_title_ignored",
    "list_agents_id_ignored",
    "list_agents_orderby",
    "list_agents_category",
    "list_agents_canvas_type",
    "list_agents_tags",
    "list_agents_filter",
    "get_agent",
    "get_agent_retrieval",
    "get_agent_after_update",
    "create_session",
    "list_sessions",
    "list_sessions_page",
    "get_session",
    "completions_stream",
    "completions_json",
    "completions_session_stream",
    "completions_session_json",
    "completions_retrieval_stream",
    "completions_retrieval_json",
    "create_session_2",
}
# Kroki z cudzym zasobem (auth: second) i ich oczekiwany RetCode.
FOREIGN_EXPECT = {
    "get_agent_foreign": 102,
    "update_agent_foreign": 103,
    "delete_agent_foreign": 103,
    "list_sessions_foreign": 103,
    "create_session_foreign": 103,
    "get_session_foreign": 103,
    "delete_session_foreign": 103,
    "delete_sessions_foreign": 103,
}
TITLES = (
    "wd_rec_e6_agents_chatbot",
    "wd_rec_e6_agents_chatbot_v2",
    "wd_rec_e6_agents_retrieval",
    "wd_rec_e6_agents_empty",
)


def _scenario() -> dict:
    return load_scenario(SCENARIO_PATH)


def _steps() -> list[dict]:
    return _scenario()["steps"]


def _by_id() -> dict[str, dict]:
    return {step["id"]: step for step in _steps()}


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
        found: set[str] = set()
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


def _component_names(dsl: dict) -> set[str]:
    return {
        component["obj"]["component_name"] for component in dsl["components"].values()
    }


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


def test_only_v0_27_2():
    """E6 nie ma shimu v0.24.0 — każdy krok działa wyłącznie na v0.27.2."""
    for step in _steps():
        assert step.get("versions") == ["v0.27.2"], step["id"]
    assert [step["id"] for step in _steps() if _applies(step, "v0.24.0")] == []


def test_step_count():
    assert len(_steps()) == TOTAL_STEPS
    assert len(_recorded_steps("v0.27.2")) == RECORDED_STEPS
    assert len(_recorded_steps()) == RECORDED_STEPS


def test_setup_and_cleanup_are_not_recorded():
    steps = _steps()
    by_id = _by_id()
    for step_id in SETUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id
    for step_id in CLEANUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id
    assert [step["id"] for step in steps[: len(SETUP_STEP_IDS)]] == list(SETUP_STEP_IDS)
    for step_id in CLEANUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id


def test_recorded_steps_declare_auth():
    for step in _recorded_steps():
        assert "auth" in step, step["id"]
        assert step["auth"] in AUTH_MODES, step["id"]


def test_recorded_routes_are_from_the_report():
    for step in _recorded_steps():
        assert (step["method"], step["path"]) in RECORDED_ROUTES, step["id"]


def test_out_of_scope_routes_are_absent():
    for step in _steps():
        assert (step["method"], step["path"]) not in OUT_OF_SCOPE_ROUTES, step["id"]


def test_recorded_steps_have_expect_or_plain_success():
    without_expect = {step["id"] for step in _recorded_steps() if "expect" not in step}
    assert without_expect == PLAIN_SUCCESS_IDS
    for step in _recorded_steps():
        if "expect" in step:
            assert set(step["expect"]) <= {"status", "code"}, step["id"]
            assert all(isinstance(v, int) for v in step["expect"].values()), step["id"]


def test_variables_have_prior_capture():
    captured: set[str] = set()
    for step in _steps():
        missing = _step_variables(step) - captured
        assert not missing, (
            f"{step['id']}: brak wcześniejszego capture {sorted(missing)}"
        )
        captured.update(step.get("capture") or {})


def test_templates_route_is_recorded_without_narrowing():
    """GET /agents/templates nie czyta żadnego parametru (agent_api.py:647) — nagrywam całość."""
    step = _by_id()["list_templates"]
    assert step.get("record", True) is True
    assert "query" not in step
    assert step["path"] == "/api/v1/agents/templates"


def test_linear_dsl_is_begin_agent_message():
    for step_id in ("create_agent", "create_agent_duplicate", "create_agent_no_auth"):
        dsl = _by_id()[step_id]["json"]["dsl"]
        assert _component_names(dsl) == {"Begin", "Agent", "Message"}, step_id
        components = dsl["components"]
        assert components["begin"]["downstream"] == ["agent"], step_id
        assert components["agent"]["downstream"] == ["message"], step_id
        assert components["agent"]["upstream"] == ["begin"], step_id
        assert components["message"]["obj"]["params"]["content"] == [
            "{agent@content}"
        ], step_id
        agent_params = components["agent"]["obj"]["params"]
        assert agent_params["llm_id"] == "{chat_model}", step_id
        assert agent_params["tools"] == [], step_id
    assert (
        _by_id()["update_agent"]["json"]["dsl"]
        == _by_id()["create_agent"]["json"]["dsl"]
    )


def test_retrieval_variant_uses_dataset_from_setup():
    dsl = _by_id()["create_agent_retrieval"]["json"]["dsl"]
    assert _component_names(dsl) == {"Begin", "Agent", "Message"}
    tools = dsl["components"]["agent"]["obj"]["params"]["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["component_name"] == "Retrieval"
    assert tool["params"]["dataset_ids"] == ["{dataset_id}"]
    assert tool["params"]["retrieval_from"] == "dataset"


def test_create_agent_captures_and_error_codes():
    by_id = _by_id()
    assert by_id["create_agent"]["capture"] == {"agent_id": "data.id"}
    assert by_id["create_agent_retrieval"]["capture"] == {
        "agent_retrieval_id": "data.id"
    }
    assert by_id["create_agent_empty_dsl"]["capture"] == {"agent_empty_id": "data.id"}
    # dsl {} jest poprawnym JSON-em -> upstream zakłada agenta (code 0)
    assert by_id["create_agent_empty_dsl"]["expect"] == {"status": 200, "code": 0}
    assert by_id["create_agent_duplicate"]["expect"] == {"status": 200, "code": 102}
    # brak dsl i niepoprawny JSON-string dsl -> ARGUMENT_ERROR (101)
    assert by_id["create_agent_missing_dsl"]["expect"] == {"status": 200, "code": 101}
    # brak title -> ARGUMENT_ERROR (101)
    assert by_id["create_agent_missing_title"]["expect"] == {"status": 200, "code": 101}
    assert "title" not in by_id["create_agent_missing_title"]["json"]
    assert by_id["create_agent_bad_dsl"]["expect"] == {"status": 200, "code": 101}
    assert by_id["create_agent_bad_dsl"]["json"]["dsl"] == "x"
    assert by_id["create_agent_no_auth"]["auth"] == "none"
    assert by_id["create_agent_no_auth"]["expect"] == {"status": 401, "code": 401}


def test_list_agents_covers_handler_params():
    by_id = _by_id()
    # domyślna lista bez parametrów
    assert "query" not in by_id["list_agents"]
    assert by_id["list_agents_page"]["query"] == {"page": 1, "page_size": 10}
    assert by_id["list_agents_keywords"]["query"]["keywords"] == "wd_rec_e6_agents"
    # parametr `title` nie jest czytany przez handler (zwraca pełną listę) — fakt do złota
    assert by_id["list_agents_title_ignored"]["query"] == {
        "title": "wd_rec_e6_agents_chatbot"
    }
    # parametr `id` także nie jest czytany (filtrują tylko keywords/owner_ids)
    assert by_id["list_agents_id_ignored"]["query"] == {
        "id": "wd_rec_e6_agents_chatbot"
    }
    assert by_id["list_agents_orderby"]["query"] == {"orderby": "title", "desc": False}
    assert by_id["list_agents_category"]["query"] == {"canvas_category": "agent_canvas"}
    # canvas_type i tags wyłączają tryb "merge" (agent_api.py:749-751)
    assert by_id["list_agents_canvas_type"]["query"] == {"canvas_type": "Recommended"}
    assert by_id["list_agents_tags"]["query"] == {"tags": "wd_rec_e6_agents"}
    assert by_id["list_agents_filter"]["query"] == {"type": "filter"}
    assert by_id["list_agents_owner_ids_foreign"]["query"] == {"owner_ids": ZERO_ID}
    assert by_id["list_agents_owner_ids_foreign"]["expect"] == {
        "status": 200,
        "code": 103,
    }


def test_update_agent_changes_title_and_dsl():
    by_id = _by_id()
    body = by_id["update_agent"]["json"]
    assert body["title"] == "wd_rec_e6_agents_chatbot_v2"
    assert "dsl" in body
    assert by_id["update_agent"]["expect"] == {"status": 200, "code": 0}
    # kolizja tytułu z innym agentem -> DATA_ERROR (102)
    dup = by_id["update_agent_duplicate_title"]["json"]
    assert dup["title"] == "wd_rec_e6_agents_retrieval"
    assert by_id["update_agent_duplicate_title"]["expect"] == {
        "status": 200,
        "code": 102,
    }
    assert by_id["update_agent_bad_dsl"]["expect"] == {"status": 200, "code": 101}


def test_sessions_crud_is_covered():
    by_id = _by_id()
    assert by_id["create_session"]["capture"] == {"session_id": "data.id"}
    assert by_id["create_session_2"]["capture"] == {"session_id_2": "data.id"}
    assert by_id["list_sessions"]["path"] == "/api/v1/agents/{agent_id}/sessions"
    assert by_id["list_sessions_page"]["query"]["page_size"] == 10
    assert by_id["delete_session"]["expect"] == {"status": 200, "code": 0}
    assert by_id["get_session_after_delete"]["expect"] == {"status": 200, "code": 102}
    # usunięcie zbiorcze po `ids` (agent_api.py:532)
    assert by_id["delete_sessions_by_ids"]["json"] == {"ids": ["{session_id_2}"]}
    assert by_id["delete_sessions_by_ids"]["expect"] == {"status": 200, "code": 0}
    assert by_id["get_session_2_after_delete"]["expect"] == {
        "status": 200,
        "code": 102,
    }
    assert by_id["get_session_missing"]["expect"] == {"status": 200, "code": 102}


def test_stream_steps_are_post_completions():
    for step_id in STREAM_STEP_IDS:
        step = _by_id()[step_id]
        assert step["stream"] is True, step_id
        assert step["method"] == "POST", step_id
        assert step["path"] == _COMPLETIONS, step_id
        assert step["json"]["stream"] is True, step_id


def test_completions_cover_new_and_existing_session():
    by_id = _by_id()
    # (a) nowa sesja: brak session_id w ciele
    assert "session_id" not in by_id["completions_stream"]["json"]
    assert "session_id" not in by_id["completions_json"]["json"]
    # (b) istniejąca sesja
    assert by_id["completions_session_stream"]["json"]["session_id"] == "{session_id}"
    assert by_id["completions_session_json"]["json"]["session_id"] == "{session_id}"
    assert by_id["completions_session_json"]["json"]["stream"] is False
    # (c) wariant Retrieval
    for step_id in ("completions_retrieval_stream", "completions_retrieval_json"):
        assert by_id[step_id]["json"]["agent_id"] == "{agent_retrieval_id}", step_id


def test_completions_error_codes():
    by_id = _by_id()
    assert by_id["completions_missing_agent_id"]["expect"] == {
        "status": 200,
        "code": 101,
    }
    assert by_id["completions_missing_agent"]["expect"] == {
        "status": 200,
        "code": 103,
    }
    assert by_id["completions_missing_session"]["expect"] == {
        "status": 200,
        "code": 102,
    }
    assert by_id["completions_session_other_agent"]["expect"] == {
        "status": 200,
        "code": 103,
    }
    assert by_id["completions_no_auth"]["expect"] == {"status": 401, "code": 401}


def test_foreign_and_missing_agent_errors():
    by_id = _by_id()
    for step_id, code in FOREIGN_EXPECT.items():
        assert by_id[step_id]["auth"] == "second", step_id
        assert by_id[step_id]["expect"] == {"status": 200, "code": code}, step_id
    assert by_id["get_agent_missing"]["expect"] == {"status": 200, "code": 102}
    assert by_id["update_agent_missing"]["expect"] == {"status": 200, "code": 103}
    assert by_id["delete_agent_missing"]["expect"] == {"status": 200, "code": 103}
    assert by_id["delete_agent"]["expect"] == {"status": 200, "code": 0}
    assert by_id["get_agent_after_delete"]["expect"] == {"status": 200, "code": 102}


def test_missing_agent_sessions_errors():
    """Sesje z nieistniejącym agent_id: wrapper dostępu zwraca OPERATING_ERROR (103)."""
    by_id = _by_id()
    for step_id in (
        "list_sessions_missing_agent",
        "create_session_missing_agent",
        "delete_sessions_missing_agent",
    ):
        step = by_id[step_id]
        assert step["path"].startswith(f"/api/v1/agents/{ZERO_ID}/sessions"), step_id
        assert step["expect"] == {"status": 200, "code": 103}, step_id


def test_fixture_file_exists():
    path = RECORDER_DIR / "fixtures" / "ragflow_intro.txt"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip()


def test_names_use_e6_agents_prefix():
    titles = []
    for step in _steps():
        body = step.get("json")
        if isinstance(body, dict) and isinstance(body.get("title"), str):
            titles.append(body["title"])
    # tytuły zasobów zakładanych przez scenariusz (także warianty błędne) mają prefiks WP
    assert set(TITLES) <= set(titles)
    for title in titles:
        assert title.startswith("wd_rec_e6_agents_"), title


def test_cleanup_removes_every_created_resource():
    by_id = _by_id()
    assert by_id["clear_sessions_agent"]["json"] == {"delete_all": True}
    assert by_id["clear_sessions_retrieval"]["json"] == {"delete_all": True}
    assert (
        by_id["delete_agent_retrieval"]["path"] == "/api/v1/agents/{agent_retrieval_id}"
    )
    assert by_id["delete_agent_empty"]["path"] == "/api/v1/agents/{agent_empty_id}"
    assert by_id["delete_dataset"]["json"] == {"ids": ["{dataset_id}"]}


def test_step_ids_are_snake_case():
    for step in _steps():
        assert re.fullmatch(r"[a-z0-9_]+", step["id"]), step["id"]
