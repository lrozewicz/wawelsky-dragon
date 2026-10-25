"""Prezentery retrievalu (kontrakt E1-9a C4.2): kształt odpowiedzi /retrieval v0.27.2.

Także ChunkReference wiadomości sesji v0.24 (CONTRACT E2-2b C3) — wspólny kształt referencji.
"""

from collections.abc import Mapping
from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.domain.retrieval.types import RetrievalResult, RetrievedChunk


def chunk_reference_v024(chunk: Mapping[str, Any]) -> dict[str, Any]:
    """ChunkReference wiadomości sesji v0.24 (C3): 7 kluczy, fallbacki na stare nazwy.

    Port ``list_session`` v0.24 (``git show v0.24.0:api/apps/sdk/session.py``).
    """
    return {
        "id": chunk.get("chunk_id", chunk.get("id")),
        "content": chunk.get("content_with_weight", chunk.get("content")),
        "document_id": chunk.get("doc_id", chunk.get("document_id")),
        "document_name": chunk.get("docnm_kwd", chunk.get("document_name")),
        "dataset_id": chunk.get("kb_id", chunk.get("dataset_id")),
        "image_id": chunk.get("image_id", chunk.get("img_id")),
        "positions": chunk.get("positions", chunk.get("position_int")),
    }


def chunk_retrieval(c: RetrievedChunk, profile: CompatProfile) -> dict[str, Any]:
    """16 kluczy złota retrieval--06 → body.data.chunks[i]; „highlight" tylko gdy nie-None.

    Profil 0.24.0: 14 kluczy złota — bez ``row_id`` i ``tag_kwd`` (klucze v0.27).
    NIE emituje questions, url, document_metadata, content_llm (C4.2).
    """
    data: dict[str, Any] = {
        "content": c.content,
        "content_ltks": c.content_terms,
        "dataset_id": c.dataset_id,
        "doc_type_kwd": c.doc_type,
        "document_id": c.document_id,
        "document_keyword": c.document_name,
        "id": c.chunk_id,
        "image_id": c.image_id,
        "important_keywords": c.important_keywords,
        "mom_id": "",
        "positions": c.positions,
        "row_id": None,
        "similarity": c.similarity,
        "tag_kwd": c.tag_kwd,
        "term_similarity": c.term_similarity,
        "vector_similarity": c.vector_similarity,
    }
    if profile == "ragflow_0_24":
        del data["row_id"]
        del data["tag_kwd"]
    if c.highlight is not None:
        data["highlight"] = c.highlight
    return data


def retrieval_result(r: RetrievalResult, profile: CompatProfile) -> dict[str, Any]:
    """{chunks, doc_aggs, total} — doc_aggs zawsze listą, nawet pustą (Q19)."""
    return {
        "chunks": [chunk_retrieval(c, profile) for c in r.chunks],
        "doc_aggs": [
            {"count": a.count, "doc_id": a.doc_id, "doc_name": a.doc_name} for a in r.doc_aggs
        ],
        "total": r.total,
    }
