"""Testy present/dify: rekordy w kształcie złota (brief OD p. 1; openai_dify--11)."""

from app.api.ragflow.present.dify import dify_records
from app.domain.retrieval.types import RetrievalResult, RetrievedChunk


def chunk(*, metadata: dict[str, object] | None = None) -> RetrievedChunk:
    """Chunk z minimalnym zestawem pól; reszta jak w wyniku retrievalu M6."""
    return RetrievedChunk(
        chunk_id="c" * 16,
        content="Legenda o smoku wawelskim.",
        content_llm="Legenda o smoku wawelskim.",
        content_terms="legenda smok",
        document_id="d" * 32,
        document_name="ragflow_intro.txt",
        dataset_id="k" * 32,
        image_id="",
        important_keywords=[],
        questions=[],
        tag_kwd=[],
        positions=[[1, 2, 3, 4]],
        similarity=0.5849871404285715,
        vector_similarity=0.9,
        term_similarity=0.1,
        highlight=None,
        doc_type="",
        url=None,
        document_metadata=metadata,
    )


def test_record_without_document_metadata() -> None:
    """Dokument bez metadanych → metadata z samymi doc_id/document_id (złoto --11)."""
    body = dify_records(RetrievalResult(total=1, chunks=[chunk()], doc_aggs=[]))
    assert body == {
        "records": [
            {
                "content": "Legenda o smoku wawelskim.",
                "score": 0.5849871404285715,
                "title": "ragflow_intro.txt",
                "metadata": {"doc_id": "d" * 32, "document_id": "d" * 32},
            }
        ]
    }


def test_record_carries_document_metadata() -> None:
    """Metadane dokumentu dokładane przed doc_id/document_id (upstream :279-281)."""
    body = dify_records(
        RetrievalResult(total=1, chunks=[chunk(metadata={"author": "wd_rec_e2"})], doc_aggs=[])
    )
    assert body["records"][0]["metadata"] == {
        "author": "wd_rec_e2",
        "doc_id": "d" * 32,
        "document_id": "d" * 32,
    }


def test_empty_result() -> None:
    """Brak trafień (złoto --12) → pusta lista rekordów."""
    assert dify_records(RetrievalResult(total=0, chunks=[], doc_aggs=[])) == {"records": []}
