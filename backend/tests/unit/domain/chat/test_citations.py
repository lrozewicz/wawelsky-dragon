"""Testy cytowań i referencji R (CONTRACT C8, K4 §1.2)."""

import pytest

from app.domain.chat.citations import (
    BAD_CITATION_PATTERNS,
    CITATION_MARKER_PATTERN,
    answer_pieces,
    api_key_hint,
    build_reference,
    chunk_ref,
    find_citations,
    has_citation_marker,
    hybrid_similarity,
    normalize_arabic_digits,
    place_citations,
    repair_citations,
)
from app.domain.retrieval.types import DocAgg, RetrievedChunk


def _chunk(chunk_id: str, document_id: str = "d1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        content=f"treść {chunk_id}",
        content_llm=f"llm {chunk_id}",
        content_terms="terms",
        document_id=document_id,
        document_name="doc.pdf",
        dataset_id="kb1",
        image_id="img1",
        important_keywords=["kw"],
        questions=["q?"],
        tag_kwd=["tag"],
        positions=[[0, 1, 2, 3]],
        similarity=0.9,
        vector_similarity=0.8,
        term_similarity=0.7,
        highlight="highlight",
        doc_type="text",
        url="http://x",
        document_metadata={"k": "v"},
    )


def test_normalize_arabic_digits() -> None:
    assert normalize_arabic_digits("a٠١b") == "a01b"  # noqa: RUF001
    assert normalize_arabic_digits("۰۱۲") == "012"
    assert normalize_arabic_digits("abc 0") == "abc 0"
    assert normalize_arabic_digits("") == ""


def test_citation_marker_pattern_is_upstream_literal() -> None:
    assert CITATION_MARKER_PATTERN.pattern == r"\[(?:ID:)?([0-9\u0660-\u0669\u06F0-\u06F9]+)\]"


def test_bad_citation_patterns_are_upstream_literal() -> None:
    assert [pattern.pattern for pattern in BAD_CITATION_PATTERNS] == [
        r"\(\s*ID\s*[: ]*\s*(\d+)\s*\)",
        r"\[\s*ID\s*[: ]*\s*(\d+)\s*\]",
        r"【\s*ID\s*[: ]*\s*(\d+)\s*】",
        r"ref\s*(\d+)",
    ]


def test_has_citation_marker() -> None:
    assert has_citation_marker("Tak [ID:0].") is True
    assert has_citation_marker("Tak [١].") is True  # cyfra arabska  # noqa: RUF001
    assert has_citation_marker("Tak (ID: 1).") is False
    assert has_citation_marker("") is False


def test_find_citations() -> None:
    assert find_citations("A [ID:0] B [ID:3] C [2]", 3) == {0, 2}  # 3 poza zakresem
    assert find_citations("A [ID:0]", 0) == set()
    assert find_citations("bez znaczników", 3) == set()


def test_repair_citations_mixed_formats() -> None:
    idx: set[int] = set()
    answer, repaired = repair_citations("A (ID: 1) B 【ID: 0】 C ref 7", 2, idx)
    assert answer == "A [ID:1] B [ID:0] C ref 7"  # 7 poza zakresem — bez zmiany
    assert repaired == {0, 1}
    assert idx == set()  # wejściowy zbiór nie jest mutowany


def test_repair_citations_extends_existing_idx() -> None:
    assert repair_citations("[ID: 1]", 2, {0}) == ("[ID:1]", {0, 1})


def test_repair_citations_multiple_matches_one_pattern() -> None:
    answer, repaired = repair_citations("see ref 1 and REF 2", 3, set())
    assert answer == "see [ID:1] and [ID:2]"
    assert repaired == {1, 2}


def test_repair_citations_out_of_range_unchanged() -> None:
    assert repair_citations("zobacz ref 9", 2, set()) == ("zobacz ref 9", set())


def test_repair_citations_no_match_keeps_idx() -> None:
    assert repair_citations("czysty tekst", 2, {1}) == ("czysty tekst", {1})


def test_repair_citations_keeps_original_digits() -> None:
    answer, repaired = repair_citations("(ID: ١)", 2, set())  # noqa: RUF001
    assert answer == "[ID:١]"  # noqa: RUF001
    assert repaired == {1}


def test_answer_pieces_sentences() -> None:
    pieces, eligible = answer_pieces("Pierwsze zdanie. Drugie zdanie! Ok")
    assert "".join(pieces) == "Pierwsze zdanie. Drugie zdanie! Ok"
    assert pieces == ["Pierwsze zdanie", ". ", "Drugie zdanie", "!", " Ok"]
    assert eligible == [0, 2]


def test_answer_pieces_polish_sentence_end() -> None:
    pieces, eligible = answer_pieces("Mam psa ż. Kot")
    assert "".join(pieces) == "Mam psa ż. Kot"
    assert pieces == ["Mam psa ż", ". ", "Kot"]  # podział po "ż. "
    assert eligible == [0]


def test_answer_pieces_code_block_is_single_piece() -> None:
    answer = "Before.\n```python\nprint(1)\n```\nAfter."
    pieces, eligible = answer_pieces(answer)
    assert pieces[3] == "```python\nprint(1)\n```\n"  # blok kodu + dopisane "\n"
    assert eligible == [0, 3, 4]


def test_answer_pieces_unterminated_code_block() -> None:
    pieces, eligible = answer_pieces("Text. ```code block")
    assert pieces == ["Text", ". ", "", "```code block\n"]
    assert eligible == [3]


def test_hybrid_similarity_zero_vector_sims() -> None:
    assert hybrid_similarity([0.0, 0.0], [0.5, 0.2], 0.7, 0.3) == [0.5, 0.2]


def test_hybrid_similarity_weighted_sum() -> None:
    result = hybrid_similarity([1.0, 0.0], [0.5, 0.2], 0.7, 0.3)
    assert result == pytest.approx([0.65, 0.14], abs=1e-9)


def test_place_citations() -> None:
    answer, cited = place_citations(
        ["Zdanie pierwsze.", " Drugie zdanie."], [0, 1], [[0.9, 0.1], [0.2, 0.8]]
    )
    assert answer == "Zdanie pierwsze. [ID:0] Drugie zdanie. [ID:1]"
    assert cited == {0, 1}


def test_place_citations_threshold_lowers_until_cite() -> None:
    # cytowanie dopiero przy thr ≈ 0.3226 (0.35 * 0.99 >= 0.3226)
    answer, cited = place_citations(["pięć znaków"], [0], [[0.35]])
    assert answer == "pięć znaków [ID:0]"
    assert cited == {0}


def test_place_citations_below_threshold_no_cites() -> None:
    assert place_citations(["pięć znaków"], [0], [[0.30]]) == ("pięć znaków", set())


def test_place_citations_max_four_ascending() -> None:
    answer, cited = place_citations(["pięć znaków"], [0], [[0.9] * 6])
    assert answer == "pięć znaków [ID:0] [ID:1] [ID:2] [ID:3]"
    assert cited == {0, 1, 2, 3}


def test_place_citations_chunk_not_repeated() -> None:
    answer, cited = place_citations(
        ["pierwszy kawałek.", " drugi kawałek."], [0, 1], [[0.9, 0.1], [0.9, 0.1]]
    )
    assert answer == "pierwszy kawałek. [ID:0] drugi kawałek."
    assert cited == {0}


def test_place_citations_no_chunks_or_pieces() -> None:
    assert place_citations(["abc"], [], []) == ("abc", set())
    assert place_citations(["abc"], [0], [[]]) == ("abc", set())
    assert place_citations(["abc"], [], [[0.9]]) == ("abc", set())


def test_api_key_hint() -> None:
    hint = " Please set LLM API-Key in 'User Setting -> Model providers -> API-Key'"
    assert api_key_hint("Error: Invalid API key") == "Error: Invalid API key" + hint
    assert api_key_hint("invalid key provided") == "invalid key provided" + hint
    assert api_key_hint("ok") == "ok"


def test_chunk_ref_keys_and_mapping() -> None:
    ref = chunk_ref(_chunk("c0"))
    assert list(ref.keys()) == [
        "id",
        "content",
        "document_id",
        "document_name",
        "dataset_id",
        "image_id",
        "positions",
        "url",
        "similarity",
        "vector_similarity",
        "term_similarity",
        "row_id",
        "doc_type",
        "document_metadata",
    ]
    assert ref["id"] == "c0"
    assert ref["content"] == "treść c0"  # content, nie content_llm
    assert ref["row_id"] is None
    assert ref["document_metadata"] == {"k": "v"}
    assert "content_llm" not in ref
    assert "content_terms" not in ref
    assert "highlight" not in ref


def test_build_reference_narrows_doc_aggs_to_cited() -> None:
    chunks = [_chunk("c0", "d1"), _chunk("c1", "d2")]
    aggs = [DocAgg("a", "d1", 1), DocAgg("b", "d2", 1)]
    ref = build_reference(chunks, aggs, len(chunks), {1})
    assert list(ref.keys()) == ["total", "chunks", "doc_aggs"]
    assert ref["total"] == len(chunks)
    assert ref["chunks"] == [chunk_ref(c) for c in chunks]
    assert ref["doc_aggs"] == [{"doc_name": "b", "doc_id": "d2", "count": 1}]
    assert list(ref["doc_aggs"][0].keys()) == ["doc_name", "doc_id", "count"]


def test_build_reference_empty_cited_keeps_all() -> None:
    aggs = [DocAgg("a", "d1", 1), DocAgg("b", "d2", 1)]
    ref = build_reference([_chunk("c0", "d1")], aggs, 1, set())
    assert ref["doc_aggs"] == [
        {"doc_name": "a", "doc_id": "d1", "count": 1},
        {"doc_name": "b", "doc_id": "d2", "count": 1},
    ]


def test_build_reference_cited_out_of_range_keeps_all() -> None:
    aggs = [DocAgg("a", "d1", 1)]
    ref = build_reference([_chunk("c0", "d1")], aggs, 1, {5})
    assert ref["doc_aggs"] == [{"doc_name": "a", "doc_id": "d1", "count": 1}]
