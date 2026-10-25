"""Agregaty wynikow ewaluacji: zliczenia per (scope, key, arm), sklejanie
agregatow i agregacja calej listy wynikow (kontrakt C4).

Port z bety: ``Aggregate``/``merge`` z ``eval/metrics.py`` oraz
``_build_aggregate`` z ``eval/run.py``. Zmiany nazw wg kontraktu:
``corpus`` -> ``scope``, ``group`` -> ``key``, ``CrossCorpusError`` ->
``CrossScopeError``. Modul czysty: bez bazy, bez sieci, bez importow z
``app.*``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wdeval.dataset import LANGUAGES, SOURCES, EvalItem
from wdeval.judge import Verdict

Scope = Literal["all", "source", "language", "group"]


@dataclass(frozen=True)
class ItemResult:
    """Wynik jednej pozycji na jednym ramieniu (kontrakt C4)."""

    item_id: str
    source: str
    language: str
    group: str
    arm: str
    answer: str
    answer_correct: bool
    fragment_recall: dict[int, bool]
    doc_recall: dict[int, bool]
    miss_kind: str | None
    verdicts: dict[str, Verdict]
    empty_path: str | None
    retrieved_chunks: list[str]


@dataclass(frozen=True)
class Aggregate:
    """Zliczenia dla zbioru pozycji o wspolnym (scope, key) i ramieniu."""

    scope: Scope
    key: str  # "all" | nazwa zrodla | jezyk | grupa bety
    arm: str
    n: int
    n_answerable: int  # mianownik dla answer_correct i obu recalli
    answer_correct: int
    fragment_recall: dict[int, int]  # k -> liczba trafien
    doc_recall: dict[int, int]  # k -> liczba trafien
    retrieval_miss: int
    parse_miss: int
    grounded_true: int
    grounded_n: int
    empty_ok_true: int
    empty_ok_n: int
    citation_ok_true: int
    citation_ok_n: int


class CrossScopeError(RuntimeError):
    """Sklejenie agregatow dwoch roznych zakresow (scope/key) — zakazane."""


def build_aggregate(
    scope: Scope,
    key: str,
    arm: str,
    results: list[tuple[EvalItem, ItemResult]],
    k_list: list[int],
) -> Aggregate:
    """Zlicza wyniki pozycji o wspolnym (scope, key, arm).

    Port logiki ``B/run.py:_build_aggregate``: mianowniki recall i
    answer_correct licza wylacznie pozycje ``answerable`` (wg ``EvalItem``),
    brak klucza k w wyniku liczy sie jako False; werdykty liczone sa po
    WSZYSTKICH wynikach z kluczem rodzaju w ``verdicts`` i
    ``value is not None``.
    """
    n = len(results)
    answerable_entries = [(item, result) for item, result in results if item.answerable]
    n_answerable = len(answerable_entries)

    answer_correct_n = sum(1 for _, r in answerable_entries if r.answer_correct)
    fragment_recall = {
        k: sum(1 for _, r in answerable_entries if r.fragment_recall.get(k, False)) for k in k_list
    }
    doc_recall = {
        k: sum(1 for _, r in answerable_entries if r.doc_recall.get(k, False)) for k in k_list
    }
    retrieval_miss = sum(1 for _, r in answerable_entries if r.miss_kind == "retrieval-miss")
    parse_miss = sum(1 for _, r in answerable_entries if r.miss_kind == "parse-miss")

    def _verdict_counts(kind: str) -> tuple[int, int]:
        values = [
            r.verdicts[kind].value
            for _, r in results
            if kind in r.verdicts and r.verdicts[kind].value is not None
        ]
        return sum(1 for v in values if v), len(values)

    grounded_true, grounded_n = _verdict_counts("grounded")
    empty_ok_true, empty_ok_n = _verdict_counts("empty_ok")
    citation_ok_true, citation_ok_n = _verdict_counts("citation_ok")

    return Aggregate(
        scope=scope,
        key=key,
        arm=arm,
        n=n,
        n_answerable=n_answerable,
        answer_correct=answer_correct_n,
        fragment_recall=fragment_recall,
        doc_recall=doc_recall,
        retrieval_miss=retrieval_miss,
        parse_miss=parse_miss,
        grounded_true=grounded_true,
        grounded_n=grounded_n,
        empty_ok_true=empty_ok_true,
        empty_ok_n=empty_ok_n,
        citation_ok_true=citation_ok_true,
        citation_ok_n=citation_ok_n,
    )


def merge(a: Aggregate, b: Aggregate) -> Aggregate:
    """Skleja dwa agregaty o tym samym (scope, key) i ramieniu (port ``merge`` z bety)."""
    if a.scope != b.scope or a.key != b.key:
        raise CrossScopeError(
            "nie mozna sklejac agregatow z roznych zakresow: "
            f"{a.scope!r}/{a.key!r} != {b.scope!r}/{b.key!r}"
        )
    if a.arm != b.arm:
        raise ValueError(f"nie mozna sklejac agregatow z roznych ramion: {a.arm!r} != {b.arm!r}")
    if set(a.fragment_recall) != set(b.fragment_recall):
        raise ValueError(
            "nie mozna sklejac agregatow z roznymi zbiorami k w fragment_recall: "
            f"{sorted(a.fragment_recall)} != {sorted(b.fragment_recall)}"
        )
    if set(a.doc_recall) != set(b.doc_recall):
        raise ValueError(
            "nie mozna sklejac agregatow z roznymi zbiorami k w doc_recall: "
            f"{sorted(a.doc_recall)} != {sorted(b.doc_recall)}"
        )

    return Aggregate(
        scope=a.scope,
        key=a.key,
        arm=a.arm,
        n=a.n + b.n,
        n_answerable=a.n_answerable + b.n_answerable,
        answer_correct=a.answer_correct + b.answer_correct,
        fragment_recall={k: a.fragment_recall[k] + b.fragment_recall[k] for k in a.fragment_recall},
        doc_recall={k: a.doc_recall[k] + b.doc_recall[k] for k in a.doc_recall},
        retrieval_miss=a.retrieval_miss + b.retrieval_miss,
        parse_miss=a.parse_miss + b.parse_miss,
        grounded_true=a.grounded_true + b.grounded_true,
        grounded_n=a.grounded_n + b.grounded_n,
        empty_ok_true=a.empty_ok_true + b.empty_ok_true,
        empty_ok_n=a.empty_ok_n + b.empty_ok_n,
        citation_ok_true=a.citation_ok_true + b.citation_ok_true,
        citation_ok_n=a.citation_ok_n + b.citation_ok_n,
    )


def aggregate_results(
    results: list[tuple[EvalItem, ItemResult]], k_list: list[int]
) -> list[Aggregate]:
    """Agregaty dla wszystkich ramion i zakresow (kolejnosc wg kontraktu C4).

    Ramiona w kolejnosci pierwszego wystapienia w ``results``; w ramach
    ramienia: ``("all", "all")``, potem ``("source", s)`` w kolejnosci
    ``SOURCES`` (tylko obecne), ``("language", l)`` w kolejnosci ``LANGUAGES``
    (tylko obecne), na koncu ``("group", g)`` — tylko pozycje
    ``source == "beta"``, grupy posortowane alfabetycznie. Pozycje filtruje
    po ``ItemResult.arm``; zrodlo/jezyk/grupe bierze z ``ItemResult``.
    """
    arms: list[str] = []
    for _, result in results:
        if result.arm not in arms:
            arms.append(result.arm)

    aggregates: list[Aggregate] = []
    for arm in arms:
        arm_results = [(item, r) for item, r in results if r.arm == arm]
        aggregates.append(build_aggregate("all", "all", arm, arm_results, k_list))

        present_sources = {r.source for _, r in arm_results}
        for source in SOURCES:
            if source not in present_sources:
                continue
            subset = [(item, r) for item, r in arm_results if r.source == source]
            aggregates.append(build_aggregate("source", source, arm, subset, k_list))

        present_languages = {r.language for _, r in arm_results}
        for language in LANGUAGES:
            if language not in present_languages:
                continue
            subset = [(item, r) for item, r in arm_results if r.language == language]
            aggregates.append(build_aggregate("language", language, arm, subset, k_list))

        groups = sorted({r.group for _, r in arm_results if r.source == "beta"})
        for group in groups:
            subset = [
                (item, r) for item, r in arm_results if r.source == "beta" and r.group == group
            ]
            aggregates.append(build_aggregate("group", group, arm, subset, k_list))

    return aggregates
