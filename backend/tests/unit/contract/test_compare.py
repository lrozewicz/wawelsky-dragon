"""Unit testy komparatora złota `compare.py` — przypadki z T4-harness.md p. 11 i K11 §5 p. 4-5."""

import json
from pathlib import Path

import pytest
import yaml

from tests.contract.ragflow.compare import Deviation, Diff, compare_file, load_deviations, unmatched

FILE = "datasets/x--01.json"
REQUEST = {"method": "GET", "path": "/api/v1/datasets", "query": {}, "body": None}
B_CODE_0 = {"code": 0}
B_NAME_A = {"code": 0, "data": {"name": "a"}}
B_DESC_A = {"code": 0, "data": {"description": "a"}}


def _write(
    path: Path,
    body: object,
    *,
    status: int = 200,
    ctype: str = "application/json",
    request: object = REQUEST,
) -> Path:
    """Buduje plik odpowiedzi w formacie złota runnera (request/status/headers/body)."""
    document = {
        "request": request,
        "status": status,
        "headers": {"content-type": ctype},
        "body": body,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _diffs(expected: list[tuple[str, str, object, object]]) -> list[Diff]:
    """Oczekiwane Diffy dla pliku datasets/x--01.json z wierszy (path, kind, golden, actual)."""
    return [Diff(FILE, path, kind, golden, actual) for path, kind, golden, actual in expected]


CASES: list[tuple[str, object, object, dict[str, str], list[tuple[str, str, object, object]]]] = [
    # (id, golden body, actual body, rules, oczekiwane (path, kind, golden, actual))
    ("identical", B_NAME_A, B_NAME_A, {}, []),
    (
        "token_equal",
        {"code": 0, "data": {"t": "<TOKEN>"}},
        {"code": 0, "data": {"t": "<TOKEN>"}},
        {},
        [],
    ),
    (
        "name_value_c",
        B_NAME_A,
        {"code": 0, "data": {"name": "b"}},
        {},
        [("body.data.name", "value", "a", "b")],
    ),
    ("description_type_e", B_DESC_A, {"code": 0, "data": {"description": "b"}}, {}, []),
    (
        "rule_exact_on_type_field_a",
        B_DESC_A,
        {"code": 0, "data": {"description": "b"}},
        {"data.description": "exact"},
        [("body.data.description", "value", "a", "b")],
    ),
    ("rule_exact_equal", B_DESC_A, B_DESC_A, {"data.description": "exact"}, []),
    (
        "rule_ignore_object_a",
        {"code": 0, "data": {"x": 1, "y": 2}},
        {"code": 0, "data": {"z": 9}},
        {"data": "ignore"},
        [],
    ),
    (
        "rule_type_list_length_a",
        {"code": 0, "data": [1, 2]},
        {"code": 0, "data": [1]},
        {"data": "type"},
        [],
    ),
    (
        "rule_type_list_types_a",
        {"code": 0, "data": [1]},
        {"code": 0, "data": "x"},
        {"data": "type"},
        [("body.data", "type", [1], "x")],
    ),
    (
        "ts_tokens_value_b",
        {"code": 0, "data": {"t": "<TS_MS>"}},
        {"code": 0, "data": {"t": "<TS_S>"}},
        {},
        [("body.data.t", "value", "<TS_MS>", "<TS_S>")],
    ),
    (
        "id_token_value_b",
        {"code": 0, "data": {"id": "<ID:dataset#1>"}},
        {"code": 0, "data": {"id": "<ID:dataset#2>"}},
        {},
        [("body.data.id", "value", "<ID:dataset#1>", "<ID:dataset#2>")],
    ),
    (
        "ignore_token_b",
        {"code": 0, "data": {"d": "<IGNORE>"}},
        {"code": 0, "data": {"d": "cokolwiek"}},
        {},
        [],
    ),
    (
        "parser_chunk_token_num_d",
        {"code": 0, "data": {"parser_config": {"chunk_token_num": 512}}},
        {"code": 0, "data": {"parser_config": {"chunk_token_num": 256}}},
        {},
        [("body.data.parser_config.chunk_token_num", "value", 512, 256)],
    ),
    (
        "parser_llm_id_d",
        {"code": 0, "data": {"parser_config": {"llm_id": "x@f"}}},
        {"code": 0, "data": {"parser_config": {"llm_id": "y"}}},
        {},
        [],
    ),
    (
        "description_str_vs_null_e",
        {"code": 0, "data": {"description": None}},
        {"code": 0, "data": {"description": "text"}},
        {},
        [("body.data.description", "type", None, "text")],
    ),
    (
        "exact_bool_vs_int_type",
        {"code": 0, "data": {"available": True}},
        {"code": 0, "data": {"available": 1}},
        {"data.available": "exact"},
        [("body.data.available", "type", True, 1)],
    ),
    (
        "int_vs_float_rule_type",
        {"code": 0, "data": {"threshold": 1}},
        {"code": 0, "data": {"threshold": 1.0}},
        {"data.threshold": "type"},
        [],
    ),
    ("q2_message_code_0", B_CODE_0, {"code": 0, "message": "success"}, {}, []),
    (
        "q2_message_code_102",
        {"code": 102},
        {"code": 102, "message": "x"},
        {},
        [("body.message", "extra", None, "x")],
    ),
    (
        "extra_other_key",
        B_CODE_0,
        {"code": 0, "total": 5},
        {},
        [("body.total", "extra", None, 5)],
    ),
    (
        "extra_message_deeper",
        {"code": 0, "data": {}},
        {"code": 0, "data": {"message": "m"}},
        {},
        [("body.data.message", "extra", None, "m")],
    ),
    (
        "missing_key",
        {"code": 0, "data": {"a": 1, "b": 2}},
        {"code": 0, "data": {"a": 1}},
        {},
        [("body.data.b", "missing", 2, None)],
    ),
    (
        "list_length",
        {"code": 0, "data": [1, 2]},
        {"code": 0, "data": [1]},
        {},
        [("body.data", "length", 2, 1)],
    ),
    (
        "dict_vs_list_type",
        {"code": 0, "data": {"x": 1}},
        {"code": 0, "data": [1]},
        {},
        [("body.data", "type", {"x": 1}, [1])],
    ),
    (
        "list_elements_type_only",
        {"code": 0, "data": [1, "x"]},
        {"code": 0, "data": [2, "x"]},
        {},
        [],
    ),
    (
        "leaf_number_type_only",
        {"code": 0, "data": {"pagerank": 0.5}},
        {"code": 0, "data": {"pagerank": 0.9}},
        {},
        [],
    ),
]


@pytest.mark.parametrize(
    ("golden_body", "actual_body", "rules", "expected"),
    [pytest.param(g, a, r, e, id=cid) for cid, g, a, r, e in CASES],
)
def test_body_cases(
    golden_body: object,
    actual_body: object,
    rules: dict[str, str],
    expected: list[tuple[str, str, object, object]],
    tmp_path: Path,
) -> None:
    """Każdy wiersz T4-harness.md p. 11 jako osobny przypadek porównania body."""
    golden = _write(tmp_path / "golden" / "datasets" / "x--01.json", golden_body)
    actual = _write(tmp_path / "actual" / "datasets" / "x--01.json", actual_body)
    assert compare_file(golden, actual, rules) == _diffs(expected)


def test_request_mismatch(tmp_path: Path) -> None:
    """Różne request (method/path/query/body) → jeden Diff request (K11 §5 p. 4)."""
    request_g = {"method": "POST", "path": "/api/v1/datasets", "query": {}, "body": {"name": "a"}}
    request_a = {"method": "PUT", "path": "/api/v1/datasets", "query": {}, "body": {"name": "a"}}
    golden = _write(tmp_path / "golden" / "datasets" / "x--01.json", B_CODE_0, request=request_g)
    actual = _write(tmp_path / "actual" / "datasets" / "x--01.json", B_CODE_0, request=request_a)
    assert compare_file(golden, actual, {}) == [
        Diff(FILE, "request", "request", request_g, request_a)
    ]


def test_status_mismatch(tmp_path: Path) -> None:
    """Różny status HTTP → Diff status (K11 §5 p. 4)."""
    golden = _write(tmp_path / "golden" / "datasets" / "x--01.json", B_CODE_0, status=200)
    actual = _write(tmp_path / "actual" / "datasets" / "x--01.json", B_CODE_0, status=404)
    assert compare_file(golden, actual, {}) == [Diff(FILE, "status", "status", 200, 404)]


def test_content_type_charset_ignored(tmp_path: Path) -> None:
    """Ten sam typ przed średnikiem, różne parametry → brak Diffów (K11 §5 p. 4)."""
    golden = _write(tmp_path / "golden" / "datasets" / "x--01.json", B_CODE_0)
    actual = _write(
        tmp_path / "actual" / "datasets" / "x--01.json",
        B_CODE_0,
        ctype="application/json; charset=utf-8",
    )
    assert compare_file(golden, actual, {}) == []


def test_content_type_mismatch(tmp_path: Path) -> None:
    """Różny typ treści → Diff content_type z częścią przed średnikiem (K11 §5 p. 4)."""
    golden = _write(tmp_path / "golden" / "datasets" / "x--01.json", B_CODE_0)
    actual = _write(tmp_path / "actual" / "datasets" / "x--01.json", B_CODE_0, ctype="text/html")
    assert compare_file(golden, actual, {}) == [
        Diff(FILE, "headers.content-type", "content_type", "application/json", "text/html"),
    ]


def test_sse_equal(tmp_path: Path) -> None:
    """Identyczne bajty .sse → brak Diffów (K11 §5 p. 4)."""
    golden = tmp_path / "golden" / "chats" / "x--01.sse"
    actual = tmp_path / "actual" / "chats" / "x--01.sse"
    for path in (golden, actual):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data: a\n\n")
    assert compare_file(golden, actual, {}) == []


def test_sse_mismatch(tmp_path: Path) -> None:
    """Różne bajty .sse → jeden Diff value na body z treścią jako tekst (K11 §5 p. 4)."""
    golden = tmp_path / "golden" / "chats" / "x--01.sse"
    actual = tmp_path / "actual" / "chats" / "x--01.sse"
    golden.parent.mkdir(parents=True)
    actual.parent.mkdir(parents=True)
    golden.write_bytes(b"data: a\n\n")
    actual.write_bytes(b"data: b\n\n")
    assert compare_file(golden, actual, {}) == [
        Diff("chats/x--01.sse", "body", "value", "data: a\n\n", "data: b\n\n")
    ]


def test_load_deviations_missing_file(tmp_path: Path) -> None:
    """Brak pliku odchyłek → pusta lista (T4-harness p. 4)."""
    assert load_deviations(tmp_path / "deviations" / "users_me.yaml") == []


def test_load_deviations_valid(tmp_path: Path) -> None:
    """Poprawny wpis → Deviation z tymi samymi polami (T4-harness p. 4)."""
    entry = {
        "file": "d/f--01.json",
        "path": "body.data.0.content",
        "kind": "value",
        "reason": "chunker WD tnie inaczej",
    }
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    assert load_deviations(path) == [
        Deviation("d/f--01.json", "body.data.0.content", "value", "chunker WD tnie inaczej"),
    ]


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(
            {"file": "f.json", "path": "body.status", "kind": "status", "reason": "r"},
            id="kind_status",
        ),
        pytest.param(
            {
                "file": "f.json",
                "path": "headers.content-type",
                "kind": "content_type",
                "reason": "r",
            },
            id="kind_content_type",
        ),
        pytest.param(
            {"file": "f.json", "path": "request", "kind": "request", "reason": "r"},
            id="kind_request",
        ),
        pytest.param(
            {"file": "f.json", "path": "body.code", "kind": "value", "reason": "r"},
            id="value_on_code",
        ),
        pytest.param(
            {"file": "f.json", "path": "body.data", "kind": "missing", "reason": "r"},
            id="missing_body_data",
        ),
        pytest.param(
            {"file": "f.json", "path": "body.data.id", "kind": "extra", "reason": "r"},
            id="extra_under_body_data",
        ),
        pytest.param(
            {"file": "f.json", "path": "body.data.id", "kind": "inny", "reason": "r"}, id="bad_kind"
        ),
        pytest.param(
            {"file": "f.json", "path": "body.data.id", "kind": "value", "reason": ""},
            id="empty_reason",
        ),
        pytest.param({"file": "f.json", "path": "body.data.id", "kind": "value"}, id="no_reason"),
    ],
)
def test_load_deviations_rejects(entry: dict[str, str], tmp_path: Path) -> None:
    """Wpis zakazany (C0 p. 4), zły kind albo pusty/brak reason → ValueError z file i path."""
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_deviations(path)
    message = str(exc.value)
    assert entry["file"] in message
    assert entry["path"] in message


def test_load_deviations_contract_allows_body_data(tmp_path: Path) -> None:
    """Wpis missing/extra pod body.data z niepustym contract: → przyjęty (K11 §10b p. 7)."""
    first = {
        "file": "c/x--10.json",
        "path": "body.data.final",
        "kind": "missing",
        "reason": "r",
        "contract": "K4 §1.7",
    }
    second = {
        "file": "c/x--10.json",
        "path": "body.data.reference.total",
        "kind": "extra",
        "reason": "r",
        "contract": "K4 §1.7",
    }
    expected_first = Deviation("c/x--10.json", "body.data.final", "missing", "r", "K4 §1.7")
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([first]), encoding="utf-8")
    assert load_deviations(path) == [expected_first]
    path.write_text(yaml.safe_dump([first, second]), encoding="utf-8")
    assert load_deviations(path) == [
        expected_first,
        Deviation("c/x--10.json", "body.data.reference.total", "extra", "r", "K4 §1.7"),
    ]


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(
            {
                "file": "c/x--10.json",
                "path": "body.data.final",
                "kind": "missing",
                "reason": "r",
                "contract": "",
            },
            id="contract_empty",
        ),
        pytest.param(
            {
                "file": "c/x--10.json",
                "path": "body.data",
                "kind": "missing",
                "reason": "r",
                "contract": "K4 §1.7",
            },
            id="contract_on_body_data_itself",
        ),
        pytest.param(
            {
                "file": "c/x--10.json",
                "path": "body.data.*.id",
                "kind": "extra",
                "reason": "r",
                "contract": "K4 §1.7",
            },
            id="contract_wildcard",
        ),
        pytest.param(
            {
                "file": "c/x--10.json",
                "path": "body.data..id",
                "kind": "extra",
                "reason": "r",
                "contract": "K4 §1.7",
            },
            id="contract_empty_segment",
        ),
        pytest.param(
            {
                "file": "c/x--10.json",
                "path": "body.status",
                "kind": "status",
                "reason": "r",
                "contract": "K4 §1.7",
            },
            id="contract_does_not_unlock_status",
        ),
        pytest.param(
            {
                "file": "c/x--10.json",
                "path": "body.code",
                "kind": "value",
                "reason": "r",
                "contract": "K4 §1.7",
            },
            id="contract_does_not_unlock_code",
        ),
    ],
)
def test_load_deviations_contract_rejected(entry: dict[str, str], tmp_path: Path) -> None:
    """contract: nie odblokowuje niczego poza missing/extra pod body.data.* (K11 §10b p. 7)."""
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_deviations(path)
    message = str(exc.value)
    assert entry["file"] in message
    assert entry["path"] in message


@pytest.mark.parametrize("contract", [None, 17], ids=["contract_null", "contract_int"])
def test_load_deviations_contract_not_string(contract: object, tmp_path: Path) -> None:
    """contract: musi być napisem z YAML — null/liczba → ValueError (nie str(None) == "None")."""
    entry = {
        "file": "c/x--10.json",
        "path": "body.data.final",
        "kind": "missing",
        "reason": "r",
        "contract": contract,
    }
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    with pytest.raises(ValueError, match="contract musi być napisem") as exc:
        load_deviations(path)
    assert "c/x--10.json" in str(exc.value)
    assert "body.data.final" in str(exc.value)


SANCTIONED_FILE = "datasets___documents/errors_access--13.json"
P15_CONTRACT = "K11 §10d p. 15"


def test_load_deviations_p15_sanctions_code_value(tmp_path: Path) -> None:
    """Wpis value dla body.code z contract K11 §10d p. 15 w pliku sankcjonowanym → przyjęty (C5)."""
    entry = {
        "file": SANCTIONED_FILE,
        "path": "body.code",
        "kind": "value",
        "reason": "x",
        "contract": P15_CONTRACT,
    }
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    assert load_deviations(path) == [
        Deviation(SANCTIONED_FILE, "body.code", "value", "x", P15_CONTRACT)
    ]


@pytest.mark.parametrize(
    ("kind", "node_path"),
    [
        pytest.param("missing", "body.data", id="missing_body_data"),
        pytest.param("extra", "body.data", id="extra_body_data"),
        pytest.param("missing", "body.data.upload", id="missing_under_body_data"),
        pytest.param("extra", "body.data.upload", id="extra_under_body_data"),
    ],
)
def test_load_deviations_p15_sanctions_body_data(
    kind: str,
    node_path: str,
    tmp_path: Path,
) -> None:
    """missing/extra dla body.data i body.data.<…> z p. 15 w pliku sankcjonowanym → przyjęte."""
    entry = {
        "file": SANCTIONED_FILE,
        "path": node_path,
        "kind": kind,
        "reason": "x",
        "contract": P15_CONTRACT,
    }
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    assert load_deviations(path) == [Deviation(SANCTIONED_FILE, node_path, kind, "x", P15_CONTRACT)]


@pytest.mark.parametrize(
    ("kind", "node_path"),
    [
        pytest.param("value", "body.code", id="value_on_code"),
        pytest.param("missing", "body.data", id="missing_body_data"),
        pytest.param("extra", "body.data.upload", id="extra_under_body_data"),
    ],
)
def test_load_deviations_p15_outside_sanctioned_file(
    kind: str, node_path: str, tmp_path: Path
) -> None:
    """contract K11 §10d p. 15 poza plikiem sankcjonowanym → ValueError z tą nazwą (C5)."""
    entry = {
        "file": "datasets/errors_access--12.json",
        "path": node_path,
        "kind": kind,
        "reason": "x",
        "contract": P15_CONTRACT,
    }
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_deviations(path)
    message = str(exc.value)
    assert P15_CONTRACT in message
    assert entry["file"] in message
    assert entry["path"] in message


def test_load_deviations_value_on_code_without_contract(tmp_path: Path) -> None:
    """kind: value dla body.code bez p. 15 → ValueError jak dotąd (C0 p. 4)."""
    entry = {
        "file": SANCTIONED_FILE,
        "path": "body.code",
        "kind": "value",
        "reason": "x",
    }
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump([entry]), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_deviations(path)
    message = str(exc.value)
    assert SANCTIONED_FILE in message
    assert "body.code" in message


def test_unmatched_all_covered() -> None:
    """Dopasowana odchyłka (po krotce file/path/kind) → pusty raport (K11 §5 p. 5)."""
    diff = Diff(FILE, "body.data.0.content", "value", "a", "b")
    deviation = Deviation(FILE, "body.data.0.content", "value", "chunker WD tnie inaczej")
    assert unmatched([diff], [deviation]) == []


def test_unmatched_reports_diff_without_deviation() -> None:
    """Diff bez odchyłki → linia DIFF w kolejności diffs (K11 §5 p. 5)."""
    diff = Diff(FILE, "body.code", "value", 1, 0)
    assert unmatched([diff], []) == [f"DIFF {FILE} body.code value golden=1 actual=0"]


def test_unmatched_reports_dead_deviation() -> None:
    """Odchyłka bez Diffa (martwa) → linia DEAD (K11 §5 p. 5)."""
    deviation = Deviation(FILE, "body.code", "value", "martwa odchyłka")
    assert unmatched([], [deviation]) == [f"DEAD {FILE} body.code value"]


def test_unmatched_diffs_first_then_dead() -> None:
    """Kolejność raportu: najpierw wszystkie DIFF, potem DEAD (T4-harness p. 5)."""
    matched = Deviation(FILE, "body.p", "value", "r")
    dead = Deviation("other/y--02.json", "body.q", "type", "r")
    covered = Diff(FILE, "body.p", "value", 1, 2)
    uncovered = Diff(FILE, "body.z", "missing", 1, None)
    assert unmatched([covered, uncovered], [matched, dead]) == [
        f"DIFF {FILE} body.z missing golden=1 actual=None",
        "DEAD other/y--02.json body.q type",
    ]
