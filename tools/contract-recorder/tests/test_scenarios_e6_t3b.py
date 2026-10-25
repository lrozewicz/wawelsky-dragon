"""Testy scenariusza E6-0 T3b (mcp_scenarios/mcp.yaml) — bez Dockera i sieci.

Zakres (``work/wp/E6-0/tasks/T3b-mcp-scenarios.md``): poprawne wczytanie przez
``load_mcp_scenario``, ``name == "mcp"``, obecność obu transportów, każdy krok
``call_tool`` z narzędziem, komplet podstawień ``{zmiennych}`` (wcześniejszy
``capture``), kroki przygotowawcze/sprzątające jako ``op: http`` bez nagrywania,
prefiks zasobów ``wd_rec_e6_mcp_``, kroki błędów z ``expect_error``.
"""

import re
from pathlib import Path

from mcp_runner import TRANSPORTS, load_mcp_scenario

NAME = "mcp"
RECORDER_DIR = Path(__file__).resolve().parent.parent
SCENARIO_PATH = RECORDER_DIR / "mcp_scenarios" / f"{NAME}.yaml"

MCP_OPS = ("initialize", "list_tools", "call_tool")
KNOWN_TOOLS = ("ragflow_retrieval", "ragflow_list_datasets", "ragflow_list_chats")
BOGUS_TOOL = "ragflow_unknown_tool"
TRANSPORT_PREFIX = {"streamable_http": "sha", "sse": "sse"}

SETUP_STEP_IDS = ("create_dataset", "upload", "parse", "poll_parse_done", "create_chat")
CLEANUP_STEP_IDS = ("delete_chat", "delete_dataset")
PREFIXED_NAMES = ("wd_rec_e6_mcp_ds", "wd_rec_e6_mcp_chat")
# Kroki, których wynik jest błędem: brak klucza (401 z middleware), zły klucz (401 z backendu),
# nieznane narzędzie i złe argumenty (CallToolResult.isError=true z serwera MCP).
ERROR_STEP_SUFFIXES = (
    "list_tools_no_auth",
    "list_tools_bad_key",
    "call_unknown_tool",
    "retrieval_missing_question",
    "retrieval_wrong_type_question",
)

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _scenario() -> dict:
    return load_mcp_scenario(SCENARIO_PATH)


def _steps() -> list[dict]:
    return _scenario()["steps"]


def _by_id() -> dict[str, dict]:
    return {step["id"]: step for step in _steps()}


def _mcp_steps() -> list[dict]:
    return [step for step in _steps() if step["op"] != "http"]


def _http_steps() -> list[dict]:
    return [step for step in _steps() if step["op"] == "http"]


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
    return _variables(
        [step.get("path"), step.get("json"), step.get("query"), step.get("arguments")]
    )


def test_load_mcp_scenario_ok():
    scenario = _scenario()
    assert isinstance(scenario, dict)
    assert scenario["name"] == NAME


def test_name_matches_file_name():
    assert _scenario()["name"] == SCENARIO_PATH.stem


def test_description_is_set():
    assert _scenario()["description"].strip()


def test_both_transports_present():
    transports = {step["transport"] for step in _mcp_steps()}
    assert transports == set(TRANSPORTS)


def test_each_transport_has_same_steps():
    per_transport = {transport: 0 for transport in TRANSPORTS}
    for step in _mcp_steps():
        per_transport[step["transport"]] += 1
    assert len(set(per_transport.values())) == 1, per_transport


def test_step_ids_unique_and_snake_case():
    ids = [step["id"] for step in _steps()]
    assert len(ids) == len(set(ids))
    for step_id in ids:
        assert re.fullmatch(r"[a-z0-9_]+", step_id), step_id


def test_mcp_steps_declare_transport_and_op():
    for step in _mcp_steps():
        assert step["op"] in MCP_OPS, step["id"]
        assert step["transport"] in TRANSPORTS, step["id"]


def test_every_call_tool_has_tool():
    seen: set[str] = set()
    for step in _mcp_steps():
        if step["op"] != "call_tool":
            continue
        tool = step.get("tool")
        assert isinstance(tool, str) and tool, step["id"]
        assert tool in set(KNOWN_TOOLS) | {BOGUS_TOOL}, step["id"]
        seen.add(tool)
    assert set(KNOWN_TOOLS) <= seen
    assert BOGUS_TOOL in seen


def test_initialize_and_list_tools_recorded_for_each_transport():
    for transport in TRANSPORTS:
        ops = [step["op"] for step in _mcp_steps() if step["transport"] == transport]
        assert "initialize" in ops, transport
        assert "list_tools" in ops, transport


def test_variables_have_prior_capture():
    captured: set[str] = set()
    for step in _steps():
        missing = _step_variables(step) - captured
        assert not missing, (
            f"{step['id']}: brak wcześniejszego capture {sorted(missing)}"
        )
        captured.update(step.get("capture") or {})


def test_setup_and_cleanup_are_http_and_not_recorded():
    steps = _steps()
    by_id = _by_id()
    for step_id in SETUP_STEP_IDS:
        assert by_id[step_id]["op"] == "http", step_id
        assert by_id[step_id].get("record") is False, step_id
    for step_id in CLEANUP_STEP_IDS:
        assert by_id[step_id]["op"] == "http", step_id
        assert by_id[step_id].get("record") is False, step_id
    assert [step["id"] for step in steps[: len(SETUP_STEP_IDS)]] == list(SETUP_STEP_IDS)
    assert [step["id"] for step in steps[-len(CLEANUP_STEP_IDS) :]] == list(
        CLEANUP_STEP_IDS
    )


def test_http_steps_are_v0_27_2_only():
    for step in _http_steps():
        assert step.get("versions") == ["v0.27.2"], step["id"]


def test_every_mcp_step_is_recorded():
    for step in _mcp_steps():
        assert step.get("record", True) is True, step["id"]


def test_error_steps_declare_expect_error():
    marked = {step["id"] for step in _mcp_steps() if step.get("expect_error")}
    expected = {
        f"{TRANSPORT_PREFIX[transport]}_{suffix}"
        for transport in TRANSPORTS
        for suffix in ERROR_STEP_SUFFIXES
    }
    assert marked == expected


def test_list_datasets_variants_present():
    by_id = _by_id()
    for transport in TRANSPORTS:
        prefix = TRANSPORT_PREFIX[transport]
        assert by_id[f"{prefix}_list_datasets_no_args"].get("arguments") is None
        assert by_id[f"{prefix}_list_datasets_paged"]["arguments"] == {
            "page": 1,
            "page_size": 10,
        }


def test_retrieval_with_and_without_dataset_ids():
    by_id = _by_id()
    for transport in TRANSPORTS:
        prefix = TRANSPORT_PREFIX[transport]
        with_ids = by_id[f"{prefix}_retrieval_dataset_ids"]["arguments"]
        assert with_ids["dataset_ids"] == ["{dataset_id}"]
        assert with_ids["question"]
        without_ids = by_id[f"{prefix}_retrieval_all_datasets"]["arguments"]
        assert "dataset_ids" not in without_ids
        assert without_ids["question"]


def test_auth_header_variants_per_transport():
    by_id = _by_id()
    for transport in TRANSPORTS:
        prefix = TRANSPORT_PREFIX[transport]
        assert by_id[f"{prefix}_list_tools"]["auth"] == "key"
        assert by_id[f"{prefix}_list_tools_api_key_header"]["auth"] == "api_key_header"
        assert by_id[f"{prefix}_list_tools_x_api_key_header"]["auth"] == "x_api_key"
        assert by_id[f"{prefix}_list_tools_no_auth"]["auth"] == "none"
        assert by_id[f"{prefix}_list_tools_bad_key"]["auth"] == "bad"


def test_created_names_use_e6_mcp_prefix():
    names = []
    for step in _http_steps():
        body = step.get("json")
        if isinstance(body, dict) and isinstance(body.get("name"), str):
            names.append(body["name"])
    assert set(names) == set(PREFIXED_NAMES)
    for name in names:
        assert name.startswith("wd_rec_e6_mcp_"), name


def test_poll_waits_for_parsed_document():
    poll = _by_id()["poll_parse_done"]
    assert poll.get("record") is False
    assert poll["method"] == "GET"
    assert poll["poll"]["until"] == {"path": "data.docs.0.run", "equals": "DONE"}


def test_cleanup_removes_every_created_resource():
    by_id = _by_id()
    assert by_id["delete_chat"]["json"] == {"ids": ["{chat_id}"]}
    assert by_id["delete_dataset"]["json"] == {"ids": ["{dataset_id}"]}
