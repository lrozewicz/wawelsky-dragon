"""Testy chunk_terms, term_similarity, fuse, apply_thresholds i doc_aggs (CONTRACT WP E1-7 M3)."""

import pytest

from app.domain.retrieval.scoring import (
    RRF_K,
    apply_thresholds,
    chunk_terms,
    doc_aggs,
    fuse,
    rank_key,
    term_similarity,
)
from app.domain.retrieval.types import (
    Candidate,
    DocAgg,
    QueryTerms,
    Scored,
    ThresholdConfig,
)

CFG = ThresholdConfig(min_vector_sim=0.25, min_rerank_score=0.1)
EXPECTED_RRF_K = 60


def cand(
    chunk_id: str = "c1", *, v: float = 0.0, t: float = 0.0, rerank: float | None = None
) -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        document_id="d1",
        document_name="a",
        ordinal=0,
        vector_similarity=v,
        term_similarity=t,
        rerank_score=rerank,
    )


def doc_cand(doc: str, name: str) -> Candidate:
    return Candidate(
        chunk_id=f"c-{doc}",
        document_id=doc,
        document_name=name,
        ordinal=0,
        vector_similarity=0.0,
        term_similarity=0.0,
    )


def tie_cand(chunk_id: str, name: str, ordinal: int) -> Candidate:
    """Kandydat bez żadnego trafienia — similarity 0.0, czyli remis z każdym innym (C3)."""
    return Candidate(
        chunk_id=chunk_id,
        document_id=f"d-{chunk_id}",
        document_name=name,
        ordinal=ordinal,
        vector_similarity=0.0,
        term_similarity=0.0,
    )


def scored(*, v: float, t: float, sim: float, rerank: float | None = None) -> Scored:
    return Scored(cand(v=v, t=t, rerank=rerank), sim)


def test_chunk_terms_dedups_content_and_multiplies_rest() -> None:
    assert chunk_terms("a b a", "t", "", "") == frozenset({"a", "b", "t", "a b", "b t", "t t"})


def test_term_similarity_hits() -> None:
    q = QueryTerms(
        raw_terms=(), terms=(("a", 0.4), ("b", 0.4)), bigrams=(("a b", 0.6),), ft_raw="", ft_stem=""
    )
    assert term_similarity(q, frozenset({"a", "a b"})) == pytest.approx((0.4 + 0.6) / 1.4)


def test_term_similarity_empty_query() -> None:
    # Pusta suma wag zapytania → 0.0 (R0 p. 9).
    q = QueryTerms(raw_terms=(), terms=(), bigrams=(), ft_raw="", ft_stem="")
    assert term_similarity(q, frozenset({"a"})) == 0.0


def test_term_similarity_no_hits() -> None:
    q = QueryTerms(raw_terms=(), terms=(("x", 0.4),), bigrams=(), ft_raw="", ft_stem="")
    assert term_similarity(q, frozenset({"a", "b"})) == 0.0


def test_fuse_weighted() -> None:
    cands = [cand("c1", v=0.9, t=0.0), cand("c2", v=0.1, t=1.0)]
    result = fuse(cands, 0.3, "weighted")
    assert [s.candidate.chunk_id for s in result] == ["c2", "c1"]
    assert [s.similarity for s in result] == pytest.approx([0.73, 0.27])


def test_fuse_weighted_uses_rerank_score_when_present() -> None:
    result = fuse([cand("c1", v=0.5, t=0.5, rerank=0.9)], 0.3, "weighted")
    assert [s.similarity for s in result] == pytest.approx([0.7 * 0.5 + 0.3 * 0.9])


def test_fuse_rrf_three_candidates() -> None:
    cands = [cand("A", v=0.9, t=0.1), cand("B", v=0.5, t=0.5), cand("C", v=0.1, t=0.9)]
    result = fuse(cands, 0.3, "rrf")
    assert [s.candidate.chunk_id for s in result] == ["A", "C", "B"]
    assert [s.similarity for s in result] == pytest.approx([1.0, 1.0, 0.0])


def test_fuse_rrf_single_candidate() -> None:
    result = fuse([cand("c1", v=0.4, t=0.2)], 0.3, "rrf")
    assert [s.similarity for s in result] == pytest.approx([1.0])


def test_fuse_rrf_empty() -> None:
    assert fuse([], 0.3, "rrf") == []


def test_fuse_rrf_ignores_partial_rerank() -> None:
    # Rerank wliczany tylko gdy MA go każdy kandydat; tu A ma 0.0, B None — pomijany, remis → 1.0.
    cands = [cand("A", v=0.9, t=0.1, rerank=0.0), cand("B", v=0.1, t=0.9, rerank=None)]
    result = fuse(cands, 0.3, "rrf")
    assert [s.similarity for s in result] == pytest.approx([1.0, 1.0])


def test_fuse_rrf_uses_full_rerank() -> None:
    # Gdy każdy ma rerank: A wygrywa vector i term, przegrywa rerank — nadal pierwszeństwo A.
    cands = [cand("A", v=0.9, t=0.9, rerank=0.1), cand("B", v=0.1, t=0.1, rerank=0.9)]
    result = fuse(cands, 0.3, "rrf")
    assert [s.candidate.chunk_id for s in result] == ["A", "B"]
    assert [s.similarity for s in result] == pytest.approx([1.0, 0.0])


def test_rank_key_ties_doc_name_ordinal_chunk_id() -> None:
    """Remis similarity → (document_name, ordinal, chunk_id) — przykład z briefu D3.

    Wejście: b.txt#0, a.txt#1, a.txt#0 → wyjście: a.txt#0, a.txt#1, b.txt#0.
    """
    a0 = "9" * 16
    a1 = "8" * 16
    b0 = "7" * 16
    cands = [tie_cand(b0, "b.txt", 0), tie_cand(a1, "a.txt", 1), tie_cand(a0, "a.txt", 0)]
    result = fuse(cands, 0.3, "weighted")
    assert [s.similarity for s in result] == [0.0, 0.0, 0.0]
    assert [s.candidate.chunk_id for s in result] == [a0, a1, b0]


def test_rank_key_ties_same_doc_and_ordinal_sorted_by_chunk_id() -> None:
    """Ten sam dokument i ten sam ordinal → rozstrzyga chunks.id rosnąco (C3)."""
    result = fuse([tie_cand("f" * 16, "a.txt", 0), tie_cand("0" * 16, "a.txt", 0)], 0.3, "weighted")
    assert [s.candidate.chunk_id for s in result] == ["0" * 16, "f" * 16]


def test_rank_key_ties_independent_of_input_order() -> None:
    """Wynik remisu nie zależy od kolejności wejścia kandydatów (C3)."""
    a0 = "9" * 16
    a1 = "8" * 16
    b0 = "7" * 16
    cands = [tie_cand(b0, "b.txt", 0), tie_cand(a1, "a.txt", 1), tie_cand(a0, "a.txt", 0)]

    def key(s: Scored) -> tuple[str, int, str]:
        return (s.candidate.document_name, s.candidate.ordinal, s.candidate.chunk_id)

    forward = [key(s) for s in fuse(cands, 0.3, "weighted")]
    backward = [key(s) for s in fuse(list(reversed(cands)), 0.3, "weighted")]
    assert forward == backward == [("a.txt", 0, a0), ("a.txt", 1, a1), ("b.txt", 0, b0)]


def test_rank_key_rrf_sorts_by_tiebreak_when_similarity_equal() -> None:
    """RRF (jak każdy tryb) sortuje kluczem rank_key, gdy similarity się zrówna (C3)."""
    a0 = "9" * 16
    b0 = "7" * 16
    scored_ties = [Scored(tie_cand(b0, "b.txt", 0), 0.5), Scored(tie_cand(a0, "a.txt", 0), 0.5)]
    assert [s.candidate.chunk_id for s in sorted(scored_ties, key=rank_key)] == [a0, b0]


def test_rrf_k_constant() -> None:
    assert RRF_K == EXPECTED_RRF_K


def test_apply_thresholds_rule1_low_vector_and_no_terms() -> None:
    result = apply_thresholds([scored(v=0.2, t=0.0, sim=0.5)], ThresholdConfig(0.25, 0.1), 0.3, 0.2)
    assert result == []


def test_apply_thresholds_rule1_passes_with_terms() -> None:
    out = apply_thresholds([scored(v=0.2, t=0.1, sim=0.5)], ThresholdConfig(0.25, 0.1), 0.3, 0.2)
    assert len(out) == 1


def test_apply_thresholds_rule2_low_rerank() -> None:
    assert apply_thresholds([scored(v=0.9, t=0.5, sim=0.9, rerank=0.05)], CFG, 0.3, 0.2) == []


def test_apply_thresholds_rule3_post_threshold() -> None:
    # Próg 0 przy w <= 0 — zostaje; przy w > 0 — odrzucony poniżej progu użytkownika.
    assert len(apply_thresholds([scored(v=0.0, t=0.1, sim=0.1)], CFG, 0.0, 0.2)) == 1
    assert apply_thresholds([scored(v=0.0, t=0.1, sim=0.1)], CFG, 0.3, 0.2) == []


def test_apply_thresholds_rule1_uses_candidate_vector_not_rerank() -> None:
    # W regule 1 vector_similarity to cosinus kandydata (nie rerank): trafienie termowe ratuje.
    out = apply_thresholds([scored(v=0.9, t=0.5, sim=0.9, rerank=0.5)], CFG, 0.3, 0.2)
    assert len(out) == 1


def test_doc_aggs_empty() -> None:
    assert doc_aggs([]) == []


def test_doc_aggs_counts_and_order() -> None:
    s1 = Scored(doc_cand("d1", "a"), 0.5)
    s2 = Scored(doc_cand("d2", "b"), 0.4)
    s3 = Scored(doc_cand("d2", "b"), 0.3)
    assert doc_aggs([s1, s2, s3]) == [DocAgg("b", "d2", 2), DocAgg("a", "d1", 1)]


def test_doc_aggs_tie_keeps_first_occurrence_order() -> None:
    s1 = Scored(doc_cand("d1", "a"), 0.5)
    s2 = Scored(doc_cand("d2", "b"), 0.4)
    s3 = Scored(doc_cand("d3", "c"), 0.3)
    assert doc_aggs([s1, s2, s3]) == [
        DocAgg("a", "d1", 1),
        DocAgg("b", "d2", 1),
        DocAgg("c", "d3", 1),
    ]
