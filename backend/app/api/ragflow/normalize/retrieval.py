"""Normalizacja wejścia retrievalu (kontrakt E1-9a C4.1 v2): kroki 1-8 dosłownie."""

from collections.abc import Mapping
from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.normalize.common import to_bool
from app.api.ragflow.pagination import parse_page
from app.core.errors import Conflict
from app.domain.retrieval.metadata import meta_data_filter_to_condition, parse_metadata_condition
from app.services.retrieval import RetrievalQuery


def _dataset_ids(body: Mapping[str, Any], path_dataset_id: str | None) -> list[str]:
    """Krok 1: ścieżka podmienia body; brak/pusty → „is required.", nie-lista → „a list"."""
    dataset_ids: Any = [path_dataset_id] if path_dataset_id is not None else body.get("dataset_ids")
    if not dataset_ids:
        raise Conflict("`dataset_ids` is required.")
    if not isinstance(dataset_ids, list):
        raise Conflict("`dataset_ids` should be a list")
    return dataset_ids


def _document_ids(body: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Krok 3: alias doc_ids; None/[] → None; nie-lista → „`document_ids` should be a list"."""
    document_ids: Any = body["document_ids"] if "document_ids" in body else body.get("doc_ids")
    if document_ids is not None and not isinstance(document_ids, list):
        raise Conflict("`document_ids` should be a list")
    return tuple(document_ids) if document_ids else None


def _cross_languages(body: Mapping[str, Any]) -> tuple[str, ...]:
    """Krok 3: brak/None/[] → (); nie-lista → „`cross_languages` should be a list" (C3/DEC-155)."""
    value: Any = body.get("cross_languages")
    if value is None:
        return ()
    if not isinstance(value, list):
        raise Conflict("`cross_languages` should be a list")
    return tuple(str(item) for item in value)


def _page_params(body: Mapping[str, Any], *, max_size: int) -> tuple[int, int]:
    """Krok 3: page i page_size (alias size) przez parse_page; złe → domyślne 1 i 30."""
    raw: dict[str, str] = {}
    v_page = body.get("page")
    v_size = body["page_size"] if "page_size" in body else body.get("size")
    if v_page is not None:
        raw["page"] = str(v_page)
    if v_size is not None:
        raw["page_size"] = str(v_size)
    page = parse_page(raw, max_size=max_size)
    return page.page, page.page_size


def _number(body: Mapping[str, Any], key: str, default: float) -> float:
    """Krok 4: float(body.get(key, default)); błąd → „`key` should be a number"."""
    try:
        return float(body.get(key, default))
    except (TypeError, ValueError):
        raise Conflict(f"`{key}` should be a number") from None


def _top_k(body: Mapping[str, Any]) -> int:
    """Krok 5: knn_top_k ma pierwszeństwo nad top_k; int i > 0, nazwa parametru w komunikacie."""
    param = "knn_top_k" if "knn_top_k" in body else "top_k"
    try:
        top_k = int(body.get(param, 1024))
    except (TypeError, ValueError):
        raise Conflict(f"`{param}` should be an integer") from None
    if top_k <= 0:
        raise Conflict(f"`{param}` must be greater than 0")
    return top_k


def _rerank_candidates(body: Mapping[str, Any], page: int, page_size: int) -> int:
    """Krok 6: rerank_candidates_count — int, > 0 i >= page * page_size."""
    try:
        count = int(body.get("rerank_candidates_count", 64))
    except (TypeError, ValueError):
        raise Conflict("`rerank_candidates_count` should be an integer") from None
    if count <= 0:
        raise Conflict("`rerank_candidates_count` must be greater than 0")
    if count < page * page_size:
        raise Conflict(
            f"`rerank_candidates_count` must be at least `page` multiplied by `page_size` "
            f"({page * page_size})"
        )
    return count


def _highlight(body: Mapping[str, Any]) -> bool:
    """Krok 7: brak/None → False; bool → wprost; „true"/„false" → bool; inne → błąd."""
    value = body.get("highlight")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise Conflict("`highlight` should be a boolean")


def retrieval_query(
    body: Mapping[str, Any],
    profile: CompatProfile,
    *,
    max_size: int,
    path_dataset_id: str | None = None,
) -> RetrievalQuery:
    """Kroki 1-8 C4.1 v2: aliasy, komunikaty upstream dosłownie (Conflict, kod 102)."""
    dataset_ids = _dataset_ids(body, path_dataset_id)
    if "question" not in body:
        raise Conflict("`question` is required.")
    question = (
        body["question"].strip() if isinstance(body["question"], str) else str(body["question"])
    )
    document_ids = _document_ids(body)
    cross_languages = _cross_languages(body)
    page, page_size = _page_params(body, max_size=max_size)
    similarity_threshold = _number(body, "similarity_threshold", 0.2)
    vector_similarity_weight = _number(body, "vector_similarity_weight", 0.3)
    top_k = _top_k(body)
    rerank_candidates_count = _rerank_candidates(body, page, page_size)
    condition = body.get("metadata_condition")
    metadata_condition = (
        parse_metadata_condition(condition) if isinstance(condition, dict) and condition else None
    )
    # K11 §10f p. 5 (chunk_api.py:391): obecność klucza `metadata_condition` w ciele zeruje
    # `meta_data_filter`; `manual` zawęża tu, `auto`/`semi_auto` rozwiązuje usługa (model).
    meta_data_filter_spec: Mapping[str, Any] | None = None
    if "metadata_condition" not in body:
        meta_data_filter = body.get("meta_data_filter")
        if isinstance(meta_data_filter, Mapping):
            if meta_data_filter.get("method") in ("auto", "semi_auto"):
                meta_data_filter_spec = meta_data_filter
            else:
                metadata_condition = meta_data_filter_to_condition(meta_data_filter)
    return RetrievalQuery(
        question=question,
        dataset_ids=tuple(dataset_ids),
        document_ids=document_ids,
        page=page,
        page_size=page_size,
        similarity_threshold=similarity_threshold,
        vector_similarity_weight=vector_similarity_weight,
        top_k=top_k,
        rerank_candidates_count=rerank_candidates_count,
        rerank_model=body.get("rerank_id") or None,
        keyword=to_bool(body.get("keyword", False)),
        cross_languages=cross_languages,
        highlight=_highlight(body),
        metadata_condition=metadata_condition,
        meta_data_filter=meta_data_filter_spec,
    )
