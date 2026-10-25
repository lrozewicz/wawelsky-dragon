"""Testy metryk ewaluacji RAG — port z bety (test_eval_metrics.py) z polami
ChunkView wg kontraktu C3 (chunk_id: str, nowe pole key, content_llm -> content).

Testy Aggregate/merge przeniesione do test_aggregate.py.
"""

from __future__ import annotations

import random

import pytest

from wdeval.dataset import EvalItem, Source
from wdeval.metrics import (
    ChunkView,
    answer_correct,
    classify_miss,
    doc_recall_at_k,
    fragment_recall_at_k,
)


def make_item(**overrides) -> EvalItem:
    defaults = dict(
        id="q1",
        group="narrative",
        question="pytanie testowe",
        answerable=True,
        expected_answer="737",
        expected_answer_alt=[],
        sources=[],
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


def make_chunk(
    chunk_id: str, content: str, doc_name: str = "doc.pdf", key: str | None = None
) -> ChunkView:
    return ChunkView(
        chunk_id=chunk_id,
        key=key if key is not None else f"{doc_name}#{chunk_id}",
        doc_name=doc_name,
        content=content,
    )


class TestAnswerCorrect:
    def test_direct_hit(self):
        item = make_item(expected_answer="737")
        assert answer_correct(item, "Urzad liczyl 737 pracownikow.") is True

    def test_normalized_thousands_separator(self):
        item = make_item(expected_answer="512 585")
        assert answer_correct(item, "Ksiegozbior to 512585 woluminow.") is True

    def test_normalized_decimal_comma(self):
        item = make_item(expected_answer="82,26")
        assert answer_correct(item, "Wynosilo 82.26 lat.") is True

    def test_alt_answer_hit(self):
        item = make_item(
            expected_answer="737", expected_answer_alt=["siedemset trzydziesci siedem"]
        )
        assert answer_correct(item, "Bylo ich siedemset trzydziesci siedem.") is True

    def test_miss(self):
        item = make_item(expected_answer="737")
        assert answer_correct(item, "Nie znam odpowiedzi.") is False

    def test_unanswerable_item_returns_false(self):
        # Celowe: dla answerable=false (expected_answer=None) poprawnosc NIE
        # jest orzekana tutaj, tylko przez sedziego (werdykt empty_ok).
        # Wolajacy ma takie pozycje wylaczyc z mianownika (Aggregate.n_answerable).
        item = make_item(answerable=False, expected_answer=None, sources=[])
        assert answer_correct(item, "Nie znalazlem odpowiedzi w dokumentach.") is False


class TestFragmentRecallAtK:
    def test_hit_in_first_chunk_k1(self):
        item = make_item(sources=[make_source(fragment="737")])
        chunks = [make_chunk("c1", "tu jest 737 osob")]
        assert fragment_recall_at_k(item, chunks, k=1) is True

    def test_fragment_only_in_fourth_chunk(self):
        item = make_item(sources=[make_source(fragment="737")])
        chunks = [
            make_chunk("c1", "cos innego"),
            make_chunk("c2", "cos innego"),
            make_chunk("c3", "cos innego"),
            make_chunk("c4", "737 osob"),
        ]
        assert fragment_recall_at_k(item, chunks, k=3) is False
        assert fragment_recall_at_k(item, chunks, k=6) is True

    def test_multihop_two_fragments_two_different_chunks(self):
        item = make_item(
            sources=[
                make_source(fragment="737"),
                make_source(fragment="512 585"),
            ]
        )
        chunks = [
            make_chunk("c1", "737 pracownikow"),
            make_chunk("c2", "512585 woluminow"),
        ]
        assert fragment_recall_at_k(item, chunks, k=2) is True

    def test_multihop_second_fragment_missing_everywhere(self):
        item = make_item(
            sources=[
                make_source(fragment="737"),
                make_source(fragment="512 585"),
            ]
        )
        chunks = [
            make_chunk("c1", "737 pracownikow"),
            make_chunk("c2", "zupelnie inna tresc"),
        ]
        assert fragment_recall_at_k(item, chunks, k=2) is False

    def test_normalization_newline_vs_space(self):
        item = make_item(sources=[make_source(fragment="512 585")])
        chunks = [make_chunk("c1", "liczba 512\n585 woluminow")]
        assert fragment_recall_at_k(item, chunks, k=1) is True

    def test_k_larger_than_chunk_count_does_not_raise(self):
        item = make_item(sources=[make_source(fragment="737")])
        chunks = [make_chunk("c1", "737 osob")]
        assert fragment_recall_at_k(item, chunks, k=100) is True

    def test_no_sources_returns_false(self):
        item = make_item(sources=[])
        chunks = [make_chunk("c1", "cokolwiek")]
        assert fragment_recall_at_k(item, chunks, k=3) is False

    def test_fragment_in_wrong_document_not_counted(self):
        # Regresja na bledzie znalezionym przez testera na realnym korpusie:
        # tablica_a_..._2024_r.xlsx stoi w obu korpusach, wiec ciag cyfr ze
        # zrodla PDF potrafi przypadkiem wystapic w obcym dokumencie xlsx.
        # Fragment ma sie liczyc TYLKO w dokumencie swojego wlasnego zrodla.
        item = make_item(sources=[make_source(file="gus_scan_synth.pdf", fragment="737")])
        wrong_doc_chunk = make_chunk("c1", "tabela: 273797.0", doc_name="tablica_a.xlsx")
        assert fragment_recall_at_k(item, [wrong_doc_chunk], k=1) is False

    def test_multihop_same_file_different_chunks_still_true(self):
        # Multihop w obrebie JEDNEGO pliku - nie przeregulowac zawezeniem
        # do dokumentu.
        item = make_item(
            sources=[
                make_source(file="doc.pdf", fragment="737"),
                make_source(file="doc.pdf", fragment="512 585"),
            ]
        )
        chunks = [
            make_chunk("c1", "737 pracownikow", doc_name="doc.pdf"),
            make_chunk("c2", "512585 woluminow", doc_name="doc.pdf"),
        ]
        assert fragment_recall_at_k(item, chunks, k=2) is True

    def test_foreign_document_fragment_in_top1_then_own_document(self):
        # Przykład z briefu T1 (doslownie): zrodlo file="a.pdf", fragment="1 264",
        # chunki z kluczami stabilnymi "<doc>#<ordinal>". k=1 -> False (fragment
        # tylko w obcym dokumencie b.pdf), k=2 -> True (wlasny dokument a.pdf).
        item = make_item(sources=[make_source(file="a.pdf", fragment="1 264")])
        chunks = [
            ChunkView("x", "b.pdf#0", "b.pdf", "1 264"),
            ChunkView("y", "a.pdf#3", "a.pdf", "ok 1264"),
        ]
        assert fragment_recall_at_k(item, chunks, k=1) is False
        assert fragment_recall_at_k(item, chunks, k=2) is True


class TestFragmentDocRecallInvariant:
    def test_fragment_recall_implies_doc_recall(self):
        # Niezmiennik: jesli fragment_recall_at_k jest True, doc_recall_at_k
        # dla tych samych (item, chunks, k) tez musi byc True - bo zrodlo
        # fragmentu jest dopasowywane po dokumencie tak samo jak w doc_recall.
        # Bez tego "fragment znaleziony, ale nie w tym dokumencie" byloby
        # wewnetrznie niespojne i nie do zaraportowania.
        rng = random.Random(20260906)  # noqa: S311 — losowosc testowa (invariant), nie kryptografia
        files = ["a.pdf", "b.pdf", "c.pdf"]

        for trial in range(200):
            n_sources = rng.randint(1, 3)
            sources = [
                make_source(file=rng.choice(files), fragment=f"frag{trial}-{i}")
                for i in range(n_sources)
            ]
            item = make_item(sources=sources)

            n_chunks = rng.randint(1, 6)
            chunks = []
            for c in range(n_chunks):
                doc_name = rng.choice(files)
                pieces = [source.fragment for source in sources if rng.random() < 0.4]  # noqa: PLR2004
                content = " ".join(pieces) if pieces else f"szum-{trial}-{c}"
                chunks.append(make_chunk(str(c), content, doc_name=doc_name))

            k = rng.randint(1, n_chunks)
            fr = fragment_recall_at_k(item, chunks, k)
            dr = doc_recall_at_k(item, chunks, k)
            assert (not fr) or dr, (
                f"trial={trial}: fragment_recall_at_k=True ale doc_recall_at_k=False "
                f"(sources={sources}, chunks={chunks}, k={k})"
            )


class TestDocRecallAtK:
    def test_doc_present_in_top_k(self):
        item = make_item(sources=[make_source(file="doc.pdf")])
        chunks = [make_chunk("c1", "tresc", doc_name="doc.pdf")]
        assert doc_recall_at_k(item, chunks, k=1) is True

    def test_two_sources_only_one_doc_in_top_k(self):
        item = make_item(
            sources=[
                make_source(file="doc1.pdf"),
                make_source(file="doc2.pdf"),
            ]
        )
        chunks = [make_chunk("c1", "tresc", doc_name="doc1.pdf")]
        assert doc_recall_at_k(item, chunks, k=1) is False

    def test_case_insensitive(self):
        item = make_item(sources=[make_source(file="Doc.PDF")])
        chunks = [make_chunk("c1", "tresc", doc_name="doc.pdf")]
        assert doc_recall_at_k(item, chunks, k=1) is True

    def test_not_substring_match(self):
        item = make_item(sources=[make_source(file="gus_excerpt.pdf")])
        chunks = [make_chunk("c1", "tresc", doc_name="gus_excerpt_v2.pdf")]
        assert doc_recall_at_k(item, chunks, k=1) is False

    def test_no_sources_returns_false(self):
        item = make_item(sources=[])
        chunks = [make_chunk("c1", "tresc", doc_name="doc.pdf")]
        assert doc_recall_at_k(item, chunks, k=1) is False


class TestClassifyMiss:
    def test_hit(self):
        item = make_item(sources=[make_source(fragment="737")])
        top_k = [make_chunk("c1", "737 osob")]
        all_kb = top_k
        assert classify_miss(item, top_k, all_kb) == "hit"

    def test_retrieval_miss(self):
        item = make_item(sources=[make_source(fragment="737")])
        top_k = [make_chunk("c1", "cos innego")]
        all_kb = [make_chunk("c1", "cos innego"), make_chunk("c2", "737 osob")]
        assert classify_miss(item, top_k, all_kb) == "retrieval-miss"

    def test_parse_miss(self):
        item = make_item(sources=[make_source(fragment="737")])
        top_k = [make_chunk("c1", "cos innego")]
        all_kb = [make_chunk("c1", "cos innego"), make_chunk("c2", "zupelnie inna tresc")]
        assert classify_miss(item, top_k, all_kb) == "parse-miss"

    def test_no_sources_raises_value_error(self):
        # Rozstrzygniecie team-leadera: classify_miss jest zdefiniowana
        # wylacznie dla answerable=true. Wakuistyczne "hit" (all([]) == True)
        # wliczaloby pozycje unanswerable do licznika trafien i cicho zawyzalo
        # recall kazdego ramienia - straznik w postaci wyjatku wymusza
        # jawne rozgalezenie u wolajacego (poprawnosc pozycji bez zrodel
        # orzeka sedzia przez empty_ok). Przyklad z briefu T1:
        # classify_miss(item_bez_zrodel, [], []) -> ValueError.
        item = make_item(sources=[])
        with pytest.raises(ValueError):
            classify_miss(item, [], [])

    def test_fragment_present_only_in_wrong_document_is_parse_miss(self):
        # Ten sam scenariusz co w TestFragmentRecallAtK, przelozony na
        # klasyfikacje pudel: fragment fizycznie istnieje w KB, ale w OBCYM
        # dokumencie - parser wlasnego dokumentu go zgubil, wiec to
        # "parse-miss", NIE "retrieval-miss" (ktore sugerowaloby, ze parser
        # go ma, tylko retrieval nie wyciagnal).
        item = make_item(sources=[make_source(file="own.pdf", fragment="737")])
        top_k = [make_chunk("c1", "cos innego", doc_name="own.pdf")]
        all_kb = [
            make_chunk("c1", "cos innego", doc_name="own.pdf"),
            make_chunk("c2", "737 osob", doc_name="obcy.pdf"),
        ]
        assert classify_miss(item, top_k, all_kb) == "parse-miss"

    def test_fragment_present_in_own_document_outside_top_k_is_retrieval_miss(self):
        item = make_item(sources=[make_source(file="own.pdf", fragment="737")])
        top_k = [make_chunk("c1", "cos innego", doc_name="own.pdf")]
        all_kb = [
            make_chunk("c1", "cos innego", doc_name="own.pdf"),
            make_chunk("c2", "737 osob", doc_name="own.pdf"),
        ]
        assert classify_miss(item, top_k, all_kb) == "retrieval-miss"

    def test_one_fragment_missing_everywhere_forces_parse_miss(self):
        item = make_item(
            sources=[
                make_source(fragment="737"),
                make_source(fragment="brakujacy fragment"),
            ]
        )
        top_k = [make_chunk("c1", "cos innego")]
        all_kb = [make_chunk("c1", "cos innego"), make_chunk("c2", "737 osob")]
        # "737" jest w calym KB, ale "brakujacy fragment" nie ma nigdzie ->
        # cala pozycja to parse-miss, mimo ze jeden fragment by sie znalazl.
        assert classify_miss(item, top_k, all_kb) == "parse-miss"
