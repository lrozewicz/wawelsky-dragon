"""Testy agregatow ewaluacji (kontrakt C4) — port testow Aggregate/merge z bety
(test_eval_metrics.py) plus testy build_aggregate/aggregate_results przeniesione
z sensu asercji test_eval_run.py bety.
"""

from __future__ import annotations

import pytest

from wdeval.aggregate import (
    Aggregate,
    CrossScopeError,
    ItemResult,
    aggregate_results,
    build_aggregate,
    merge,
)
from wdeval.dataset import EvalItem, Source
from wdeval.judge import Verdict


def make_item(**overrides) -> EvalItem:
    defaults = dict(
        id="q1",
        group="narrative",
        question="pytanie testowe",
        answerable=True,
        expected_answer="737",
        expected_answer_alt=[],
        sources=[make_source()],
        notes="",
    )
    defaults.update(overrides)
    return EvalItem(**defaults)


def make_source(**overrides) -> Source:
    defaults = dict(
        file="doc.pdf",
        locator={"page": 1},
        fragment="737",
        quote="737 pracownikow",
        derived_from=None,
    )
    defaults.update(overrides)
    return Source(**defaults)


def make_result(**overrides) -> ItemResult:
    defaults = dict(
        item_id="q1",
        source="beta",
        language="pl",
        group="narrative",
        arm="fast",
        answer="737",
        answer_correct=True,
        fragment_recall={1: True, 3: True, 6: True},
        doc_recall={1: True, 3: True, 6: True},
        miss_kind="hit",
        verdicts={},
        empty_path=None,
        retrieved_chunks=["doc.pdf#0"],
    )
    defaults.update(overrides)
    return ItemResult(**defaults)


def make_aggregate(**overrides) -> Aggregate:
    defaults = dict(
        scope="all",
        key="all",
        arm="fast",
        n=1,
        n_answerable=1,
        answer_correct=0,
        fragment_recall={1: 0, 3: 0},
        doc_recall={1: 0, 3: 0},
        retrieval_miss=0,
        parse_miss=0,
        grounded_true=0,
        grounded_n=0,
        empty_ok_true=0,
        empty_ok_n=0,
        citation_ok_true=0,
        citation_ok_n=0,
    )
    defaults.update(overrides)
    return Aggregate(**defaults)


def entry(item_id: str, **overrides) -> tuple[EvalItem, ItemResult]:
    return make_item(id=item_id), make_result(item_id=item_id, **overrides)


class TestBuildAggregate:
    def test_counts_n_and_n_answerable(self):
        results = [
            entry("q1"),
            entry("q2"),
            (
                make_item(id="q3", answerable=False, expected_answer=None, sources=[]),
                make_result(item_id="q3"),
            ),
        ]
        agg = build_aggregate("all", "all", "fast", results, [1, 3, 6])
        assert agg.n == 3  # noqa: PLR2004 — liczniki doslowne z konstruowanego zestawu
        assert agg.n_answerable == 2  # noqa: PLR2004

    def test_answer_correct_counts_only_answerable(self):
        # Sens asercji test_eval_run.py bety: pozycja answerable=false nie
        # wplywa na answer_correct; mianownik (n_answerable) to 0.
        results = [
            (
                make_item(id="q4", answerable=False, expected_answer=None, sources=[]),
                make_result(item_id="q4", answer=False, answer_correct=False, miss_kind=None),
            ),
        ]
        agg = build_aggregate("all", "all", "fast", results, [1, 3])
        assert agg.n == 1
        assert agg.n_answerable == 0
        assert agg.answer_correct == 0

    def test_missing_k_counts_as_false(self):
        # "brak klucza k w wyniku = False" (brief T1)
        results = [entry("q1", fragment_recall={1: True}, doc_recall={})]
        agg = build_aggregate("all", "all", "fast", results, [1, 3, 6])
        assert agg.fragment_recall == {1: 1, 3: 0, 6: 0}
        assert agg.doc_recall == {1: 0, 3: 0, 6: 0}

    def test_recall_and_correct_summed_over_answerable(self):
        results = [
            entry(
                "q1",
                answer_correct=True,
                fragment_recall={1: True, 3: False},
                doc_recall={1: True, 3: True},
            ),
            entry(
                "q2",
                answer_correct=False,
                fragment_recall={1: False, 3: False},
                doc_recall={1: False, 3: True},
            ),
        ]
        agg = build_aggregate("all", "all", "fast", results, [1, 3])
        assert agg.answer_correct == 1
        assert agg.fragment_recall == {1: 1, 3: 0}
        assert agg.doc_recall == {1: 1, 3: 2}

    def test_miss_kind_counts(self):
        results = [
            entry("q1", miss_kind="retrieval-miss"),
            entry("q2", miss_kind="parse-miss"),
            entry("q3", miss_kind="hit"),
            (
                make_item(id="q4", answerable=False, expected_answer=None, sources=[]),
                make_result(item_id="q4", miss_kind=None),
            ),
        ]
        agg = build_aggregate("all", "all", "fast", results, [1])
        assert agg.retrieval_miss == 1
        assert agg.parse_miss == 1

    def test_verdicts_counted_only_when_value_not_none(self):
        results = [
            entry(
                "q1",
                verdicts={
                    "grounded": Verdict("grounded", True, "TAK"),
                    "empty_ok": Verdict("empty_ok", None, "?"),
                },
            ),
            entry("q2", verdicts={"grounded": Verdict("grounded", False, "NIE")}),
            entry("q3", verdicts={}),  # brak klucza rodzaju -> nie liczy sie
        ]
        agg = build_aggregate("all", "all", "fast", results, [1])
        assert agg.grounded_true == 1
        assert agg.grounded_n == 2  # noqa: PLR2004 — 2 z 3 wynikow ma rozstrzygniety grounded
        assert agg.empty_ok_true == 0
        assert agg.empty_ok_n == 0
        assert agg.citation_ok_true == 0
        assert agg.citation_ok_n == 0

    def test_verdicts_counted_over_all_entries_including_unanswerable(self):
        # Werdykty liczone po wszystkich wynikach (jak w becie), nie tylko
        # answerable — pozycja bez zrodel ma pusty mianownik metryk, ale jej
        # empty_ok wchodzi do licznikow werdyktow.
        results = [
            (
                make_item(id="q4", answerable=False, expected_answer=None, sources=[]),
                make_result(
                    item_id="q4",
                    answer_correct=False,
                    miss_kind=None,
                    verdicts={"empty_ok": Verdict("empty_ok", True, "TAK")},
                ),
            ),
        ]
        agg = build_aggregate("all", "all", "fast", results, [1])
        assert agg.n_answerable == 0
        assert agg.empty_ok_true == 1
        assert agg.empty_ok_n == 1

    def test_scope_key_arm_stored(self):
        agg = build_aggregate("source", "beta", "auto", [entry("q1")], [1])
        assert agg.scope == "source"
        assert agg.key == "beta"
        assert agg.arm == "auto"


class TestMerge:
    def test_sums_counters_including_per_k_dicts(self):
        a = make_aggregate(
            n=2,
            n_answerable=2,
            answer_correct=1,
            fragment_recall={1: 1, 3: 2},
            doc_recall={1: 0, 3: 1},
            retrieval_miss=1,
            parse_miss=0,
        )
        b = make_aggregate(
            n=3,
            n_answerable=3,
            answer_correct=2,
            fragment_recall={1: 2, 3: 1},
            doc_recall={1: 1, 3: 2},
            retrieval_miss=0,
            parse_miss=1,
        )
        result = merge(a, b)
        assert result.n == 5  # noqa: PLR2004 — sumy pol z dwoch agregatow (2+3)
        assert result.n_answerable == 5  # noqa: PLR2004
        assert result.answer_correct == 3  # noqa: PLR2004 — 1+2
        assert result.fragment_recall == {1: 3, 3: 3}
        assert result.doc_recall == {1: 1, 3: 3}
        assert result.retrieval_miss == 1
        assert result.parse_miss == 1
        assert result.scope == "all"
        assert result.key == "all"
        assert result.arm == "fast"

    def test_different_scope_raises_cross_scope_error(self):
        # Przykład z briefu T1 (doslownie): source/beta vs source/poquad.
        a = make_aggregate(scope="source", key="beta")
        b = make_aggregate(scope="source", key="poquad")
        with pytest.raises(CrossScopeError):
            merge(a, b)

    def test_different_key_same_scope_raises_cross_scope_error(self):
        a = make_aggregate(scope="all", key="all")
        b = make_aggregate(scope="group", key="narrative")
        with pytest.raises(CrossScopeError):
            merge(a, b)

    def test_different_arm_raises_value_error(self):
        a = make_aggregate(arm="fast")
        b = make_aggregate(arm="vision")
        with pytest.raises(ValueError):
            merge(a, b)

    def test_different_k_sets_in_fragment_recall_raises_value_error(self):
        a = make_aggregate(fragment_recall={1: 0, 3: 0})
        b = make_aggregate(fragment_recall={1: 0, 5: 0})
        with pytest.raises(ValueError):
            merge(a, b)

    def test_different_k_sets_in_doc_recall_raises_value_error(self):
        a = make_aggregate(doc_recall={1: 0, 3: 0})
        b = make_aggregate(doc_recall={1: 0, 5: 0})
        with pytest.raises(ValueError):
            merge(a, b)

    def test_does_not_mutate_arguments(self):
        # frozen=True blokuje rebindowanie pol Aggregate, ale NIE chroni
        # dictow przed mutacja in-place - merge musi budowac nowe dicty.
        a = make_aggregate(fragment_recall={1: 1, 3: 2}, doc_recall={1: 1, 3: 1})
        b = make_aggregate(fragment_recall={1: 2, 3: 1}, doc_recall={1: 0, 3: 1})
        a_fragment_before = dict(a.fragment_recall)
        b_fragment_before = dict(b.fragment_recall)
        merge(a, b)
        assert a.fragment_recall == a_fragment_before
        assert b.fragment_recall == b_fragment_before


class TestAggregateResults:
    def test_key_order_per_contract(self):
        # Przykład z briefu T1 (doslownie): 3 wyniki ramienia fast —
        # beta/pl/narrative, codex-gold/en/codex-gold, poquad/pl/poquad —
        # klucze w kolejnosci: (all,all), (source,beta), (source,codex-gold),
        # (source,poquad), (language,pl), (language,en), (group,narrative).
        results = [
            entry("q1", source="beta", language="pl", group="narrative"),
            entry("q2", source="codex-gold", language="en", group="codex-gold"),
            entry("q3", source="poquad", language="pl", group="poquad"),
        ]
        aggregates = aggregate_results(results, [1, 3])
        assert [(a.scope, a.key) for a in aggregates] == [
            ("all", "all"),
            ("source", "beta"),
            ("source", "codex-gold"),
            ("source", "poquad"),
            ("language", "pl"),
            ("language", "en"),
            ("group", "narrative"),
        ]
        assert all(a.arm == "fast" for a in aggregates)

    def test_arms_in_first_appearance_order(self):
        results = [
            entry("q1", arm="auto"),
            entry("q2", arm="fast"),
            entry("q3", arm="auto"),
        ]
        aggregates = aggregate_results(results, [1])
        assert [(a.scope, a.key, a.arm) for a in aggregates if a.scope == "all"] == [
            ("all", "all", "auto"),
            ("all", "all", "fast"),
        ]

    def test_positions_filtered_by_arm(self):
        results = [
            entry("q1", arm="fast"),
            entry("q2", arm="fast"),
            entry("q3", arm="auto"),
        ]
        aggregates = aggregate_results(results, [1])
        by_key = {(a.scope, a.key, a.arm): a for a in aggregates}
        assert by_key[("all", "all", "fast")].n == 2  # noqa: PLR2004 — dwa wyniki na ramie fast
        assert by_key[("all", "all", "auto")].n == 1

    def test_group_only_for_beta_source_and_sorted(self):
        results = [
            entry("q1", source="beta", group="narrative"),
            entry("q2", source="beta", group="multihop"),
            entry("q3", source="codex-gold", group="codex-gold"),
            entry("q4", source="poquad", group="poquad"),
        ]
        aggregates = aggregate_results(results, [1])
        group_keys = [(a.scope, a.key) for a in aggregates if a.scope == "group"]
        assert group_keys == [("group", "multihop"), ("group", "narrative")]

    def test_absent_sources_and_languages_skipped_within_arm(self):
        results = [entry("q1", source="beta", language="pl", group="narrative")]
        aggregates = aggregate_results(results, [1])
        assert [(a.scope, a.key) for a in aggregates] == [
            ("all", "all"),
            ("source", "beta"),
            ("language", "pl"),
            ("group", "narrative"),
        ]

    def test_language_order_per_languages_tuple(self):
        results = [
            entry("q1", source="beta", language="pl", group="narrative"),
            entry("q2", source="beta", language="en", group="multihop"),
        ]
        aggregates = aggregate_results(results, [1])
        language_keys = [a.key for a in aggregates if a.scope == "language"]
        assert language_keys == ["pl", "en"]

    def test_all_scope_sums_whole_arm(self):
        results = [
            entry("q1", answer_correct=True),
            entry("q2", answer_correct=False),
        ]
        (agg,) = [a for a in aggregate_results(results, [1]) if a.scope == "all"]
        assert agg.n == 2  # noqa: PLR2004 — dwa wyniki w zestawie
        assert agg.n_answerable == 2  # noqa: PLR2004
        assert agg.answer_correct == 1
