"""Testy raportu i artefaktu JSON (kontrakt C6) — port komorek tabeli z bety
(test_eval_report.py) plus nowe ksztalty JSON z kontraktu."""

from __future__ import annotations

from pathlib import Path

from wdeval.aggregate import Aggregate, ItemResult
from wdeval.judge import Verdict
from wdeval.report import (
    INTERPRETATION_CEILING,
    aggregate_to_json,
    build_artifact,
    item_to_json,
    render_report,
    write_artifact,
)


def make_aggregate(**overrides) -> Aggregate:
    defaults = dict(
        scope="all",
        key="all",
        arm="fast",
        n=4,
        n_answerable=4,
        answer_correct=3,
        fragment_recall={1: 1, 3: 2},
        doc_recall={1: 1, 3: 2},
        retrieval_miss=0,
        parse_miss=0,
        grounded_true=3,
        grounded_n=4,
        empty_ok_true=0,
        empty_ok_n=0,
        citation_ok_true=2,
        citation_ok_n=4,
    )
    defaults.update(overrides)
    return Aggregate(**defaults)


def make_result(**overrides) -> ItemResult:
    defaults = dict(
        item_id="q1",
        source="beta",
        language="pl",
        group="narrative",
        arm="fast",
        answer="737",
        answer_correct=True,
        fragment_recall={1: True, 3: False},
        doc_recall={1: True, 3: True},
        miss_kind="hit",
        verdicts={},
        empty_path=None,
        retrieved_chunks=["doc.pdf#0", "doc.pdf#1"],
    )
    defaults.update(overrides)
    return ItemResult(**defaults)


HEADER = {
    "run_id": "r1",
    "judge_model": "gpt-judge",
    "answering_model": "gpt-answer",
    "dataset": "dataset.jsonl",
}


def _table_rows(out: str) -> list[list[str]]:
    """Zwraca komorki wierszy danych (po linii separatora) pierwszej tabeli."""
    lines = out.splitlines()
    separator_idx = next(i for i, ln in enumerate(lines) if set(ln) <= {"-", "+"} and "-+-" in ln)
    rows = []
    for ln in lines[separator_idx + 1 :]:
        if ln.startswith("=====") or ln == "":
            break
        rows.append([cell.strip() for cell in ln.split("|")])
    return rows


def _table_cols(out: str) -> list[str]:
    """Zwraca nazwy kolumn pierwszej tabeli."""
    header_line = next(ln for ln in out.splitlines() if ln.startswith("klucz"))
    return [c.strip() for c in header_line.split("|")]


def _section_rows(out: str, scope: str) -> list[list[str]]:
    """Zwraca komorki wierszy danych tabeli danej sekcji scope."""
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln == f"===== {scope} =====")
    section = lines[start + 1 :]
    separator_idx = next(i for i, ln in enumerate(section) if set(ln) <= {"-", "+"} and "-+-" in ln)
    rows = []
    for ln in section[separator_idx + 1 :]:
        if ln.startswith("=====") or ln == "":
            break
        rows.append([cell.strip() for cell in ln.split("|")])
    return rows


class TestRenderReport:
    def test_header_lines_sorted_then_empty_line(self):
        out = render_report([make_aggregate()], k_list=[1, 3], header={"b": "2", "a": "1"})
        assert out.startswith("a: 1\nb: 2\n\n===== all =====\n\n")

    def test_sections_in_scope_order_only_present(self):
        aggs = [
            make_aggregate(scope="group", key="narrative"),
            make_aggregate(scope="language", key="pl"),
            make_aggregate(scope="all", key="all"),
            make_aggregate(scope="source", key="beta"),
        ]
        out = render_report(aggs, k_list=[1, 3], header=HEADER)
        markers = [ln for ln in out.splitlines() if ln.startswith("=====")]
        assert markers == [
            "===== all =====",
            "===== source =====",
            "===== language =====",
            "===== group =====",
        ]

    def test_absent_scope_has_no_section(self):
        aggs = [make_aggregate(scope="all", key="all")]
        out = render_report(aggs, k_list=[1, 3], header=HEADER)
        assert out.count("=====") == 2  # noqa: PLR2004 — jeden naglowek sekcji = para "===== ... ====="
        assert "===== source =====" not in out

    def test_table_headers_and_columns(self):
        out = render_report([make_aggregate()], k_list=[1, 3], header=HEADER)
        header_line = next(ln for ln in out.splitlines() if ln.startswith("klucz"))
        cols = [c.strip() for c in header_line.split("|")]
        assert cols == [
            "klucz",
            "ramie",
            "n",
            "n_ans",
            "correct",
            "frag@1",
            "frag@3",
            "doc@1",
            "doc@3",
            "retr-miss",
            "parse-miss",
            "grounded",
            "empty_ok",
            "citation_ok",
        ]

    def test_rows_in_received_order_with_cells(self):
        aggs = [
            make_aggregate(scope="all", key="all", arm="fast"),
            make_aggregate(
                scope="source", key="beta", arm="fast", n=2, n_answerable=2, answer_correct=1
            ),
            make_aggregate(scope="all", key="all", arm="auto", retrieval_miss=1, parse_miss=2),
        ]
        out = render_report(aggs, k_list=[1, 3], header=HEADER)
        # Sekcja "all" dostaje wiersze w kolejnosci otrzymanej (fast przed auto);
        # wiersz source/beta siedzi w swojej sekcji.
        assert _table_rows(out) == [
            [
                "all",
                "fast",
                "4",
                "4",
                "75% (3/4)",
                "25% (1/4)",
                "50% (2/4)",
                "25% (1/4)",
                "50% (2/4)",
                "0",
                "0",
                "75% (3/4)",
                "n/a",
                "50% (2/4)",
            ],
            [
                "all",
                "auto",
                "4",
                "4",
                "75% (3/4)",
                "25% (1/4)",
                "50% (2/4)",
                "25% (1/4)",
                "50% (2/4)",
                "1",
                "2",
                "75% (3/4)",
                "n/a",
                "50% (2/4)",
            ],
        ]
        assert _section_rows(out, "source") == [
            [
                "beta",
                "fast",
                "2",
                "2",
                "50% (1/2)",
                "50% (1/2)",
                "100% (2/2)",
                "50% (1/2)",
                "100% (2/2)",
                "0",
                "0",
                "75% (3/4)",
                "n/a",
                "50% (2/4)",
            ],
        ]

    def test_zero_denominator_gives_na_not_crash(self):
        agg = make_aggregate(
            scope="group",
            key="unanswerable",
            n=3,
            n_answerable=0,
            answer_correct=0,
            fragment_recall={1: 0, 3: 0},
            doc_recall={1: 0, 3: 0},
        )
        out = render_report([agg], k_list=[1, 3], header=HEADER)
        assert "n/a" in out
        assert "ZeroDivisionError" not in out

    def test_missing_k_gives_na_not_fabricated_zero(self):
        # fragment_recall/doc_recall nie maja klucza k=3: kolumna frag@3
        # nie moze udawac pomiaru "0%", ktorego nikt nie policzyl.
        agg = make_aggregate(fragment_recall={1: 1}, doc_recall={1: 1})
        out = render_report([agg], k_list=[1, 3], header=HEADER)
        rows = _table_rows(out)
        cols = _table_cols(out)
        assert rows[0][cols.index("frag@3")] == "n/a"
        assert rows[0][cols.index("doc@3")] == "n/a"

    def test_k_list_controls_columns(self):
        agg = make_aggregate(fragment_recall={1: 1, 3: 2, 6: 3}, doc_recall={1: 1, 3: 2, 6: 3})
        out_full = render_report([agg], k_list=[1, 3, 6], header=HEADER)
        out_one = render_report([agg], k_list=[1], header=HEADER)
        assert "frag@1" in out_full and "frag@3" in out_full and "frag@6" in out_full
        assert "doc@1" in out_full and "doc@3" in out_full and "doc@6" in out_full
        assert "frag@1" in out_one
        assert "frag@3" not in out_one
        assert "frag@6" not in out_one

    def test_ceiling_once_at_end_after_empty_line(self):
        out = render_report([make_aggregate()], k_list=[1, 3], header=HEADER)
        assert out.count(INTERPRETATION_CEILING) == 1
        assert out.endswith("\n\n" + INTERPRETATION_CEILING)

    def test_deterministic_across_calls(self):
        aggs = [make_aggregate(scope="all", key="all"), make_aggregate(scope="source", key="beta")]
        assert render_report(aggs, k_list=[1, 3], header=HEADER) == render_report(
            aggs, k_list=[1, 3], header=HEADER
        )

    def test_header_metadata_present(self):
        out = render_report([make_aggregate()], k_list=[1, 3], header=HEADER)
        assert "r1" in out
        assert "gpt-judge" in out
        assert "gpt-answer" in out
        assert "dataset.jsonl" in out


class TestAggregateToJson:
    def test_shape_without_scope_key_arm_and_text_k_keys(self):
        agg = make_aggregate(
            scope="source",
            key="beta",
            arm="auto",
            n=2,
            n_answerable=2,
            answer_correct=1,
            fragment_recall={1: 2, 3: 1},
            doc_recall={1: 0, 3: 2},
            retrieval_miss=1,
            parse_miss=0,
            grounded_true=1,
            grounded_n=2,
            empty_ok_true=0,
            empty_ok_n=0,
            citation_ok_true=2,
            citation_ok_n=2,
        )
        data = aggregate_to_json(agg)
        assert set(data) == {
            "n",
            "n_answerable",
            "answer_correct",
            "fragment_recall",
            "doc_recall",
            "retrieval_miss",
            "parse_miss",
            "grounded_true",
            "grounded_n",
            "empty_ok_true",
            "empty_ok_n",
            "citation_ok_true",
            "citation_ok_n",
        }
        assert data["n"] == 2  # noqa: PLR2004 — wartosci doslownie z konstruowanego agregatu
        assert data["n_answerable"] == 2  # noqa: PLR2004
        assert data["answer_correct"] == 1
        assert data["fragment_recall"] == {"1": 2, "3": 1}
        assert data["doc_recall"] == {"1": 0, "3": 2}
        assert data["retrieval_miss"] == 1
        assert data["parse_miss"] == 0
        assert data["grounded_true"] == 1
        assert data["grounded_n"] == 2  # noqa: PLR2004
        assert data["citation_ok_true"] == 2  # noqa: PLR2004
        assert data["citation_ok_n"] == 2  # noqa: PLR2004


class TestItemToJson:
    def test_exact_keys(self):
        data = item_to_json(make_result())
        assert set(data) == {
            "item_id",
            "source",
            "language",
            "group",
            "arm",
            "answer",
            "answer_correct",
            "fragment_recall",
            "doc_recall",
            "miss_kind",
            "verdicts",
            "empty_path",
            "retrieved_chunks",
        }

    def test_brief_example_k_keys_and_verdicts(self):
        # Przykład z briefu T1 (doslownie): fragment_recall={1: True, 6: False},
        # verdicts={"grounded": Verdict("grounded", None, "??")} ->
        # "fragment_recall": {"1": true, "6": false},
        # "verdicts": {"grounded": {"value": null, "raw": "??"}}.
        result = make_result(
            fragment_recall={1: True, 6: False},
            verdicts={"grounded": Verdict("grounded", None, "??")},
        )
        data = item_to_json(result)
        assert data["fragment_recall"] == {"1": True, "6": False}
        assert data["verdicts"] == {"grounded": {"value": None, "raw": "??"}}

    def test_verdict_values_preserved(self):
        result = make_result(
            verdicts={
                "grounded": Verdict("grounded", True, "TAK"),
                "empty_ok": Verdict("empty_ok", False, "NIE"),
            }
        )
        data = item_to_json(result)
        assert data["verdicts"] == {
            "grounded": {"value": True, "raw": "TAK"},
            "empty_ok": {"value": False, "raw": "NIE"},
        }


class TestBuildArtifact:
    def test_top_level_keys_and_passthrough(self):
        manifest = {"run_id": "r1"}
        comparisons = [{"arms": ["fast", "auto"], "common_count": 0}]
        results = [make_result(item_id="q1"), make_result(item_id="q2")]
        aggregates = [make_aggregate(scope="all", key="all", arm="fast")]
        artifact = build_artifact(manifest, results, aggregates, comparisons)
        assert set(artifact) == {"manifest", "items", "comparisons", "sections"}
        assert artifact["manifest"] is manifest
        assert artifact["comparisons"] is comparisons
        assert [item["item_id"] for item in artifact["items"]] == ["q1", "q2"]

    def test_sections_nested_scope_key_arm(self):
        agg_all = make_aggregate(scope="all", key="all", arm="fast", n=1)
        agg_beta = make_aggregate(scope="source", key="beta", arm="fast", n=1)
        agg_auto = make_aggregate(scope="all", key="all", arm="auto", n=2)
        artifact = build_artifact({}, [], [agg_all, agg_beta, agg_auto], [])
        assert artifact["sections"] == {
            "all": {
                "all": {
                    "fast": aggregate_to_json(agg_all),
                    "auto": aggregate_to_json(agg_auto),
                }
            },
            "source": {
                "beta": {
                    "fast": aggregate_to_json(agg_beta),
                }
            },
        }

    def test_items_in_results_order(self):
        results = [make_result(item_id="q2"), make_result(item_id="q1")]
        artifact = build_artifact({}, results, [], [])
        assert [item["item_id"] for item in artifact["items"]] == ["q2", "q1"]


class TestWriteArtifact:
    def test_brief_example_sorted_keys_and_trailing_newline(self, tmp_path: Path):
        # Przykład z briefu T1 (doslownie): write_artifact(tmp/"a/b.json",
        # {"z": 1, "a": "ą"}) -> plik istnieje, treść '{\n  "a": "ą",\n  "z": 1\n}\n'.
        path = tmp_path / "a" / "b.json"
        write_artifact(path, {"z": 1, "a": "ą"})
        assert path.exists()
        assert path.read_text(encoding="utf-8") == '{\n  "a": "ą",\n  "z": 1\n}\n'

    def test_creates_missing_parent_directories(self, tmp_path: Path):
        path = tmp_path / "x" / "y" / "z" / "out.json"
        write_artifact(path, {})
        assert path.exists()
