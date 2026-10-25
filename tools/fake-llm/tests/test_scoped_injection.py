"""Testy wstrzykiwania zawężonego do modelu (pole ``model`` w ciałach ``POST /v1/fake/*``) (C8, T6).

Z polem ``model`` reguła obowiązuje wyłącznie żądania o dokładnie tej nazwie (pełnej,
z aliasem) i jest trzymana osobno od stanu globalnego; wartość zerowa usuwa regułę.
Bez pola zachowanie globalne bez zmian (pilnują tego istniejące testy ``/v1/fake/*``).
"""

import asyncio
import time
from collections.abc import Iterator

import httpx
import pytest

from fake_llm import stats

HTTP_OK = 200
HTTP_TOO_MANY = 429
HTTP_BAD_GATEWAY = 502
HTTP_UNAVAILABLE = 503
DELAY_MS = 300
MIN_DELAYED_S = 0.3
FAST_LIMIT_S = 0.15
EMBED_MODEL = "fake-embed-1024"
OCR_MODEL = "fake-ocr"
CHAT_MODEL = "fake-chat"
SEP = "~"
PARALLEL = 3


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Zeruje liczniki, opóźnienia, reguły globalne i zawężone przed i po każdym teście."""
    stats.reset()
    stats.set_ocr_delay_ms(0)
    stats.set_embed_delay_ms(0)
    stats.set_embed_429(0, None)
    for route in stats.UPSTREAM_ROUTES:
        stats.set_upstream_error(route, 0, 500, None)
    stats.reset_scoped()
    yield
    stats.reset()
    stats.set_ocr_delay_ms(0)
    stats.set_embed_delay_ms(0)
    stats.set_embed_429(0, None)
    for route in stats.UPSTREAM_ROUTES:
        stats.set_upstream_error(route, 0, 500, None)
    stats.reset_scoped()


def _embed_body(model: str) -> dict[str, object]:
    return {"model": model, "input": "zdanie do osadzenia"}


def _chat_body(model: str) -> dict[str, object]:
    return {"model": model, "messages": [{"role": "user", "content": "pytanie"}]}


async def _embed_elapsed(client: httpx.AsyncClient, model: str) -> float:
    start = time.perf_counter()
    response = await client.post("/v1/embeddings", json=_embed_body(model))
    assert response.status_code == HTTP_OK
    return time.perf_counter() - start


async def _chat_elapsed(client: httpx.AsyncClient, model: str) -> float:
    start = time.perf_counter()
    response = await client.post("/v1/chat/completions", json=_chat_body(model))
    assert response.status_code == HTTP_OK
    return time.perf_counter() - start


# --- (b) embed-delay zawężone do modelu ---


async def test_embed_delay_scoped_delays_only_that_model(client: httpx.AsyncClient) -> None:
    """``embed-delay {"model": t1}`` opóźnia tylko ``t1``; ``t2`` i baza szybkie (C8)."""
    t1 = f"{EMBED_MODEL}{SEP}t1"
    t2 = f"{EMBED_MODEL}{SEP}t2"
    setup = await client.post("/v1/fake/embed-delay", json={"ms": DELAY_MS, "model": t1})
    assert setup.status_code == HTTP_OK
    state = (await client.get("/v1/fake/embed-delay")).json()
    assert state["ms"] == 0
    assert state["scoped"] == {t1: DELAY_MS}
    assert await _embed_elapsed(client, t1) >= MIN_DELAYED_S
    assert await _embed_elapsed(client, t2) < FAST_LIMIT_S
    assert await _embed_elapsed(client, EMBED_MODEL) < FAST_LIMIT_S


async def test_embed_delay_scoped_zero_removes_rule(client: httpx.AsyncClient) -> None:
    """``ms: 0`` z ``model`` usuwa regułę zawężoną (GET bez klucza ``scoped``)."""
    t1 = f"{EMBED_MODEL}{SEP}t1"
    await client.post("/v1/fake/embed-delay", json={"ms": DELAY_MS, "model": t1})
    await client.post("/v1/fake/embed-delay", json={"ms": 0, "model": t1})
    assert await _embed_elapsed(client, t1) < FAST_LIMIT_S
    assert "scoped" not in (await client.get("/v1/fake/embed-delay")).json()


# --- (b/c) ocr-delay zawężone do modelu ---


async def test_ocr_delay_scoped_delays_only_that_model(client: httpx.AsyncClient) -> None:
    """``ocr-delay {"model": fake-ocr~t1}`` opóźnia tylko ten alias, nie bazowy ``fake-ocr``."""
    t1 = f"{OCR_MODEL}{SEP}t1"
    await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS, "model": t1})
    state = (await client.get("/v1/fake/ocr-delay")).json()
    assert state["scoped"] == {t1: DELAY_MS}
    assert await _chat_elapsed(client, t1) >= MIN_DELAYED_S
    assert await _chat_elapsed(client, OCR_MODEL) < FAST_LIMIT_S


# --- (c) embed-429 zawężone do modelu ---


async def test_embed_429_scoped_rejects_only_that_model(client: httpx.AsyncClient) -> None:
    """``embed-429 {"every":1,"model":t1}`` odrzuca 429 tylko ``t1``; inne modele → 200 (C8)."""
    t1 = f"{EMBED_MODEL}{SEP}t1"
    t2 = f"{EMBED_MODEL}{SEP}t2"
    setup = await client.post(
        "/v1/fake/embed-429", json={"every": 1, "retry_after_s": None, "model": t1}
    )
    assert setup.status_code == HTTP_OK
    assert (await client.post("/v1/embeddings", json=_embed_body(t1))).status_code == HTTP_TOO_MANY
    assert (await client.post("/v1/embeddings", json=_embed_body(t2))).status_code == HTTP_OK
    assert (
        await client.post("/v1/embeddings", json=_embed_body(EMBED_MODEL))
    ).status_code == HTTP_OK


async def test_embed_429_scoped_zero_removes_rule(client: httpx.AsyncClient) -> None:
    """``every: 0`` z ``model`` usuwa regułę zawężoną 429."""
    t1 = f"{EMBED_MODEL}{SEP}t1"
    await client.post("/v1/fake/embed-429", json={"every": 1, "retry_after_s": None, "model": t1})
    await client.post("/v1/fake/embed-429", json={"every": 0, "retry_after_s": None, "model": t1})
    assert (await client.post("/v1/embeddings", json=_embed_body(t1))).status_code == HTTP_OK


# --- (c) upstream-error zawężone do modelu+trasy ---


async def test_upstream_error_scoped_embeddings(client: httpx.AsyncClient) -> None:
    """``upstream-error`` z ``model`` wstrzykuje 5xx tylko temu modelowi (C8)."""
    t1 = f"{EMBED_MODEL}{SEP}t1"
    await client.post(
        "/v1/fake/upstream-error",
        json={
            "route": "embeddings",
            "every": 1,
            "status": HTTP_BAD_GATEWAY,
            "times": None,
            "model": t1,
        },
    )
    assert (
        await client.post("/v1/embeddings", json=_embed_body(t1))
    ).status_code == HTTP_BAD_GATEWAY
    assert (
        await client.post("/v1/embeddings", json=_embed_body(EMBED_MODEL))
    ).status_code == HTTP_OK
    state = (await client.get("/v1/fake/upstream-error")).json()
    assert state["embeddings"]["every"] == 0
    assert state["scoped"][t1]["embeddings"] == {
        "every": 1,
        "status": HTTP_BAD_GATEWAY,
        "times_left": None,
    }


async def test_upstream_error_scoped_chat(client: httpx.AsyncClient) -> None:
    """``upstream-error`` zawężony do modelu czatu nie dotyczy innego modelu czatu."""
    t1 = f"{CHAT_MODEL}{SEP}t1"
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "chat", "every": 1, "status": HTTP_UNAVAILABLE, "times": None, "model": t1},
    )
    assert (
        await client.post("/v1/chat/completions", json=_chat_body(t1))
    ).status_code == HTTP_UNAVAILABLE
    assert (
        await client.post("/v1/chat/completions", json=_chat_body(CHAT_MODEL))
    ).status_code == HTTP_OK


# --- (e) stats/reset nie czyści reguł zawężonych ---


async def test_stats_reset_keeps_scoped_rules(client: httpx.AsyncClient) -> None:
    """``POST /v1/fake/stats/reset`` zeruje liczniki, ale nie usuwa reguł zawężonych."""
    t1 = f"{EMBED_MODEL}{SEP}t1"
    await client.post("/v1/fake/embed-delay", json={"ms": DELAY_MS, "model": t1})
    reset = await client.post("/v1/fake/stats/reset")
    assert reset.status_code == HTTP_OK
    state = (await client.get("/v1/fake/embed-delay")).json()
    assert state["scoped"] == {t1: DELAY_MS}
    assert await _embed_elapsed(client, t1) >= MIN_DELAYED_S


# --- (f) max_concurrent osobny dla aliasu ---


async def test_max_concurrent_is_separate_per_alias(client: httpx.AsyncClient) -> None:
    """``max_concurrent`` liczy się osobno dla aliasu — baza nie dostaje wpisu."""
    t1 = f"{EMBED_MODEL}{SEP}t1"
    await client.post("/v1/fake/embed-delay", json={"ms": DELAY_MS, "model": t1})
    responses = await asyncio.gather(
        *(client.post("/v1/embeddings", json=_embed_body(t1)) for _ in range(PARALLEL))
    )
    assert all(response.status_code == HTTP_OK for response in responses)
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["max_concurrent"][t1] == PARALLEL
    assert EMBED_MODEL not in payload["max_concurrent"]
