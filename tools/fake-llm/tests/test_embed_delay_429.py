"""Testy opóźnienia embeddingów i wstrzykiwania 429 (C6, E5-H8b)."""

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from fake_llm import stats

FAKE_LLM_DIR = Path(__file__).resolve().parents[1]
HTTP_OK = 200
HTTP_TOO_MANY = 429
HTTP_UNPROCESSABLE = 422
EMBED_MODEL = "fake-embed-1024"
DELAY_MS = 200
MIN_DELAYED_S = 0.2
FAST_LIMIT_S = 0.15
REJECT_LIMIT_S = 0.25


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Zeruje liczniki, opóźnienia i stan embed-429 przed i po każdym teście (stan modułowy)."""
    stats.reset()
    stats.set_embed_delay_ms(0)
    stats.set_embed_429(0, None)
    yield
    stats.reset()
    stats.set_embed_delay_ms(0)
    stats.set_embed_429(0, None)


def _body(model: str = EMBED_MODEL) -> dict[str, object]:
    return {"model": model, "input": "zdanie do osadzenia"}


async def _elapsed(client: httpx.AsyncClient) -> float:
    """Czas odpowiedzi `POST /v1/embeddings` (200) w sekundach."""
    start = time.perf_counter()
    response = await client.post("/v1/embeddings", json=_body())
    assert response.status_code == HTTP_OK
    return time.perf_counter() - start


async def test_default_delay_is_zero(client: httpx.AsyncClient) -> None:
    """Bez ustawienia `GET /embed-delay` zwraca 0, a żądanie odpowiada szybko."""
    response = await client.get("/v1/fake/embed-delay")
    assert response.status_code == HTTP_OK
    assert response.json() == {"ms": 0}
    assert await _elapsed(client) < FAST_LIMIT_S


async def test_set_delay_echoes_and_request_is_delayed(client: httpx.AsyncClient) -> None:
    """`POST /embed-delay {"ms":200}` zwraca wartość i wydłuża odpowiedź embeddingu."""
    response = await client.post("/v1/fake/embed-delay", json={"ms": DELAY_MS})
    assert response.status_code == HTTP_OK
    assert response.json() == {"ms": DELAY_MS}
    assert (await client.get("/v1/fake/embed-delay")).json() == {"ms": DELAY_MS}
    assert await _elapsed(client) >= MIN_DELAYED_S


async def test_negative_delay_is_rejected(client: httpx.AsyncClient) -> None:
    """`ms < 0` → 422, stan opóźnienia się nie zmienia."""
    response = await client.post("/v1/fake/embed-delay", json={"ms": -1})
    assert response.status_code == HTTP_UNPROCESSABLE
    assert (await client.get("/v1/fake/embed-delay")).json() == {"ms": 0}


async def test_embed_429_every_second_with_retry_after(client: httpx.AsyncClient) -> None:
    """`every:2` odrzuca co drugie żądanie 429 z nagłówkiem `Retry-After`."""
    setup = await client.post("/v1/fake/embed-429", json={"every": 2, "retry_after_s": 3})
    assert setup.status_code == HTTP_OK
    assert setup.json() == {"every": 2, "retry_after_s": 3}
    assert (await client.get("/v1/fake/embed-429")).json() == {"every": 2, "retry_after_s": 3}

    first = await client.post("/v1/embeddings", json=_body())
    second = await client.post("/v1/embeddings", json=_body())
    third = await client.post("/v1/embeddings", json=_body())
    fourth = await client.post("/v1/embeddings", json=_body())

    assert first.status_code == HTTP_OK
    assert second.status_code == HTTP_TOO_MANY
    assert second.headers["Retry-After"] == "3"
    assert third.status_code == HTTP_OK
    assert fourth.status_code == HTTP_TOO_MANY
    assert second.json()["error"]["type"] == "rate_limit_error"


async def test_embed_429_null_retry_after_has_no_header(client: httpx.AsyncClient) -> None:
    """`retry_after_s: null` → 429 bez nagłówka `Retry-After`."""
    await client.post("/v1/fake/embed-429", json={"every": 1, "retry_after_s": None})
    response = await client.post("/v1/embeddings", json=_body())
    assert response.status_code == HTTP_TOO_MANY
    assert "Retry-After" not in response.headers


async def test_embed_429_every_one_always_rejects(client: httpx.AsyncClient) -> None:
    """`every:1` odrzuca każde żądanie embeddingu."""
    await client.post("/v1/fake/embed-429", json={"every": 1, "retry_after_s": None})
    for _ in range(2):
        assert (await client.post("/v1/embeddings", json=_body())).status_code == HTTP_TOO_MANY


async def test_embed_429_every_zero_disables(client: httpx.AsyncClient) -> None:
    """`every:0` wyłącza wstrzykiwanie 429."""
    await client.post("/v1/fake/embed-429", json={"every": 0, "retry_after_s": 3})
    assert (await client.post("/v1/embeddings", json=_body())).status_code == HTTP_OK


async def test_rejected_429_is_counted_in_stats(client: httpx.AsyncClient) -> None:
    """Odrzucone 429 jest liczone w `embeddings.rejected_429`; liczone są też udane żądania."""
    await client.post("/v1/fake/embed-429", json={"every": 2, "retry_after_s": None})
    for _ in range(4):
        await client.post("/v1/embeddings", json=_body())
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["embeddings"] == {"requests": 4, "rejected_429": 2}


async def test_delay_not_applied_to_rejected_429(client: httpx.AsyncClient) -> None:
    """Opóźnienie embed-delay nie dotyczy odrzuconego 429 (odpowiada od razu)."""
    await client.post("/v1/fake/embed-delay", json={"ms": 300})
    await client.post("/v1/fake/embed-429", json={"every": 1, "retry_after_s": None})
    start = time.perf_counter()
    response = await client.post("/v1/embeddings", json=_body())
    elapsed = time.perf_counter() - start
    assert response.status_code == HTTP_TOO_MANY
    assert elapsed < REJECT_LIMIT_S


def test_embed_delay_initialized_from_env() -> None:
    """`FAKE_EMBED_DELAY_MS` ustawia opóźnienie startowe przy imporcie modułu."""
    process = subprocess.run(
        [sys.executable, "-c", "from fake_llm import stats; print(stats.EMBED_DELAY_MS)"],
        cwd=FAKE_LLM_DIR,
        env={"FAKE_EMBED_DELAY_MS": "250"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == "250"
