"""Testy licznika maks. jednoczesnych żądań per model i resetu liczników (C6, E5-H8b)."""

import asyncio
from collections.abc import Iterator

import httpx
import pytest

from fake_llm import stats

HTTP_OK = 200
EMBED_MODEL = "fake-embed-1024"
OCR_MODEL = "fake-ocr"
CHAT_MODEL = "fake-chat"
PARALLEL = 4
DELAY_MS = 300


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Zeruje liczniki, opóźnienia i stan embed-429 przed i po każdym teście (stan modułowy)."""
    stats.reset()
    stats.set_ocr_delay_ms(0)
    stats.set_embed_delay_ms(0)
    stats.set_embed_429(0, None)
    yield
    stats.reset()
    stats.set_ocr_delay_ms(0)
    stats.set_embed_delay_ms(0)
    stats.set_embed_429(0, None)


def _embed_body() -> dict[str, object]:
    return {"model": EMBED_MODEL, "input": "zdanie do osadzenia"}


def _chat_body(model: str) -> dict[str, object]:
    return {"model": model, "messages": [{"role": "user", "content": "pytanie"}]}


async def test_embed_max_concurrent_counts_parallel_requests(client: httpx.AsyncClient) -> None:
    """N równoległych żądań embeddingu z opóźnieniem daje `max_concurrent` = N dla modelu."""
    await client.post("/v1/fake/embed-delay", json={"ms": DELAY_MS})
    responses = await asyncio.gather(
        *(client.post("/v1/embeddings", json=_embed_body()) for _ in range(PARALLEL))
    )
    assert all(response.status_code == HTTP_OK for response in responses)
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["max_concurrent"][EMBED_MODEL] == PARALLEL


async def test_ocr_max_concurrent_counts_parallel_requests(client: httpx.AsyncClient) -> None:
    """N równoległych żądań `fake-ocr` z opóźnieniem daje `max_concurrent` = N dla modelu."""
    await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS})
    responses = await asyncio.gather(
        *(client.post("/v1/chat/completions", json=_chat_body(OCR_MODEL)) for _ in range(PARALLEL))
    )
    assert all(response.status_code == HTTP_OK for response in responses)
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["max_concurrent"][OCR_MODEL] == PARALLEL


async def test_max_concurrent_is_separate_per_model(client: httpx.AsyncClient) -> None:
    """Licznik maks. współbieżności jest liczony osobno dla każdego modelu."""
    await client.post("/v1/embeddings", json=_embed_body())
    await client.post("/v1/chat/completions", json=_chat_body(CHAT_MODEL))
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["max_concurrent"][EMBED_MODEL] == 1
    assert payload["max_concurrent"][CHAT_MODEL] == 1


async def test_max_concurrent_not_exceeded_without_delay(client: httpx.AsyncClient) -> None:
    """Bez opóźnienia kolejne żądania są obsługiwane jedno po drugim — maks. współbieżności 1."""
    for _ in range(3):
        await client.post("/v1/embeddings", json=_embed_body())
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["max_concurrent"][EMBED_MODEL] == 1


async def test_stats_reset_zeroes_counters_not_settings(client: httpx.AsyncClient) -> None:
    """`POST /stats/reset` zeruje liczniki, ale nie opóźnienia ani ustawień embed-429."""
    await client.post("/v1/fake/embed-delay", json={"ms": DELAY_MS})
    await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS})
    await client.post("/v1/fake/embed-429", json={"every": 3, "retry_after_s": 2})
    await client.post("/v1/embeddings", json=_embed_body())
    await client.post("/v1/chat/completions", json=_chat_body(OCR_MODEL))
    await client.post("/v1/embeddings", json=_embed_body())

    response = await client.post("/v1/fake/stats/reset")
    assert response.status_code == HTTP_OK
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["chat_completions"] == {}
    assert payload["max_concurrent"] == {}
    assert payload["embeddings"] == {"requests": 0, "rejected_429": 0}
    # Ustawienia przetrwały reset (C6).
    assert (await client.get("/v1/fake/embed-delay")).json() == {"ms": DELAY_MS}
    assert (await client.get("/v1/fake/ocr-delay")).json() == {"ms": DELAY_MS}
    assert (await client.get("/v1/fake/embed-429")).json() == {"every": 3, "retry_after_s": 2}
