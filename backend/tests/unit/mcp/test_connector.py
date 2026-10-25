"""Testy ``app.mcp.client.ApiConnector`` (K17 §4) na atrapie HTTP (bez sieci)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest

from app.mcp.client import ApiConnector, _message_of

API_BASE = "http://api.test/api/v1"
API_KEY = "klucz-klienta"


def _api(request: httpx.Request) -> httpx.Response:
    """Atrapa API WD: koperty ``code``/``data`` jak trasy ragflow (K17 §4)."""
    path = request.url.path
    if path == "/api/v1/datasets" and request.url.params.get("id"):
        return httpx.Response(
            200, json={"code": 0, "data": [{"id": "ds1", "name": "A", "description": None}]}
        )
    if path == "/api/v1/datasets":
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [{"id": "ds1", "name": "A", "description": None}],
                "total_datasets": 1,
            },
        )
    if path == "/api/v1/datasets/ds1/documents":
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "docs": [
                        {"id": "doc1", "name": "f.txt", "type": "doc", "location": "f.txt"},
                        {"id": "doc2", "name": "g.txt", "type": "doc"},
                    ]
                },
            },
        )
    if path == "/api/v1/chats":
        return httpx.Response(
            200,
            json={"code": 0, "data": {"chats": [{"id": "c1", "name": "N", "description": "D"}]}},
        )
    if path == "/api/v1/retrieval":
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "chunks": [
                        {
                            "id": "ch1",
                            "content": "treść",
                            "dataset_id": "ds1",
                            "document_id": "doc1",
                            "document_keyword": "f.txt",
                        }
                    ],
                    "total": 1,
                },
            },
        )
    return httpx.Response(404, json={"code": 404, "message": "not found"})


@pytest.fixture
def connector() -> Iterator[ApiConnector]:
    """``ApiConnector`` z klientem na atrapie HTTP i przechwyconymi żądaniami."""
    conn = ApiConnector(API_BASE)
    transport = httpx.MockTransport(_api)
    conn._client = httpx.AsyncClient(transport=transport)
    yield conn


async def test_list_datasets_returns_json_lines(connector: ApiConnector) -> None:
    text = await connector.list_datasets(api_key=API_KEY)
    rows = [json.loads(line) for line in text.splitlines()]
    assert rows == [{"id": "ds1", "name": "A", "description": None}]


async def test_list_chats_unwraps_envelope(connector: ApiConnector) -> None:
    text = await connector.list_chats(api_key=API_KEY)
    assert json.loads(text) == {"id": "c1", "name": "N", "description": "D"}


async def test_retrieval_maps_chunks_and_metadata(connector: ApiConnector) -> None:
    blocks = await connector.retrieval(api_key=API_KEY, dataset_ids=["ds1"], question="q")
    body = json.loads(blocks[0].text)
    chunk = body["chunks"][0]
    assert chunk["dataset_name"] == "A"
    assert chunk["document_name"] == "f.txt"
    assert chunk["document_metadata"]["name"] == "f.txt"
    assert body["pagination"]["total_chunks"] == 1
    assert body["query_info"] == {
        "question": "q",
        "similarity_threshold": 0.2,
        "vector_weight": 0.3,
        "keyword_search": False,
        "dataset_count": 1,
    }


async def test_retrieval_without_dataset_ids_resolves_all(connector: ApiConnector) -> None:
    blocks = await connector.retrieval(api_key=API_KEY, dataset_ids=[], question="q")
    assert "treść" in blocks[0].text


async def test_unauthorized_key_raises_with_marker() -> None:
    conn = ApiConnector(API_BASE)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401, json={"code": 401, "message": "<Unauthorized '401: Unauthorized'>"}
        )
    )
    conn._client = httpx.AsyncClient(transport=transport)
    with pytest.raises(Exception, match="Unauthorized"):
        await conn.list_datasets(api_key="zly")


def _connector_returning(response: httpx.Response) -> ApiConnector:
    """``ApiConnector``, którego każde wywołanie API zwraca ``response``."""
    conn = ApiConnector(API_BASE)
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
    return conn


async def test_non_ok_status_uses_api_message() -> None:
    """Nie-200 → wyjątek z komunikatem ``message`` API (K17 §4)."""
    conn = _connector_returning(httpx.Response(500, json={"code": 500, "message": "boom"}))
    with pytest.raises(Exception, match="boom"):
        await conn.list_chats(api_key=API_KEY)


async def test_code_nonzero_uses_api_message() -> None:
    """``code != 0`` przy HTTP 200 → wyjątek z komunikatem API."""
    conn = _connector_returning(httpx.Response(200, json={"code": 102, "message": "zły kod"}))
    with pytest.raises(Exception, match="zły kod"):
        await conn.list_datasets(api_key=API_KEY)


async def test_retrieval_code_nonzero_raises() -> None:
    """``code != 0`` na ``POST /retrieval`` → wyjątek (bez budowania odpowiedzi)."""
    conn = _connector_returning(httpx.Response(200, json={"code": 102, "message": "no dataset"}))
    with pytest.raises(Exception, match="no dataset"):
        await conn.retrieval(api_key=API_KEY, dataset_ids=["ds1"], question="q")


async def test_retrieval_without_any_dataset_raises() -> None:
    """Brak dostępnych datasetów przy pustym ``dataset_ids`` → komunikat K17 §4."""
    conn = _connector_returning(httpx.Response(200, json={"code": 0, "data": []}))
    with pytest.raises(Exception, match="No accessible datasets found"):
        await conn.retrieval(api_key=API_KEY, dataset_ids=[], question="q")


async def test_metadata_failures_degrade_gracefully() -> None:
    """Gdy API metadanych zawiedzie, chunk dostaje ``dataset_name`` = ``Unknown`` (bez wyjątku)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/retrieval":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"chunks": [{"id": "ch1", "dataset_id": "ds1"}], "total": 1},
                },
            )
        return httpx.Response(500, json={"code": 500, "message": "meta down"})

    conn = ApiConnector(API_BASE)
    conn._client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    blocks = await conn.retrieval(api_key=API_KEY, dataset_ids=["ds1"], question="q")
    chunk = json.loads(blocks[0].text)["chunks"][0]
    assert chunk["dataset_name"] == "Unknown"
    assert "document_metadata" not in chunk


def test_message_of_tolerates_non_json() -> None:
    """Ciało nie-JSON → ``None`` (bez wyjątku z ``response.json``)."""
    response = httpx.Response(500, text="<html>")
    assert _message_of(response) is None


def test_message_of_ignores_body_without_message() -> None:
    """JSON bez ``message`` albo nie-dict → ``None``."""
    assert _message_of(httpx.Response(200, json={"code": 0})) is None
    assert _message_of(httpx.Response(200, json=[1, 2])) is None
