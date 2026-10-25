"""Testy scenariusza E6-0 T1 (metadata_e6) — bez Dockera.

Zakres (``work/wp/E6-0/tasks/_scenario-common.md``): poprawność YAML, komplet
podstawień ``{zmiennych}``, kroki przygotowawcze/sprzątające bez nagrywania,
wyłącznie v0.27.2 (brak shimu v0.24.0), trasy z ``reports/T1-routes.md``,
pokrycie wszystkich operatorów ``meta_filter`` oraz kształt kroków błędów
(``metadata/config`` dokumentu, zły JSON ``metadata_condition``).
"""

import json
import re
from pathlib import Path

from runner import ALL_VERSIONS, AUTH_MODES, METHODS, load_scenario

NAME = "metadata_e6"
RECORDER_DIR = Path(__file__).resolve().parent.parent
SCENARIO_PATH = RECORDER_DIR / "scenarios" / f"{NAME}.yaml"
FIXTURE_NAMES = ("e6_meta_a.txt", "e6_meta_b.txt", "e6_meta_c.txt")
_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
ZERO_ID = "0" * 32

# Wykaz tras z reports/T1-routes.md: każdy nagrywany krok v0.27.2 to jedna z tych tras.
RECORDED_ROUTES = {
    ("PATCH", "/api/v1/datasets/{dataset_id}/documents/metadatas"),
    ("GET", "/api/v1/datasets/{dataset_id}/documents"),
    ("PUT", "/api/v1/datasets/{dataset_id}/documents/{doc_id_a}/metadata/config"),
    ("PUT", "/api/v1/datasets/{dataset_id}/documents/" + ZERO_ID + "/metadata/config"),
    ("POST", "/api/v1/retrieval"),
    ("POST", "/api/v1/chats"),
    ("POST", "/api/v1/chats/{chat_id_filtered}/completions"),
    ("POST", "/api/v1/chats/{chat_id}/completions"),
    ("PUT", "/api/v1/chats/{chat_id}"),
    ("PUT", "/api/v1/datasets/{dataset_id_auto}/metadata/config"),
    ("GET", "/api/v1/datasets/{dataset_id_auto}/metadata/config"),
    ("GET", "/api/v1/datasets/{dataset_id_auto}/documents"),
}
# Trasa pominięta w v0.27.2 (reports/T1-routes.md): GET konfiguracji dokumentu nie
# istnieje osobno — GET .../<doc_id> to download pliku (document_api.py:2138).
SKIPPED_ROUTES = {
    ("GET", "/api/v1/datasets/{dataset_id}/documents/{doc_id_a}/metadata/config"),
}

RECORDED_STEPS_V0_27 = 45
TOTAL_STEPS = 61
SETUP_STEP_IDS = (
    "create_dataset",
    "upload_a",
    "upload_b",
    "upload_c",
    "parse_all",
    "poll_doc_a",
    "poll_doc_b",
    "poll_doc_c",
    "create_chat",
)
CLEANUP_STEP_IDS = ("delete_chats", "delete_auto_dataset", "delete_dataset")
POLL_IDS = ("poll_doc_a", "poll_doc_b", "poll_doc_c", "poll_auto")
# Operatory obecne w meta_filter (common/metadata_utils.py:96-123); alias !=, >=, <=,
# jest mapowany w convert_conditions (l. 26); do listy dochodzi operator nieznany "bogus".
RAW_OPERATORS = {
    "=",
    "!=",
    ">",
    "<",
    ">=",
    "<=",
    "contains",
    "not contains",
    "in",
    "not in",
    "start with",
    "end with",
    "empty",
    "not empty",
    "bogus",
}
# Nagrywane kroki sukcesu bez jawnego ``expect`` (sukces sprawdzany domyślnie przez runner).
PLAIN_SUCCESS_IDS = {
    "list_docs_baseline",
    "get_doc_after_config",
    "get_auto_metadata_config",
    "get_auto_doc_after_parse",
    "create_chat_filtered",
    "chat_completion_json",
    "chat_completion_sse",
    "chat_completion_zero_json",
    "chat_completion_zero_sse",
}
PREFIXED_NAMES = (
    "wd_rec_e6_meta_ds",
    "wd_rec_e6_meta_chat",
    "wd_rec_e6_meta_chat_filtered",
    "wd_rec_e6_meta_auto_ds",
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


def _operators() -> set[str]:
    """Operatory z ``metadata_condition`` w query nagrywanych kroków listy dokumentów."""
    found: set[str] = set()
    for step in _steps():
        raw = (step.get("query") or {}).get("metadata_condition")
        if not isinstance(raw, str):
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue  # krok złego JSON-a
        for condition in parsed.get("conditions", []):
            found.add(condition["comparison_operator"])
    return found


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
    assert len(_recorded_steps("v0.27.2")) == RECORDED_STEPS_V0_27
    assert len(_recorded_steps()) == RECORDED_STEPS_V0_27


def test_setup_and_cleanup_are_not_recorded():
    steps = _steps()
    by_id = _by_id()
    for step_id in SETUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id
    for step_id in CLEANUP_STEP_IDS:
        assert by_id[step_id]["record"] is False, step_id
    assert [step["id"] for step in steps[: len(SETUP_STEP_IDS)]] == list(SETUP_STEP_IDS)
    assert [step["id"] for step in steps[-3:]] == list(CLEANUP_STEP_IDS)


def test_recorded_steps_declare_auth():
    for step in _recorded_steps():
        assert "auth" in step, step["id"]
        assert step["auth"] in AUTH_MODES, step["id"]


def test_recorded_routes_are_from_the_report():
    for step in _recorded_steps():
        assert (step["method"], step["path"]) in RECORDED_ROUTES, step["id"]


def test_skipped_routes_are_absent():
    """Trasa pobrania konfiguracji dokumentu nie istnieje osobno — GET .../<doc_id>
    to download pliku (document_api.py:2138), więc w scenariuszu jej nie ma."""
    for step in _steps():
        assert (step["method"], step["path"]) not in SKIPPED_ROUTES, step["id"]


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


def test_poll_waits_for_every_parsed_document():
    polls = _by_id()
    for step_id in POLL_IDS:
        step = polls[step_id]
        assert "poll" in step, step_id
        assert step["record"] is False, step_id
        assert step["poll"]["until"]["equals"] == "DONE", step_id
    # poll po wszystkich trzech dokumentach datasetu + jeden dokument datasetu auto
    assert polls["poll_doc_a"]["query"] == {"id": "{doc_id_a}"}
    assert polls["poll_doc_b"]["query"] == {"id": "{doc_id_b}"}
    assert polls["poll_doc_c"]["query"] == {"id": "{doc_id_c}"}
    assert polls["poll_auto"]["query"] == {"id": "{doc_id_auto}"}


def test_all_meta_filter_operators_are_covered():
    assert _operators() == RAW_OPERATORS


def test_condition_steps_use_query_json_string():
    """metadata_condition listy dokumentów to JSON-string w query (document_api.py:1066)."""
    for step in _recorded_steps():
        if not step["id"].startswith("cond_"):
            continue
        raw = (step.get("query") or {}).get("metadata_condition")
        assert isinstance(raw, str), step["id"]
    assert _by_id()["cond_bad_json"]["expect"] == {"status": 200, "code": 102}


def test_document_metadata_config_errors():
    by_id = _by_id()
    assert by_id["put_doc_metadata_config"]["json"]["metadata"]["type"] == "object"
    # brak pola `metadata` -> ARGUMENT_ERROR (101)
    assert by_id["put_doc_metadata_config_missing_metadata"]["expect"] == {
        "status": 200,
        "code": 101,
    }
    # nieistniejący dokument i cudzy dataset -> DATA_ERROR (102)
    assert by_id["put_doc_metadata_config_missing_doc"]["expect"] == {
        "status": 200,
        "code": 102,
    }
    second = by_id["put_doc_metadata_config_second_user"]
    assert second["auth"] == "second"
    assert second["expect"] == {"status": 200, "code": 102}
    # skutek: GET listy z filtrem ?id=<doc> po zmianie konfiguracji
    assert by_id["get_doc_after_config"]["query"] == {"id": "{doc_id_a}"}


def test_retrieval_covers_all_meta_data_filter_modes():
    by_id = _by_id()
    expected = {
        "retrieval_metadata_condition_only": "metadata_condition",
        "retrieval_manual_one_doc": "meta_data_filter",
        "retrieval_manual_no_match": "meta_data_filter",
        "retrieval_auto": "meta_data_filter",
        "retrieval_semi_auto": "meta_data_filter",
        "retrieval_condition_and_filter": "meta_data_filter",
    }
    for step_id, kind in expected.items():
        body = by_id[step_id]["json"]
        assert kind in body, step_id
    # manual zawężający do dokładnie 1 dokumentu: autor A AND rok 2020
    manual = by_id["retrieval_manual_one_doc"]["json"]["meta_data_filter"]
    assert manual["method"] == "manual"
    assert manual["logic"] == "and"
    assert [(f["key"], f["op"], f["value"]) for f in manual["manual"]] == [
        ("author", "=", "A"),
        ("year", "=", "2020"),
    ]
    assert by_id["retrieval_auto"]["json"]["meta_data_filter"] == {"method": "auto"}
    assert (
        by_id["retrieval_semi_auto"]["json"]["meta_data_filter"]["method"]
        == "semi_auto"
    )
    # krok z obydwoma: metadata_condition (autor A) + meta_data_filter (autor B)
    both = by_id["retrieval_condition_and_filter"]["json"]
    assert both["metadata_condition"]["conditions"][0]["value"] == "A"
    assert both["meta_data_filter"]["manual"][0]["value"] == "B"


def test_chat_steps_cover_json_and_sse_for_both_filters():
    by_id = _by_id()
    filtered = by_id["create_chat_filtered"]["json"]["meta_data_filter"]
    assert filtered["method"] == "manual"
    # filtr czatu zawęża do dokładnie 1 dokumentu: autor A AND rok 2020
    assert [f["key"] for f in filtered["manual"]] == ["author", "year"]
    assert (
        by_id["update_chat_zero"]["json"]["meta_data_filter"]["manual"][0]["value"]
        == "Z"
    )
    for step_id in ("chat_completion_sse", "chat_completion_zero_sse"):
        step = by_id[step_id]
        assert step.get("stream") is True, step_id
        assert step["json"]["stream"] is True, step_id
    for step_id in ("chat_completion_json", "chat_completion_zero_json"):
        step = by_id[step_id]
        assert "stream" not in step, step_id
        assert step["json"]["stream"] is False, step_id


def test_auto_metadata_dataset_enables_metadata_and_config_fields():
    by_id = _by_id()
    create = by_id["create_auto_dataset"]
    assert create["record"] is False
    assert create["json"]["parser_config"] == {"enable_metadata": True}
    put = by_id["put_auto_metadata_config"]
    assert put.get("record", True) is True
    assert {field["key"] for field in put["json"]["metadata"]} == {"author", "year"}
    assert by_id["get_auto_doc_after_parse"]["query"] == {"id": "{doc_id_auto}"}


def test_fixture_files_exist():
    for name in FIXTURE_NAMES:
        path = RECORDER_DIR / "fixtures" / name
        assert path.is_file(), name
        assert path.read_text(encoding="utf-8").strip(), name


def test_names_use_e6_meta_prefix():
    names = []
    for step in _steps():
        body = step.get("json")
        if isinstance(body, dict) and isinstance(body.get("name"), str):
            names.append(body["name"])
    assert set(names) == set(PREFIXED_NAMES)
    for name in names:
        assert name.startswith("wd_rec_e6_meta_"), name


def test_cleanup_removes_every_created_resource():
    by_id = _by_id()
    assert by_id["delete_chats"]["json"] == {"ids": ["{chat_id}", "{chat_id_filtered}"]}
    assert by_id["delete_auto_dataset"]["json"] == {"ids": ["{dataset_id_auto}"]}
    assert by_id["delete_dataset"]["json"] == {"ids": ["{dataset_id}"]}


def test_step_ids_are_snake_case():
    for step in _steps():
        assert re.fullmatch(r"[a-z0-9_]+", step["id"]), step["id"]
