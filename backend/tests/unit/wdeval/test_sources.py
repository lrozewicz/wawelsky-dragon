"""Testy jednostkowe wdeval.sources — adaptery Codex gold i PoQuAD (kontrakt C7)."""

import json
from pathlib import Path
from typing import Any

import pytest

from wdeval.dataset import DatasetError, EvalItem, Source, validate_schema
from wdeval.sources import (
    CODEX_GOLD_RELPATH,
    POQUAD_RELPATH,
    load_codex_gold,
    load_poquad,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "wdeval"
CODEX_DIR = FIXTURES / "codex"
POQUAD_MINI = FIXTURES / "poquad-mini.json"

_GOLD_COUNT = 3  # linie w fixtures/wdeval/codex/metadata/gold_questions.jsonl
_POQUAD_COUNT = 5  # pytania w poquad-mini.json
_MINI_SAMPLE = 2  # rozmiar próby w teście determinizmu


def _write_gold(tmp_path: Path, lines: list[str]) -> Path:
    """Buduje katalog codex z własnym gold_questions.jsonl (dla przypadków błędnych)."""
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    (metadata / "gold_questions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _gold_line(**overrides: Any) -> str:
    defaults: dict[str, Any] = {
        "id": "x-1",
        "document": "documents/pl/md/a.md",
        "language": "pl",
        "question": "Q?",
        "answer": "A.",
        "evidence": "E",
        "locator": "s. 1",
    }
    defaults.update(overrides)
    return json.dumps(defaults, ensure_ascii=False)


def test_load_codex_gold_first_fixture_line() -> None:
    items, docs = load_codex_gold(CODEX_DIR)
    assert len(items) == _GOLD_COUNT
    assert items[0] == EvalItem(
        id="en-x-001",
        group="codex-gold",
        question="Q?",
        answerable=True,
        expected_answer="A.",
        expected_answer_alt=[],
        sources=[
            Source(
                file="x.pdf",
                locator={"text": "page 2"},
                fragment="E text",
                quote="E text",
                derived_from=None,
            )
        ],
        notes="page 2",
        source="codex-gold",
        language="en",
    )
    assert docs["x.pdf"] == CODEX_DIR / "documents/en/pdf/x.pdf"


def test_load_codex_gold_document_map_and_items() -> None:
    items, docs = load_codex_gold(CODEX_DIR)
    assert [item.id for item in items] == ["en-x-001", "pl-y-002", "en-z-003"]
    assert items[1].language == "pl"
    assert docs == {
        "x.pdf": CODEX_DIR / "documents/en/pdf/x.pdf",
        "y.md": CODEX_DIR / "documents/pl/md/y.md",
        "z.md": CODEX_DIR / "documents/en/md/z.md",
    }


def test_load_codex_gold_relpath_points_at_fixture() -> None:
    assert (CODEX_DIR / CODEX_GOLD_RELPATH).exists()


def test_load_codex_gold_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="brak pliku"):
        load_codex_gold(tmp_path)


def test_load_codex_gold_missing_field(tmp_path: Path) -> None:
    data = {
        "id": "x-1",
        "document": "documents/pl/md/a.md",
        "language": "pl",
        "question": "Q?",
        "evidence": "E",
        "locator": "s. 1",
    }
    codex_dir = _write_gold(tmp_path, [json.dumps(data, ensure_ascii=False)])
    with pytest.raises(DatasetError, match=r"linia 1: brak pola 'answer'"):
        load_codex_gold(codex_dir)


def test_load_codex_gold_bad_language(tmp_path: Path) -> None:
    codex_dir = _write_gold(tmp_path, [_gold_line(language="fr")])
    with pytest.raises(DatasetError, match=r"linia 1: language 'fr' spoza dozwolonego zbioru"):
        load_codex_gold(codex_dir)


def test_load_codex_gold_duplicate_basename(tmp_path: Path) -> None:
    codex_dir = _write_gold(
        tmp_path,
        [
            _gold_line(id="a", document="documents/en/a/x.pdf"),
            _gold_line(id="b", document="documents/pl/b/x.pdf"),
        ],
    )
    with pytest.raises(DatasetError, match=r"zduplikowana nazwa dokumentu 'x\.pdf'"):
        load_codex_gold(codex_dir)


def test_load_codex_gold_skips_empty_lines(tmp_path: Path) -> None:
    codex_dir = _write_gold(
        tmp_path,
        [_gold_line(id="a"), "", "   ", _gold_line(id="b", document="documents/pl/md/b.md")],
    )
    items, docs = load_codex_gold(codex_dir)
    assert [item.id for item in items] == ["a", "b"]
    assert sorted(docs) == ["a.md", "b.md"]


def test_load_codex_gold_invalid_json_line(tmp_path: Path) -> None:
    """Linia z niepoprawnym JSON-em → DatasetError z numerem linii, nie JSONDecodeError."""
    codex_dir = _write_gold(tmp_path, [_gold_line(id="a"), "{zly json"])
    with pytest.raises(DatasetError, match=r"linia 2: niepoprawny JSON"):
        load_codex_gold(codex_dir)


def test_codex_and_poquad_items_pass_validate_schema() -> None:
    gold_items, _ = load_codex_gold(CODEX_DIR)
    poquad_items, _ = load_poquad(POQUAD_MINI, n=100, seed=1)
    assert validate_schema(gold_items + poquad_items) == []


def test_load_poquad_all_five_questions() -> None:
    items, docs = load_poquad(POQUAD_MINI, n=100, seed=1)
    assert len(items) == _POQUAD_COUNT
    assert [item.id for item in items] == [
        "poquad-0000-00-00",
        "poquad-0000-00-01",
        "poquad-0000-01-00",
        "poquad-0001-00-00",
        "poquad-0001-00-01",
    ]
    assert [doc.name for doc in docs] == ["poquad-0000.txt", "poquad-0001.txt"]
    assert (
        docs[0].data
        == (
            "Wawel\n\nWawel to wzgórze w Krakowie.\n\n"
            "Zamek Królewski na Wawelu był rezydencją królów Polski."
        ).encode()
    )


def test_load_poquad_impossible_question() -> None:
    items, _ = load_poquad(POQUAD_MINI, n=100, seed=1)
    impossible = items[2]
    assert impossible.id == "poquad-0000-01-00"
    assert impossible.answerable is False
    assert impossible.expected_answer is None
    assert impossible.sources == []
    assert impossible.expected_answer_alt == []
    assert impossible.group == "poquad"
    assert impossible.source == "poquad"
    assert impossible.language == "pl"


def test_load_poquad_expected_answer_and_alt() -> None:
    items, _ = load_poquad(POQUAD_MINI, n=100, seed=1)
    item = items[3]
    assert item.expected_answer == "w jaskini pod wzgórzem"
    assert item.expected_answer_alt == ["w jaskini", "pod wzgórzem"]
    assert item.sources == [
        Source(
            file="poquad-0001.txt",
            locator={"paragraph": 0},
            fragment="w jaskini",
            quote="",
            derived_from=None,
        )
    ]


def test_load_poquad_single_answer_without_alt() -> None:
    items, _ = load_poquad(POQUAD_MINI, n=100, seed=1)
    item = items[4]
    assert item.expected_answer == "Szewczyk Dratewka"
    assert item.expected_answer_alt == []


def test_load_poquad_deterministic_sampling() -> None:
    first_items, first_docs = load_poquad(POQUAD_MINI, n=2, seed=7)
    second_items, second_docs = load_poquad(POQUAD_MINI, n=2, seed=7)
    assert first_items == second_items
    assert first_docs == second_docs
    assert len(first_items) == _MINI_SAMPLE
    ids = [item.id for item in first_items]
    assert ids == sorted(ids)


def test_load_poquad_non_positive_n(tmp_path: Path) -> None:
    assert load_poquad(POQUAD_MINI, n=0, seed=1) == ([], [])


def test_load_poquad_sorted_by_id_lexicographically(tmp_path: Path) -> None:
    """Ponad 99 paragrafów: kolejność po id (leksykograficzna) ≠ kolejność po krotce."""
    paragraph_count = 101  # > 99, żeby format :02d dał 3 cyfry i rozmył kolejność krotek
    paragraphs = [
        {
            "context": f"Zdanie numer {i} o Wawelu.",
            "qas": [
                {
                    "question": f"Pytanie numer {i}?",
                    "answers": [
                        {
                            "text": f"Odpowiedź {i}",
                            "answer_start": 0,
                            "answer_end": 3,
                            "generative_answer": f"Odpowiedź {i}",
                        }
                    ],
                    "is_impossible": False,
                }
            ],
        }
        for i in range(paragraph_count)
    ]
    payload = {
        "version": "1.0",
        "data": [
            {"id": "a0", "title": "Wawel", "summary": "", "url": "", "paragraphs": paragraphs}
        ],
    }
    path = tmp_path / "poquad-many.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    items, _ = load_poquad(path, n=paragraph_count, seed=1)
    ids = [item.id for item in items]
    assert len(ids) == paragraph_count
    assert ids == sorted(ids)


def test_load_poquad_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="brak pliku"):
        load_poquad(tmp_path / "brak.json", n=5, seed=1)


def test_poquad_relpath_constant() -> None:
    assert POQUAD_RELPATH == "benchmarks/poquad/poquad-dev.json"
