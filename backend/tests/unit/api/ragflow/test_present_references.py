"""Testy present/references: kształty odpowiedzi retrievalu (kontrakt E1-9a C4.2)."""

import json
from pathlib import Path

from app.api.ragflow.present.references import chunk_retrieval, retrieval_result
from app.domain.retrieval.types import DocAgg, RetrievalResult, RetrievedChunk

PROFILE = "ragflow_0_27"

GOLDEN = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.27.2"

CHUNK_KEYS = 16  # klucze złota retrieval--06 → body.data.chunks.0 (bez highlight)


def _chunk(**overrides: object) -> RetrievedChunk:
    """Pełny RetrievedChunk do testów prezentertów (pola wg kontraktu M1)."""
    values: dict[str, object] = dict(
        chunk_id="c" * 32,
        content="Treść fragmentu.",
        content_llm="Treść fragmentu.",
        content_terms="tre ś ć fragmentu",
        document_id="d" * 32,
        document_name="ragflow_intro.txt",
        dataset_id="s" * 32,
        image_id="",
        important_keywords=["smok"],
        questions=["Co wie o smoku?"],
        tag_kwd=[],
        positions=[[1, 0, 0, 0, 0]],
        similarity=0.75,
        vector_similarity=0.8,
        term_similarity=0.7,
        highlight=None,
        doc_type="",
        url=None,
        document_metadata=None,
    )
    values.update(overrides)
    return RetrievedChunk(**values)  # type: ignore[arg-type]


def _golden_chunk_keys() -> list[str]:
    """Klucze złota retrieval--06 → body.data.chunks.0."""
    document = json.loads((GOLDEN / "retrieval" / "retrieval--06.json").read_text(encoding="utf-8"))
    golden_chunk: dict[str, object] = document["body"]["data"]["chunks"][0]
    return list(golden_chunk.keys())


def test_chunk_retrieval_keys_match_golden() -> None:
    """Wymaganie 1 briefu: sorted kluczy == sorted złota (c z highlight=None)."""
    golden_keys = _golden_chunk_keys()
    assert sorted(chunk_retrieval(_chunk(), PROFILE).keys()) == sorted(golden_keys)
    assert len(golden_keys) == CHUNK_KEYS


def test_chunk_retrieval_field_mapping() -> None:
    """Mapowanie pól C4.2 dosłownie: content_ltks←content_terms itd.; bez pól zakazanych."""
    data = chunk_retrieval(_chunk(), PROFILE)
    assert data == {
        "content": "Treść fragmentu.",
        "content_ltks": "tre ś ć fragmentu",
        "dataset_id": "s" * 32,
        "doc_type_kwd": "",
        "document_id": "d" * 32,
        "document_keyword": "ragflow_intro.txt",
        "id": "c" * 32,
        "image_id": "",
        "important_keywords": ["smok"],
        "mom_id": "",
        "positions": [[1, 0, 0, 0, 0]],
        "row_id": None,
        "similarity": 0.75,
        "tag_kwd": [],
        "term_similarity": 0.7,
        "vector_similarity": 0.8,
    }


def test_chunk_retrieval_highlight_only_when_present() -> None:
    """highlight dodany tylko gdy c.highlight is not None (C4.2)."""
    data = chunk_retrieval(_chunk(highlight="Fragment <em>smok</em>."), PROFILE)
    assert sorted(data.keys()) == sorted(
        [
            "content",
            "content_ltks",
            "dataset_id",
            "doc_type_kwd",
            "document_id",
            "document_keyword",
            "highlight",
            "id",
            "image_id",
            "important_keywords",
            "mom_id",
            "positions",
            "row_id",
            "similarity",
            "tag_kwd",
            "term_similarity",
            "vector_similarity",
        ]
    )
    assert data["highlight"] == "Fragment <em>smok</em>."


def test_retrieval_result_shape() -> None:
    """retrieval_result: chunks, doc_aggs [{count, doc_id, doc_name}], total (C4.2)."""
    chunk = _chunk()
    result = RetrievalResult(
        total=3,
        chunks=[chunk],
        doc_aggs=[DocAgg(doc_name="ragflow_intro.txt", doc_id="d" * 32, count=3)],
    )
    assert retrieval_result(result, PROFILE) == {
        "chunks": [chunk_retrieval(chunk, PROFILE)],
        "doc_aggs": [{"count": 3, "doc_id": "d" * 32, "doc_name": "ragflow_intro.txt"}],
        "total": 3,
    }


def test_retrieval_result_empty_always_lists() -> None:
    """Pusty wynik: chunks i doc_aggs listami (Q19), total 0 (przykład briefu)."""
    assert retrieval_result(RetrievalResult(total=0, chunks=[], doc_aggs=[]), PROFILE) == {
        "chunks": [],
        "doc_aggs": [],
        "total": 0,
    }
