"""Testy walidacyjne scenariusza T3 WP E4-45g (file_legacy.yaml) — bez Dockera.

Zakres (work/wp/E4-45g/tasks/_scenario-common.md, work/wp/E2-0/tasks/_scenario-common.md):
``load_scenario`` przechodzi, ``name`` == nazwa pliku, każdy krok jest ``record: false``
albo ma jawnie sensowne ``auth``/``expect``, a każda zmienna ``{x}`` w ``path``/``query``/
``json`` ma wcześniejszy ``capture``.

Dodatkowo dla T3: scenariusz nagrywa legacy trasy ``/api/v1/file/*`` w OBU wersjach
(v0.24.0 ``api/apps/sdk/files.py``, v0.27.2 ``api/apps/backward_compat.py``), więc żadna
z tras z zakresu nie może zniknąć; ``upload_info`` istnieje tylko w v0.27.2; ciała ``rm``
różnią się między wersjami (``file_ids`` vs ``ids``); scenariusz nagrywa pobranie binarne,
proby cudzego zasobu kluczem ``second`` i sprząta po sobie.
"""

import re
from pathlib import Path

import pytest
from runner import AUTH_MODES, load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
FILES = ("file_legacy.yaml",)
ALL_VERSIONS = ("v0.24.0", "v0.27.2")

# Trasy legacy menedżera plików wymagane w każdej z wersji (ścieżki bez parametrów ścieżki
# i bez query — jak szablony w scenariuszu).
ROUTES_IN_BOTH = (
    "/api/v1/file/create",
    "/api/v1/file/upload",
    "/api/v1/file/list",
    "/api/v1/file/root_folder",
    "/api/v1/file/parent_folder",
    "/api/v1/file/all_parent_folder",
    "/api/v1/file/get/{file_id}",
    "/api/v1/file/mv",
    "/api/v1/file/rename",
    "/api/v1/file/convert",
    "/api/v1/file/rm",
)
ROUTES_V0_27_2_ONLY = ("/api/v1/file/upload_info",)
# Trasa v0.24.0 pominięta w scenariuszu (powód w work/wp/E4-45g/reports/T3-routes.md).
ROUTES_SKIPPED = ("/api/v1/file/download/<attachment_id>",)

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _scenario(filename: str) -> dict:
    return load_scenario(SCENARIOS_DIR / filename)


def _steps(filename: str) -> list[dict]:
    return _scenario(filename)["steps"]


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


def _versions(step: dict) -> set[str]:
    return set(step.get("versions", ALL_VERSIONS))


def _covers(path: str, version: str) -> bool:
    return any(
        step["path"] == path and version in _versions(step) for step in _steps(FILES[0])
    )


@pytest.mark.parametrize("filename", FILES)
def test_name_matches_file_name(filename):
    assert _scenario(filename)["name"] == Path(filename).stem


@pytest.mark.parametrize("filename", FILES)
def test_description_is_set(filename):
    assert _scenario(filename)["description"].strip()


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


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_legacy_routes_are_covered_in_both_versions(version):
    """Każda trasa z zakresu (poza ``upload_info``, tylko v0.27.2) ma krok w tej wersji."""
    missing = [route for route in ROUTES_IN_BOTH if not _covers(route, version)]
    assert not missing, f"{version}: brak kroków dla {missing}"


def test_v0_24_parent_folder_step_tolerates_upstream_bug():
    """v0.24.0 ``get_parent_folder()`` (``sdk/files.py:360``) nie przyjmuje parametru,
    a ``@token_required`` wstrzykuje ``tenant_id`` → ``TypeError`` (HTTP 200, code 100).
    Krok v0.24.0 nagrywa ten fakt (``expect: any``); krok v0.27.2 działa normalnie."""
    steps = _steps(FILES[0])
    route = "/api/v1/file/parent_folder"
    happy_path = [
        step
        for step in steps
        if step["id"].startswith("get_parent_folder") and step["path"] == route
    ]
    v0_24 = [step for step in happy_path if "v0.24.0" in _versions(step)]
    v0_27 = [step for step in happy_path if "v0.27.2" in _versions(step)]
    assert len(v0_24) == 1 and len(v0_27) == 1
    assert v0_24[0].get("expect") == "any", v0_24[0]["id"]
    assert "expect" not in v0_27[0], v0_27[0]["id"]


def test_paged_listing_sends_explicit_pagination_and_order():
    """``list_root_paged`` pinuje kształt zapytania (v0.24.0 czyta ``desc`` jako string
    → zawsze malejąco; patrz T3-notes.md §3)."""
    paged = [step for step in _steps(FILES[0]) if step["id"] == "list_root_paged"]
    assert len(paged) == 1
    assert paged[0]["query"] == {
        "page": 1,
        "page_size": 1,
        "orderby": "name",
        "desc": False,
    }


def test_upload_info_is_recorded_only_for_v0_27_2():
    for route in ROUTES_V0_27_2_ONLY:
        assert _covers(route, "v0.27.2"), route
        assert not _covers(route, "v0.24.0"), route


def test_skipped_download_route_is_absent():
    """``/file/download/<attachment_id>`` (tylko v0.24.0) nie ma kroku — patrz raport tras."""
    paths = {step["path"] for step in _steps(FILES[0])}
    for route in ROUTES_SKIPPED:
        assert route not in paths


def test_rm_bodies_differ_per_version():
    """SDK v0.24.0 przyjmuje ``file_ids``, v0.27.2 (``DeleteFileReq``) — ``ids``."""
    versions_of = {"v0.24.0": "file_ids", "v0.27.2": "ids"}
    for version, key in versions_of.items():
        rms = [
            step
            for step in _steps(FILES[0])
            if step["path"] == "/api/v1/file/rm"
            and version in _versions(step)
            and step.get("record", True)
            and "expect" not in step
        ]
        assert rms, f"{version}: brak nagrywanego (skutecznego) kroku rm"
        for step in rms:
            assert set(step["json"]) == {key}, step["id"]


@pytest.mark.parametrize("filename", FILES)
def test_binary_download_step_exists(filename):
    """Pobranie pliku nagrywamy jako odpowiedź binarną (status/content-type/sha256)."""
    binary = [step for step in _steps(filename) if step.get("binary")]
    assert binary, "brak kroku z 'binary: true'"
    assert any(step["method"].upper() == "GET" for step in binary), (
        "binary tylko dla GET"
    )
    assert any(step["path"] == "/api/v1/file/get/{file_id}" for step in binary), (
        "brak binarnego kroku pobrania /file/get/{file_id}"
    )


@pytest.mark.parametrize("filename", FILES)
def test_second_user_probes_denied_on_get_rm_move(filename):
    """Odczyt/usunięcie/przeniesienie cudzego zasobu kluczem ``second`` (get/rm/mv)."""
    second = [step for step in _steps(filename) if step.get("auth") == "second"]
    assert {step["path"] for step in second} >= {
        "/api/v1/file/get/{probe_id}",
        "/api/v1/file/rm",
        "/api/v1/file/mv",
    }
    for step in second:
        assert step.get("expect") == "any", step["id"]


@pytest.mark.parametrize("filename", FILES)
def test_scenario_cleans_up_created_resources(filename):
    """Scenariusz usuwa plik, folder i sondę oraz dataset (dataset bez nagrywania)."""
    steps = _steps(filename)
    # plik i folder: skuteczny (bez expect) rm w każdej wersji
    for version, variable in (("v0.24.0", "{file_id}"), ("v0.27.2", "{file_id}")):
        cleanup = [
            step
            for step in steps
            if step["path"] == "/api/v1/file/rm"
            and version in _versions(step)
            and step.get("record", True)
            and "expect" not in step
        ]
        ids_lists = [
            step["json"]["file_ids"]
            if "file_ids" in step["json"]
            else step["json"]["ids"]
            for step in cleanup
        ]
        deleted = {item for ids in ids_lists for item in ids}
        assert variable in deleted, f"{version}: brak rm pliku {variable}"
        assert "{folder_id}" in deleted, f"{version}: brak rm folderu"
    # sonda i dataset: bez nagrywania
    probe_deletes = [step for step in steps if step["id"].startswith("rm_probe_")]
    assert len(probe_deletes) == 2
    assert all(step.get("record") is False for step in probe_deletes)
    dataset_delete = [step for step in steps if step["id"] == "delete_dataset"]
    assert len(dataset_delete) == 1
    assert dataset_delete[0].get("record") is False


@pytest.mark.parametrize("filename", FILES)
def test_preparation_poll_waits_for_linked_document(filename):
    """Krok konwersji czeka, aż dokument pojawi się w liście datasetu (poll)."""
    polls = [step for step in _steps(filename) if "poll" in step]
    assert len(polls) == 1
    poll = polls[0]
    assert poll["poll"]["until"] == {"path": "data.total", "equals": 1}
    assert poll["path"] == "/api/v1/datasets/{dataset_id}/documents"
