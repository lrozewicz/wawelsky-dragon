"""Testy pętli ewaluacji na atrapach ask/judge/all_chunks (kontrakt C14).

Sens testów przeniesiony z bety (``tests/unit/test_eval_run.py``); adaptery
produkcyjne (``make_ask``/``make_judge``) pokrywa test integracyjny — świadomie
nieobecne tutaj.
"""

from __future__ import annotations

from typing import Any

import pytest

from wdeval.aggregate import Aggregate
from wdeval.dataset import EvalItem, Source
from wdeval.evaluate import (
    Answer,
    DocumentNameGuardError,
    RunResult,
    run_evaluation,
    to_beta_citations,
)
from wdeval.judge import Verdict
from wdeval.metrics import ChunkView


def _chunk(key: str, doc_name: str, content: str = "kontekst z liczbą 42 wewnątrz") -> ChunkView:
    return ChunkView(chunk_id=f"cid-{key}", key=key, doc_name=doc_name, content=content)


_DEFAULT_CHUNKS = (_chunk("doc1.pdf#0", "doc1.pdf"),)


def _source(file: str, fragment: str = "42") -> Source:
    return Source(
        file=file, locator={"page": 1}, fragment=fragment, quote=fragment, derived_from=None
    )


def _item(  # noqa: PLR0913 — pomocnik z kontraktu C14 (id, grupa + opcje)
    item_id: str,
    group: str,
    *,
    answerable: bool = True,
    question: str = "Ile?",
    source: str = "beta",
    language: str = "pl",
) -> EvalItem:
    sources = [_source("doc1.pdf")] if answerable else []
    return EvalItem(
        id=item_id,
        group=group,
        question=question,
        answerable=answerable,
        expected_answer="42" if answerable else None,
        sources=sources,
        source=source,
        language=language,
    )


class Fakes:
    """Atrapy ask/judge/all_chunks z licznikami wywołań (jak w bety Counters)."""

    def __init__(
        self,
        *,
        answers: dict[str, str] | None = None,
        chunks_by_arm: dict[str, list[ChunkView]] | None = None,
        judge_values: dict[str, bool | None] | None = None,
    ) -> None:
        self.answers = answers if answers is not None else {}
        self.chunks_by_arm = chunks_by_arm if chunks_by_arm is not None else {}
        self.judge_values = judge_values if judge_values is not None else {}
        self.judge_calls: list[tuple[str, dict[str, str]]] = []
        self.all_chunks_calls: dict[str, int] = {}

    async def ask(self, arm: str, question: str) -> Answer:
        chunks = self.chunks_by_arm.get(arm)
        if chunks is None:
            chunks = list(_DEFAULT_CHUNKS)
        return Answer(text=self.answers.get(question, "42"), chunks=chunks)

    async def judge(self, kind: str, payload: dict[str, str]) -> Verdict:
        self.judge_calls.append((kind, payload))
        value = self.judge_values.get(kind, True)
        return Verdict(kind=kind, value=value, raw="TAK" if value else "NIE")

    async def all_chunks(self, arm: str) -> list[ChunkView]:
        self.all_chunks_calls[arm] = self.all_chunks_calls.get(arm, 0) + 1
        chunks = self.chunks_by_arm.get(arm)
        if chunks is None:
            return [_chunk("doc1.pdf#0", "doc1.pdf"), _chunk("doc2.xlsx#0", "doc2.xlsx")]
        return chunks


def _run_kwargs(fakes: Fakes) -> dict[str, Any]:
    return {
        "ask": fakes.ask,
        "judge": fakes.judge,
        "all_chunks": fakes.all_chunks,
        "documents": {"fast": {"doc1.pdf"}, "vision": {"doc1.pdf"}},
    }


def test_to_beta_citations_przesuwa_markery_o_jeden() -> None:
    assert to_beta_citations("a [ID:0] b [ID:12]") == "a [1] b [13]"


async def test_puste_ramiona_pusty_wynik() -> None:
    fakes = Fakes()
    result = await run_evaluation([], [], k_list=[1], **_run_kwargs(fakes))
    assert result == RunResult(results=[], aggregates=[], comparisons=[])
    assert fakes.all_chunks_calls == {}


async def test_bieg_jedno_ramie_wyniki_i_agregaty() -> None:
    fakes = Fakes()
    items = [_item("q1", "narrative")]
    result = await run_evaluation(items, ["fast"], k_list=[1, 3], **_run_kwargs(fakes))

    assert len(result.results) == 1
    item, single = result.results[0]
    assert item.id == "q1"
    assert single.arm == "fast"
    assert single.source == "beta"
    assert single.language == "pl"
    assert single.group == "narrative"
    assert single.answer == "42"
    assert single.answer_correct is True
    assert single.miss_kind == "hit"
    assert single.fragment_recall == {1: True, 3: True}
    assert single.doc_recall == {1: True, 3: True}
    assert single.retrieved_chunks == ["doc1.pdf#0"]
    assert [agg.scope for agg in result.aggregates] == ["all", "source", "language", "group"]
    assert result.aggregates[0].arm == "fast"
    assert isinstance(result.aggregates[0], Aggregate)
    assert result.comparisons == []


async def test_all_chunks_wolany_raz_na_ramie() -> None:
    fakes = Fakes()
    items = [_item("q1", "narrative"), _item("q2", "narrative", question="Ile?")]
    await run_evaluation(items, ["fast", "vision"], k_list=[1], **_run_kwargs(fakes))
    assert fakes.all_chunks_calls == {"fast": 1, "vision": 1}


async def test_straznik_nazw_dokumentow_rzuca_z_brakujaca_nazwa() -> None:
    fakes = Fakes()
    items = [_item("q1", "narrative"), _item("q4", "unanswerable", answerable=False)]
    with pytest.raises(DocumentNameGuardError) as excinfo:
        await run_evaluation(
            items,
            ["fast"],
            k_list=[1],
            ask=fakes.ask,
            judge=fakes.judge,
            all_chunks=fakes.all_chunks,
            documents={"fast": {"inna-nazwa.pdf"}},
        )
    assert "ramię fast" in str(excinfo.value)
    assert "doc1.pdf" in str(excinfo.value)


async def test_pozycja_bez_odpowiedzi_przechodzi_straznika() -> None:
    """Pozycja answerable=false (bez źródeł) nie ma czego strzec — strażnik milczy."""
    fakes = Fakes()
    items = [_item("q4", "unanswerable", answerable=False)]
    result = await run_evaluation(items, ["fast"], k_list=[1], **_run_kwargs(fakes))
    assert len(result.results) == 1


async def test_grounded_tylko_przy_niepustej_odpowiedzi() -> None:
    puste = Fakes(answers={"Q1?": ""})
    result = await run_evaluation(
        [_item("q1", "narrative", question="Q1?")], ["fast"], k_list=[1], **_run_kwargs(puste)
    )
    (_, r_puste) = result.results[0]
    assert "grounded" not in r_puste.verdicts
    assert puste.judge_calls == []

    pelne = Fakes()
    result = await run_evaluation(
        [_item("q1", "narrative", question="Q1?")], ["fast"], k_list=[1], **_run_kwargs(pelne)
    )
    (_, r_pelne) = result.results[0]
    assert "grounded" in r_pelne.verdicts


async def test_citation_ok_tylko_z_markrem() -> None:
    bez_markera = Fakes(answers={"Q1?": "42."})
    result = await run_evaluation(
        [_item("q1", "narrative", question="Q1?")], ["fast"], k_list=[1], **_run_kwargs(bez_markera)
    )
    (_, r_bez) = result.results[0]
    assert "citation_ok" not in r_bez.verdicts
    assert [kind for kind, _ in bez_markera.judge_calls] == ["grounded"]

    z_markrem = Fakes(answers={"Q1?": "42 [ID:0]"})
    result = await run_evaluation(
        [_item("q1", "narrative", question="Q1?")], ["fast"], k_list=[1], **_run_kwargs(z_markrem)
    )
    (_, r_z) = result.results[0]
    assert "citation_ok" in r_z.verdicts
    assert [kind for kind, _ in z_markrem.judge_calls] == ["grounded", "citation_ok"]


async def test_sedzia_dostaje_przetlumaczone_cytowania_i_kontekst() -> None:
    fakes = Fakes(answers={"Q1?": "42 [ID:0] [ID:3]"})
    await run_evaluation(
        [_item("q1", "narrative", question="Q1?")], ["fast"], k_list=[1], **_run_kwargs(fakes)
    )
    translated = {kind: payload for kind, payload in fakes.judge_calls}
    assert translated["grounded"]["answer"] == "42 [1] [4]"
    assert translated["citation_ok"]["answer"] == "42 [1] [4]"
    assert translated["grounded"]["question"] == "Q1?"
    assert translated["grounded"]["context"] == (
        "[Źródło 1] (doc1.pdf)\nkontekst z liczbą 42 wewnątrz"
    )


async def test_empty_path_no_chunks_gdy_retrieval_pusty() -> None:
    fakes = Fakes(chunks_by_arm={"fast": []})
    result = await run_evaluation(
        [_item("q4", "unanswerable", answerable=False, question="Q4?")],
        ["fast"],
        k_list=[1],
        **_run_kwargs(fakes),
    )
    (_, r) = result.results[0]
    assert r.empty_path == "no_chunks"
    assert "empty_ok" in r.verdicts


async def test_empty_path_prose_refusal_gdy_sedzia_uznal_odmowe() -> None:
    fakes = Fakes(judge_values={"empty_ok": True})
    result = await run_evaluation(
        [_item("q4", "unanswerable", answerable=False, question="Q4?")],
        ["fast"],
        k_list=[1],
        **_run_kwargs(fakes),
    )
    (_, r) = result.results[0]
    assert r.empty_path == "prose_refusal"


async def test_empty_path_none_gdy_sedzia_uznal_halucynacje() -> None:
    fakes = Fakes(judge_values={"empty_ok": False})
    result = await run_evaluation(
        [_item("q4", "unanswerable", answerable=False, question="Q4?")],
        ["fast"],
        k_list=[1],
        **_run_kwargs(fakes),
    )
    (_, r) = result.results[0]
    assert r.empty_path is None


async def test_pozycja_bez_odpowiedzi_ma_miss_kind_none() -> None:
    fakes = Fakes()
    result = await run_evaluation(
        [_item("q4", "unanswerable", answerable=False, question="Q4?")],
        ["fast"],
        k_list=[1],
        **_run_kwargs(fakes),
    )
    (_, r) = result.results[0]
    assert r.miss_kind is None
    assert r.answer_correct is False


async def test_comparisons_przy_dwuch_ramionach() -> None:
    fakes = Fakes()
    items = [_item("q1", "narrative"), _item("q4", "unanswerable", answerable=False)]
    result = await run_evaluation(items, ["vision", "fast"], k_list=[1], **_run_kwargs(fakes))
    assert result.comparisons == [
        {
            "arms": ["fast", "vision"],
            "common_question_ids": ["q1", "q4"],
            "common_count": 2,
            "total": 2,
        }
    ]
    assert result.aggregates  # oba ramiona w agregatach
    assert {agg.arm for agg in result.aggregates} == {"fast", "vision"}
