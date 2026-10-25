"""Testy walidacyjne scenariuszy S3 WP E2-0 (chat_extras, openai_dify) — bez Dockera.

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
FILES = ("chat_extras.yaml", "openai_dify.yaml")

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
    """Pierwsze kroki (przygotowanie) i ostatnie (sprzątanie) nie trafiają do złota."""
    steps = _scenario(filename)["steps"]
    assert steps[0].get("record") is False, steps[0]["id"]
    assert steps[-1].get("record") is False, steps[-1]["id"]
    assert steps[-2].get("record") is False, steps[-2]["id"]


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
    prepare = [step for step in polls if step["id"] == "poll_parse_done"]
    assert len(prepare) == 1
    assert prepare[0].get("record") is False, prepare[0]["id"]
    assert prepare[0]["poll"]["until"]["equals"] == "DONE", prepare[0]["id"]
    for step in polls:
        assert step.get("record") is False, step["id"]


def test_openai_dify_waits_for_index_and_retrieval():
    """Po ``poll_parse_done`` scenariusz czeka na widoczność chunki i retriewalu.

    Indeks ES odświeża się do 1 s, więc zaraz po parsowaniu liczba chunki bywa
    jeszcze zerowa; bez tego kroku odpowiedź raz nie ma treści, raz ma (T4).
    """
    steps = _scenario("openai_dify.yaml")["steps"]
    ids = [step["id"] for step in steps]
    for step_id in ("wait_index", "wait_retrieval"):
        step = next(item for item in steps if item["id"] == step_id)
        assert step.get("record") is False, step_id
        assert step["poll"] == {
            "until": {"path": "data.total", "equals": 1},
            "interval_s": 2,
            "timeout_s": 60,
        }, step_id
    assert ids.index("poll_parse_done") < ids.index("wait_index")
    assert ids.index("wait_index") < ids.index("wait_retrieval")
    assert ids.index("wait_retrieval") < ids.index("create_chat")


@pytest.mark.parametrize("filename", FILES)
def test_stream_steps_are_post(filename):
    """Runner czyta strumień tylko dla POST (``client.stream("POST", …)``)."""
    for step in _scenario(filename)["steps"]:
        if step.get("stream"):
            assert step["method"].upper() == "POST", step["id"]


@pytest.mark.parametrize("filename", FILES)
def test_cleanup_removes_created_resources(filename):
    """Scenariusz usuwa każdy utworzony czat i dataset (Wspólne zasady)."""
    steps = _scenario(filename)["steps"]
    creations = [step for step in steps if step.get("capture", {}).get("chat_id")] + [
        step for step in steps if step.get("capture", {}).get("chat_id_2")
    ]
    for creation in creations:
        variable = (
            "chat_id_2" if "chat_id_2" in creation.get("capture", {}) else "chat_id"
        )
        deletes = [
            step
            for step in steps
            if step["method"].upper() == "DELETE"
            and step.get("json") == {"ids": [f"{{{variable}}}"]}
        ]
        assert len(deletes) == 1, creation["id"]
    datasets = [step for step in steps if step.get("capture", {}).get("dataset_id")]
    assert len(datasets) == 1, filename
    assert steps[-1].get("json") == {"ids": ["{dataset_id}"]}, steps[-1]["id"]


def test_chat_extras_records_message_delete_and_feedback():
    """Delete wiadomości i feedback istnieją w źródle tylko w v0.27.2 (raport S3-routes)."""
    steps = _scenario("chat_extras.yaml")["steps"]
    for step_id, method, suffix in (
        ("delete_message", "DELETE", "/messages/{msg_id}"),
        ("message_feedback", "PUT", "/messages/{msg_id}/feedback"),
    ):
        matched = [step for step in steps if step["id"] == step_id]
        assert len(matched) == 1, step_id
        step = matched[0]
        assert step["method"].upper() == method, step_id
        assert step["path"].endswith(suffix), step_id
        assert step.get("versions") == ["v0.27.2"], step_id
        assert step.get("record", True) is not False, step_id


def test_chat_extras_message_id_comes_from_session_read():
    """``msg_id`` dla delete/feedback pochodzi z odczytu sesji (``capture``)."""
    steps = _scenario("chat_extras.yaml")["steps"]
    readers = [step for step in steps if step.get("capture", {}).get("msg_id")]
    assert len(readers) == 1, "oczekiwany dokładnie jeden capture msg_id"
    assert readers[0]["path"].endswith("/sessions/{session_id}"), readers[0]["id"]
    assert steps.index(readers[0]) < next(
        index for index, step in enumerate(steps) if step["id"] == "delete_message"
    )


def test_openai_dify_has_health_without_auth():
    """``/dify/retrieval/health`` nie ma dekoratora logowania (v0.27.2)."""
    steps = _scenario("openai_dify.yaml")["steps"]
    matched = [step for step in steps if step["id"] == "dify_retrieval_health"]
    assert len(matched) == 1
    assert matched[0]["auth"] == "none", matched[0]
    assert matched[0].get("versions") == ["v0.27.2"], matched[0]
