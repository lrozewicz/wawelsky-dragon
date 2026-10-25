"""Prezentacja odpowiedzi ``/dify/retrieval`` (brief OD p. 1; upstream :282-290).

Kształt dosłownie z upstreamu: surowe ``{"records": [...]}`` bez koperty ``code`` (Dify
czyta własny format), rekord = ``content``, ``score``, ``title``, ``metadata``.
Profil ``ragflow_0_24`` (CONTRACT E2-2b C0 p. 8) nie dokłada ``metadata.document_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.domain.retrieval.types import RetrievalResult, RetrievedChunk

if TYPE_CHECKING:
    from app.api.ragflow.compat import CompatProfile


def _record(chunk: RetrievedChunk, profile: CompatProfile) -> dict[str, Any]:
    """Rekord Dify: ``metadata`` = metadane dokumentu + ``doc_id``/``document_id`` (:279-281)."""
    metadata: dict[str, Any] = dict(chunk.document_metadata or {})
    metadata["doc_id"] = chunk.document_id
    # Dify oczekuje ``metadata.document_id`` (upstream komentarz w :280); v0.24 ma tylko ``doc_id``
    # (złoto ``dify__retrieval/openai_dify--11.json``).
    if profile != "ragflow_0_24":
        metadata["document_id"] = chunk.document_id
    return {
        "content": chunk.content,
        "score": chunk.similarity,
        "title": chunk.document_name,
        "metadata": metadata,
    }


def dify_records(
    result: RetrievalResult, profile: CompatProfile = "ragflow_0_27"
) -> dict[str, Any]:
    """Ciało HTTP 200 trasy ``/dify/retrieval``: ``{"records": [...]}``."""
    return {"records": [_record(chunk, profile) for chunk in result.chunks]}
