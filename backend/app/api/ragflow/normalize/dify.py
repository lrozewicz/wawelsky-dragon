"""Normalizacja żądań ``/dify/retrieval`` (brief OD p. 1; port ``_read_retrieval_request``).

POST czyta ciało JSON, GET — parametry zapytania (upstream ``dify_retrieval_api.py:34-91``);
oba warianty dają ten sam ``DifyQuery``. Moduł czysty: bez I/O.

Komunikaty błędów dosłownie z upstreamu (:215-222, :236-249) — łącznie z końcowym ``"; "``.
"""

from collections.abc import Mapping
from typing import Any

from app.core.errors import ValidationFailed
from app.domain.retrieval.metadata import MetadataCondition, parse_metadata_condition
from app.services.dify import DifyQuery

# Domyślne wartości ``retrieval_setting`` (upstream :109 ``top_k``, :106 ``score_threshold``).
DEFAULT_TOP_K = 1024
DEFAULT_SCORE_THRESHOLD = 0.0

MSG_MISSING = "required arguments are missing: {missing}; "
MSG_MALFORMED = "invalid or malformed arguments: {detail}; "


def _number(setting: Mapping[str, Any], key: str, default: int | float) -> int | float:
    """``setting[key]`` jako liczba; brak klucza → ``default`` (``_parse_retrieval_options``).

    Wyjątek ``TypeError``/``ValueError`` zamieniamy na ``ValidationFailed`` o tym samym
    komunikacie co upstream (:113).
    """
    value = setting.get(key, default)
    try:
        return int(value) if isinstance(default, int) else float(value)
    except (TypeError, ValueError):
        raise ValidationFailed(
            MSG_MALFORMED.format(detail="top_k must be integer and score_threshold must be numeric")
        ) from None


def _options(setting: object) -> tuple[int, float]:
    """``retrieval_setting`` → (top_k, score_threshold); nie-obiekt → ``ValidationFailed``."""
    if setting is None:
        setting = {}
    if not isinstance(setting, Mapping):
        raise ValidationFailed(MSG_MALFORMED.format(detail="retrieval_setting must be an object"))
    top_k = _number(setting, "top_k", DEFAULT_TOP_K)
    threshold = _number(setting, "score_threshold", DEFAULT_SCORE_THRESHOLD)
    return int(top_k), float(threshold)


def _condition(raw: object) -> MetadataCondition | None:
    """``metadata_condition`` → ``MetadataCondition``; puste → None (upstream ``meta_filter``)."""
    if not raw:
        return None
    if not isinstance(raw, Mapping):
        raise ValidationFailed(MSG_MALFORMED.format(detail="metadata_condition must be an object"))
    return parse_metadata_condition(raw)


def parse_dify_body(body: Mapping[str, object]) -> DifyQuery:
    """Ciało POST (upstream :70-91): pola najwyższego poziomu + ``retrieval_setting``."""
    raw_id = body.get("knowledge_id")
    raw_query = body.get("query")
    return build_query(
        raw_id if isinstance(raw_id, str) else "",
        raw_query if isinstance(raw_query, str) else "",
        body.get("retrieval_setting"),
        body.get("metadata_condition"),
    )


def parse_dify_query(params: Mapping[str, str]) -> DifyQuery:
    """Parametry GET (upstream :44-67): ``top_k``/``score_threshold`` tekstem z query.

    Obecność parametru sprawdzamy jak upstream (``not in (None, "")``), nie prawdziwością
    wartości: ``top_k=0`` to podana wartość, a nie brak parametru (FIXA p. 4, DEC-037).
    """
    setting: dict[str, Any] = {}
    if params.get("top_k") not in (None, ""):
        setting["top_k"] = params["top_k"]
    if params.get("score_threshold") not in (None, ""):
        setting["score_threshold"] = params["score_threshold"]
    return build_query(
        params.get("knowledge_id") or "",
        params.get("query") or "",
        setting,
        None,
    )


def build_query(
    knowledge_id: str, query: str, setting: object, metadata: object = None
) -> DifyQuery:
    """Wspólna dalsza część obu wariantów: wymagane pola → opcje → warunek metadanych."""
    fields = (("knowledge_id", knowledge_id), ("query", query))
    missing = [name for name, value in fields if not value]
    if missing:
        raise ValidationFailed(MSG_MISSING.format(missing=",".join(missing)))
    top_k, threshold = _options(setting)
    return DifyQuery(
        knowledge_id=knowledge_id,
        query=query,
        top_k=top_k,
        score_threshold=threshold,
        metadata_condition=_condition(metadata),
    )
