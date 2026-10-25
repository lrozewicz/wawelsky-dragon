"""Testy jednostkowe wdeval.dataset — port z bety plus pola source/language i file_sha256."""

import json
from pathlib import Path

import pytest

from wdeval.dataset import (
    GROUPS,
    LANGUAGES,
    SOURCES,
    DatasetError,
    EvalItem,
    Source,
    file_sha256,
    load_dataset,
    validate_schema,
)

BETA_DATASET = Path(__file__).resolve().parents[3] / "wdeval" / "data" / "beta" / "dataset.jsonl"
BETA_ITEM_COUNT = 29
_EXPECTED_GROUPS = frozenset(
    {
        "tables-full",
        "tables-xlsx",
        "scan-synth",
        "infographic",
        "narrative",
        "slides",
        "multihop",
        "unanswerable",
    }
)


def _source(**overrides) -> Source:
    defaults = dict(
        file="doc.pdf",
        locator={"page": 1},
        fragment="frag-1",
        quote="an exact quote",
        derived_from=None,
    )
    defaults.update(overrides)
    return Source(**defaults)


def _answerable_item(**overrides) -> EvalItem:
    defaults = dict(
        id="q1",
        group="narrative",
        question="What is X?",
        answerable=True,
        expected_answer="X is Y",
        expected_answer_alt=[],
        sources=[_source()],
        notes="",
    )
    defaults.update(overrides)
    return EvalItem(**defaults)


def _unanswerable_item(**overrides) -> EvalItem:
    defaults = dict(
        id="q2",
        group="unanswerable",
        question="What is Z?",
        answerable=False,
        expected_answer=None,
        expected_answer_alt=[],
        sources=[],
        notes="",
    )
    defaults.update(overrides)
    return EvalItem(**defaults)


def _codex_gold_item(**overrides) -> EvalItem:
    defaults = dict(
        id="cg-1",
        group="codex-gold",
        question="What is X?",
        answerable=True,
        expected_answer="X is Y",
        expected_answer_alt=[],
        sources=[
            _source(locator={"text": "s. 2"}, quote=""),
        ],
        notes="",
        source="codex-gold",
        language="en",
    )
    defaults.update(overrides)
    return EvalItem(**defaults)


# --- stale ----------------------------------------------------------------


def test_constants_match_contract():
    assert GROUPS == _EXPECTED_GROUPS
    assert SOURCES == ("beta", "codex-gold", "poquad")
    assert LANGUAGES == ("pl", "en")


# --- poprawne ksztalty -----------------------------------------------------


def test_valid_locator_page_shape_ok():
    item = _answerable_item(sources=[_source(locator={"page": 1})])
    assert validate_schema([item]) == []


def test_valid_locator_sheet_cell_shape_ok():
    item = _answerable_item(sources=[_source(locator={"sheet": "Sheet1", "cell": "B2"})])
    assert validate_schema([item]) == []


def test_valid_locator_slide_shape_ok():
    item = _answerable_item(sources=[_source(locator={"slide": 3})])
    assert validate_schema([item]) == []


def test_valid_unanswerable_item_ok():
    item = _unanswerable_item()
    assert validate_schema([item]) == []


def test_valid_derived_from_page_only():
    item = _answerable_item(sources=[_source(derived_from="doc.pdf#page=67")])
    assert validate_schema([item]) == []


def test_valid_derived_from_page_and_src_image():
    item = _answerable_item(sources=[_source(derived_from="doc.pdf#page=67&src=image")])
    assert validate_schema([item]) == []


# --- 13 naruszen (beta) ----------------------------------------------------


def test_violation_01_id_empty():
    item = _answerable_item(id="")
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "id pusty" in errors[0]


def test_violation_02_id_duplicated():
    a = _answerable_item(id="dup")
    b = _answerable_item(id="dup")
    errors = validate_schema([a, b])
    assert len(errors) == 1
    assert "dup" in errors[0]
    assert "zduplikowany" in errors[0]


def test_violation_03_group_invalid():
    item = _answerable_item(id="q3", group="bogus-group")
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q3" in errors[0]


def test_violation_04_question_empty():
    item = _answerable_item(id="q4", question="")
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q4" in errors[0]


def test_violation_05_answerable_true_expected_answer_missing():
    item = _answerable_item(id="q5", expected_answer=None)
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q5" in errors[0]


def test_violation_06_answerable_true_sources_empty():
    item = _answerable_item(id="q6", sources=[])
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q6" in errors[0]


def test_violation_07_answerable_false_expected_answer_set():
    item = _unanswerable_item(id="q7", expected_answer="should be none")
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q7" in errors[0]


def test_violation_08_answerable_false_sources_nonempty():
    item = _unanswerable_item(id="q8", sources=[_source()])
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q8" in errors[0]


def test_violation_09_source_file_empty():
    item = _answerable_item(id="q9", sources=[_source(file="")])
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q9" in errors[0]


def test_violation_10_source_fragment_empty():
    item = _answerable_item(id="q10", sources=[_source(fragment="")])
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q10" in errors[0]


def test_violation_11_source_quote_empty():
    item = _answerable_item(id="q11", sources=[_source(quote="")])
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q11" in errors[0]


def test_violation_12_source_locator_bad_shape():
    item = _answerable_item(id="q12", sources=[_source(locator={"page": 1, "extra": "x"})])
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q12" in errors[0]


def test_violation_13_source_derived_from_bad_format():
    item = _answerable_item(id="q13", sources=[_source(derived_from="doc.pdf#page=abc")])
    errors = validate_schema([item])
    assert len(errors) == 1
    assert "q13" in errors[0]


# --- source/language (nowe w WD) -------------------------------------------


def test_non_beta_item_skips_quote_locator_derived_from_checks():
    assert validate_schema([_codex_gold_item()]) == []


def test_beta_item_validates_quote_and_locator():
    item = _codex_gold_item(group="narrative", source="beta", language="pl")
    errors = validate_schema([item])
    assert errors == [
        "cg-1: Source.quote pusty",
        "cg-1: Source.locator niepoprawny ksztalt: {'text': 's. 2'}",
    ]


def test_source_outside_allowed():
    item = _answerable_item(id="x", source="inne")
    assert validate_schema([item]) == ["x: source 'inne' spoza dozwolonego zbioru"]


def test_language_outside_allowed():
    item = _answerable_item(id="x", language="de")
    assert validate_schema([item]) == ["x: language 'de' spoza dozwolonego zbioru"]


def test_codex_gold_group_allowed():
    item = _unanswerable_item(id="cg-2", group="codex-gold")
    assert validate_schema([item]) == []


def test_poquad_group_allowed():
    item = _unanswerable_item(id="pq-1", group="poquad", source="poquad")
    assert validate_schema([item]) == []


# --- kontrola typow przy bezposredniej budowie obiektow --------------------


def test_validate_schema_type_checks():
    cases = [
        (_answerable_item(id="a", sources=[_source(file=5)]), "Source.file nie jest stringiem"),
        (
            _answerable_item(id="b", sources=[_source(fragment=5)]),
            "Source.fragment nie jest stringiem",
        ),
        (_answerable_item(id="c", sources=[_source(quote=5)]), "Source.quote nie jest stringiem"),
        (
            _answerable_item(id="d", sources=[_source(derived_from=5)]),
            "Source.derived_from niepoprawny format",
        ),
        (
            _answerable_item(id="h", sources=[_source(derived_from="")]),
            "Source.derived_from niepoprawny format",
        ),
        (
            _answerable_item(id="i", sources=[_source(locator=None)]),
            "Source.locator niepoprawny ksztalt",
        ),
        (_answerable_item(id="e", notes=5), "notes musi byc stringiem"),
        (
            _answerable_item(id="f", expected_answer=5),
            "expected_answer musi byc stringiem albo None",
        ),
        (
            _answerable_item(id="g", expected_answer_alt=["", 5]),
            "expected_answer_alt musi zawierac wylacznie niepuste stringi",
        ),
    ]
    for item, message in cases:
        errors = validate_schema([item])
        assert any(message in e for e in errors), (item.id, errors)


# --- load_dataset ------------------------------------------------------


def test_load_dataset_valid_jsonl(tmp_path):
    path = tmp_path / "dataset.jsonl"
    lines = [
        "# comment line, should be skipped",
        json.dumps(
            {
                "id": "a1",
                "group": "narrative",
                "question": "What?",
                "answerable": True,
                "expected_answer": "Answer",
                "sources": [
                    {
                        "file": "doc.pdf",
                        "locator": {"page": 2},
                        "fragment": "f1",
                        "quote": "q1",
                    }
                ],
            }
        ),
        "",
        json.dumps(
            {
                "id": "a2",
                "group": "unanswerable",
                "question": "What else?",
                "answerable": False,
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    items = load_dataset(path)

    assert [item.id for item in items] == ["a1", "a2"]
    assert items[0].id == "a1"
    assert items[0].sources[0].file == "doc.pdf"
    assert items[0].sources[0].derived_from is None
    assert items[1].id == "a2"
    assert items[1].expected_answer is None
    assert items[1].sources == []
    assert items[1].expected_answer_alt == []
    assert items[1].notes == ""


def test_load_dataset_source_language_keys(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "x",
                "group": "poquad",
                "question": "q",
                "answerable": False,
                "source": "poquad",
                "language": "pl",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    items = load_dataset(path)

    assert items == [
        EvalItem(
            id="x",
            group="poquad",
            question="q",
            answerable=False,
            expected_answer=None,
            source="poquad",
            language="pl",
        )
    ]
    assert validate_schema(items) == []


def test_load_dataset_source_must_be_string(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(
        json.dumps(
            {"id": "x", "group": "poquad", "question": "q", "answerable": False, "source": 5}
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DatasetError) as exc_info:
        load_dataset(path)
    assert "pole 'source' musi byc stringiem" in str(exc_info.value)


def test_load_dataset_language_must_be_string(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(
        json.dumps(
            {"id": "x", "group": "poquad", "question": "q", "answerable": False, "language": 5}
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DatasetError) as exc_info:
        load_dataset(path)
    assert "pole 'language' musi byc stringiem" in str(exc_info.value)


def test_load_dataset_rejects_non_object_line(tmp_path):
    path = tmp_path / "list.jsonl"
    path.write_text("[1, 2]\n", encoding="utf-8")

    with pytest.raises(DatasetError) as exc_info:
        load_dataset(path)
    assert "oczekiwano obiektu JSON" in str(exc_info.value)


def test_load_dataset_rejects_bad_required_field_types(tmp_path):
    bad_lines = [
        {"id": 5, "group": "narrative", "question": "q", "answerable": True},
        {"id": "a", "group": 5, "question": "q", "answerable": True},
        {"id": "a", "group": "narrative", "question": 5, "answerable": True},
        {"id": "a", "group": "narrative", "question": "q", "answerable": "yes"},
    ]
    for index, line in enumerate(bad_lines, start=1):
        path = tmp_path / f"bad-{index}.jsonl"
        path.write_text(json.dumps(line) + "\n", encoding="utf-8")
        with pytest.raises(DatasetError) as exc_info:
            load_dataset(path)
        assert "musi byc" in str(exc_info.value)


def test_load_dataset_rejects_sources_not_list(tmp_path):
    path = tmp_path / "bad-sources.jsonl"
    line = {"id": "a", "group": "narrative", "question": "q", "answerable": True, "sources": "x"}
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    with pytest.raises(DatasetError) as exc_info:
        load_dataset(path)
    assert "pole 'sources' musi byc lista" in str(exc_info.value)


def test_load_dataset_rejects_source_element_not_object(tmp_path):
    path = tmp_path / "bad-source-element.jsonl"
    line = {"id": "a", "group": "narrative", "question": "q", "answerable": True, "sources": ["x"]}
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    with pytest.raises(DatasetError) as exc_info:
        load_dataset(path)
    assert "element 'sources' nie jest obiektem" in str(exc_info.value)


def test_load_dataset_rejects_expected_answer_alt_not_list(tmp_path):
    path = tmp_path / "bad-alt.jsonl"
    line = {
        "id": "a",
        "group": "narrative",
        "question": "q",
        "answerable": True,
        "expected_answer": "ok",
        "expected_answer_alt": "x",
    }
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    with pytest.raises(DatasetError) as exc_info:
        load_dataset(path)
    assert "pole 'expected_answer_alt' musi byc lista" in str(exc_info.value)


def test_load_dataset_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.jsonl"
    with pytest.raises(DatasetError):
        load_dataset(missing)


def test_load_dataset_invalid_json_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "a1", "group": "narrative"\n', encoding="utf-8")

    with pytest.raises(DatasetError) as exc_info:
        load_dataset(path)
    assert "1" in str(exc_info.value)


def test_load_dataset_missing_required_field(tmp_path):
    path = tmp_path / "missing-group.jsonl"
    path.write_text(
        json.dumps({"id": "a1", "question": "Q?", "answerable": True}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DatasetError) as exc_info:
        load_dataset(path)
    assert "group" in str(exc_info.value)


# --- dane bety -------------------------------------------------------------


def test_beta_dataset_loads_and_validates():
    items = load_dataset(BETA_DATASET)

    assert len(items) == BETA_ITEM_COUNT
    assert {item.group for item in items} == set(GROUPS)
    assert all(item.source == "beta" for item in items)
    assert all(item.language == "pl" for item in items)
    assert validate_schema(items) == []


# --- file_sha256 -----------------------------------------------------------


def test_file_sha256_known_digest(tmp_path):
    target = tmp_path / "a"
    target.write_bytes(b"abc")
    assert file_sha256(target) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
