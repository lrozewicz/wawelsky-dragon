"""Modele OpenAPI retrievalu (odpowiedzi C3, żądanie) — kształty v0.27.2.

Pola ``RetrievalRequest`` = klucze czytane ręcznie przez ``normalize/retrieval.py``;
typy kanoniczne i domyślne wg briefu T2 (aliasy jako osobne pola).
"""

from typing import Any

from pydantic import Field

from app.api.ragflow.schemas.common import DocAgg, RequestModel, ResponseModel


class RetrievalChunk(ResponseModel):
    """Element data.chunks — 16 kluczy złota retrieval--06; highlight gdy niepusty (C3)."""

    content: str
    content_ltks: str
    dataset_id: str
    doc_type_kwd: str
    document_id: str
    document_keyword: str
    id: str
    image_id: str
    important_keywords: list[str]
    mom_id: str
    positions: list[list[int]]
    row_id: None
    similarity: float
    tag_kwd: list[str]
    term_similarity: float
    vector_similarity: float
    highlight: str | None = None


class RetrievalResult(ResponseModel):
    """data operacji retrievalu: chunks, doc_aggs, total (C3 p. 4)."""

    chunks: list[RetrievalChunk]
    doc_aggs: list[DocAgg]
    total: int


class RetrievalRequest(RequestModel):
    """Ciało operacji retrievalu (normalize.retrieval.retrieval_query; K6 §3)."""

    question: str
    dataset_ids: list[str]
    document_ids: list[str] | None = None
    doc_ids: list[str] | None = Field(default=None, description="alias document_ids")
    page: int = 1
    page_size: int = 30
    size: int | None = Field(default=None, description="alias page_size")
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3
    top_k: int = 1024
    knn_top_k: int = Field(default=1024, description="alias top_k")
    rerank_candidates_count: int = 64
    rerank_id: str | None = None
    keyword: bool = False
    cross_languages: list[str] | None = Field(
        default=None,
        description=(
            "Języki docelowe przepisania pytania przed wyszukiwaniem; brak/puste → bez przepisania"
        ),
    )
    highlight: bool = False
    metadata_condition: dict[str, Any] | None = None
    meta_data_filter: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Rodzaj zawężenia po metadanych: `manual` (warunki wprost) albo `auto`/`semi_auto` "
            "(warunki generuje model); obecność `metadata_condition` w ciele zeruje ten filtr"
        ),
    )


REQUEST_MODELS: tuple[type[RequestModel], ...] = (RetrievalRequest,)
