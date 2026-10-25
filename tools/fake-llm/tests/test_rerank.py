"""Testy reranku: HTTP `POST /v1/rerank` i funkcja rerank_scores (K10 §5, C6)."""

import httpx
import pytest

from fake_llm.rerank import rerank_scores

MODEL = "fake-rerank"
CHAT_MODEL = "fake-chat"
UNKNOWN_MODEL = "nope"
HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_UNPROCESSABLE = 422
THREE_DOCS = 3


async def test_rerank_orders_by_relevance(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={
            "model": MODEL,
            "query": "umowa najmu lokalu",
            "documents": ["prognoza pogody", "umowa najmu", "Umowa najmu lokalu mieszkalnego"],
        },
    )
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["id"] == "fake-rerank"
    assert body["meta"] == {}
    assert body["results"] == [
        {"index": 2, "relevance_score": 1.0},
        {"index": 1, "relevance_score": pytest.approx(2 / THREE_DOCS)},
        {"index": 0, "relevance_score": 0.0},
    ]


async def test_rerank_ties_sorted_by_index(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": MODEL, "query": "a b", "documents": ["a", "b", "a b", "c"]},
    )
    assert response.status_code == HTTP_OK
    results = response.json()["results"]
    assert [result["index"] for result in results] == [2, 0, 1, 3]
    assert [result["relevance_score"] for result in results] == [1.0, 0.5, 0.5, 0.0]


async def test_rerank_top_n_truncates(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={
            "model": MODEL,
            "query": "a b",
            "documents": ["a", "b", "a b", "c"],
            "top_n": 2,
        },
    )
    assert response.status_code == HTTP_OK
    assert [result["index"] for result in response.json()["results"]] == [2, 0]


async def test_rerank_top_n_larger_than_documents(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={
            "model": MODEL,
            "query": "a b",
            "documents": ["a", "b", "a b", "c"],
            "top_n": 10,
        },
    )
    assert response.status_code == HTTP_OK
    results = response.json()["results"]
    assert [result["index"] for result in results] == [2, 0, 1, 3]
    assert [result["relevance_score"] for result in results] == [1.0, 0.5, 0.5, 0.0]


async def test_rerank_documents_as_objects(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": MODEL, "query": "a", "documents": [{"text": "a"}, {"text": "x"}]},
    )
    assert response.status_code == HTTP_OK
    assert response.json()["results"] == [
        {"index": 0, "relevance_score": 1.0},
        {"index": 1, "relevance_score": 0.0},
    ]


async def test_rerank_mixed_documents(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": MODEL, "query": "a", "documents": ["x", {"text": "a"}]},
    )
    assert response.status_code == HTTP_OK
    results = response.json()["results"]
    assert [result["index"] for result in results] == [1, 0]
    assert [result["relevance_score"] for result in results] == [1.0, 0.0]


async def test_rerank_empty_query_gives_zero_scores(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": MODEL, "query": "!!!", "documents": ["a"]},
    )
    assert response.status_code == HTTP_OK
    assert response.json()["results"] == [{"index": 0, "relevance_score": 0.0}]


async def test_rerank_scores_use_token_sets(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": MODEL, "query": "a a a", "documents": ["a"]},
    )
    assert response.status_code == HTTP_OK
    assert response.json()["results"][0]["relevance_score"] == 1.0


async def test_rerank_uses_polish_tokenization(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": MODEL, "query": "Zażółć", "documents": ["zazolc"]},
    )
    assert response.status_code == HTTP_OK
    assert response.json()["results"][0]["relevance_score"] == 1.0


async def test_rerank_unknown_model_not_found(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": UNKNOWN_MODEL, "query": "a", "documents": ["a"]},
    )
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json() == {
        "error": {
            "message": f"The model '{UNKNOWN_MODEL}' does not exist",
            "type": "invalid_request_error",
            "param": "model",
            "code": "model_not_found",
        }
    }


async def test_rerank_chat_model_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": CHAT_MODEL, "query": "a", "documents": ["a"]},
    )
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json()["error"]["code"] == "model_not_found"


async def test_rerank_top_n_zero_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/rerank",
        json={"model": MODEL, "query": "a", "documents": ["a"], "top_n": 0},
    )
    assert response.status_code == HTTP_UNPROCESSABLE


def test_rerank_scores_orders_ties_by_index() -> None:
    assert rerank_scores("a b", ["b", "a"]) == [(0, 0.5), (1, 0.5)]
