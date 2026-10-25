"""Testy normalize/dify: ciało POST i parametry GET (brief OD p. 1)."""

import pytest

from app.api.ragflow.normalize.dify import parse_dify_body, parse_dify_query
from app.core.errors import ValidationFailed
from app.domain.retrieval.metadata import MetadataCondition, MetadataFilter
from app.services.dify import DifyQuery


def test_body_with_retrieval_setting() -> None:
    """Przykład ze scenariusza złota (openai_dify--11): ciało → DifyQuery bez warunku."""
    assert parse_dify_body(
        {
            "knowledge_id": "kb1",
            "query": "smokwawelski",
            "retrieval_setting": {"top_k": 10, "score_threshold": 0.0},
        }
    ) == DifyQuery(knowledge_id="kb1", query="smokwawelski", top_k=10, score_threshold=0.0)


def test_body_defaults() -> None:
    """Brak retrieval_setting → top_k 1024 i score_threshold 0.0 (upstream domyślne)."""
    assert parse_dify_body({"knowledge_id": "kb1", "query": "q"}) == DifyQuery(
        knowledge_id="kb1", query="q", top_k=1024, score_threshold=0.0
    )


def test_body_metadata_condition() -> None:
    """metadata_condition jak w złocie openai_dify--12 (operator „is” → „=”)."""
    query = parse_dify_body(
        {
            "knowledge_id": "kb1",
            "query": "q",
            "metadata_condition": {
                "logic": "and",
                "conditions": [
                    {"name": "author", "comparison_operator": "is", "value": "wd_rec_e2"}
                ],
            },
        }
    )
    assert query.metadata_condition == MetadataCondition(
        logic="and", conditions=(MetadataFilter(name="author", op="=", value="wd_rec_e2"),)
    )


def test_body_missing_fields() -> None:
    """Brak knowledge_id i query → komunikat upstreamu (posortowane nazwy, końcowe „; ”)."""
    with pytest.raises(ValidationFailed) as exc_info:
        parse_dify_body({})
    assert exc_info.value.message == "required arguments are missing: knowledge_id,query; "


def test_body_missing_query_only() -> None:
    """Pusty query → tylko query w komunikacie."""
    with pytest.raises(ValidationFailed) as exc_info:
        parse_dify_body({"knowledge_id": "kb1"})
    assert exc_info.value.message == "required arguments are missing: query; "


def test_body_top_k_not_a_number() -> None:
    """top_k tekstem nieparsowalnym → komunikat upstreamu (:113)."""
    with pytest.raises(ValidationFailed) as exc_info:
        parse_dify_body({"knowledge_id": "kb1", "query": "q", "retrieval_setting": {"top_k": "x"}})
    assert exc_info.value.message == (
        "invalid or malformed arguments: top_k must be integer and score_threshold must"
        " be numeric; "
    )


def test_body_retrieval_setting_not_an_object() -> None:
    """retrieval_setting listą → „must be an object”."""
    with pytest.raises(ValidationFailed) as exc_info:
        parse_dify_body({"knowledge_id": "kb1", "query": "q", "retrieval_setting": []})
    assert exc_info.value.message == (
        "invalid or malformed arguments: retrieval_setting must be an object; "
    )


def test_query_params() -> None:
    """GET (openai_dify--14): parametry tekstem → ten sam DifyQuery co POST."""
    assert parse_dify_query(
        {"knowledge_id": "kb1", "query": "smokwawelski", "top_k": "10", "score_threshold": "0.0"}
    ) == DifyQuery(knowledge_id="kb1", query="smokwawelski", top_k=10, score_threshold=0.0)


def test_query_params_defaults() -> None:
    """GET bez top_k/score_threshold → domyślne upstreamu."""
    assert parse_dify_query({"knowledge_id": "kb1", "query": "q"}) == DifyQuery(
        knowledge_id="kb1", query="q", top_k=1024, score_threshold=0.0
    )


def test_query_params_zero_is_a_value_not_absence() -> None:
    """``top_k=0``/``score_threshold=0`` to podane wartości, nie brak parametru (FIXA p. 4).

    Upstream sprawdza obecność parametru (``top_k not in (None, "")``,
    dify_retrieval_api.py:44-67) — check prawdziwości podmieniałby 0 na domyślne 1024/0.0.
    """
    assert parse_dify_query(
        {"knowledge_id": "kb1", "query": "q", "top_k": "0", "score_threshold": "0"}
    ) == DifyQuery(knowledge_id="kb1", query="q", top_k=0, score_threshold=0.0)


def test_query_params_empty_string_is_absence() -> None:
    """Pusty parametr (``?top_k=``) → brak klucza → domyślne 1024 (upstream ``""``)."""
    assert parse_dify_query(
        {"knowledge_id": "kb1", "query": "q", "top_k": "", "score_threshold": ""}
    ) == DifyQuery(knowledge_id="kb1", query="q", top_k=1024, score_threshold=0.0)


def test_query_params_missing() -> None:
    """GET bez knowledge_id → komunikat jak w POST."""
    with pytest.raises(ValidationFailed) as exc_info:
        parse_dify_query({"query": "q"})
    assert exc_info.value.message == "required arguments are missing: knowledge_id; "
