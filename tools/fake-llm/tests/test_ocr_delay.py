"""Testy sterowalnego opóźnienia `fake-ocr` i resetu liczników (C6, E5-H8a)."""

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
HTTP_UNPROCESSABLE = 422
OCR_MODEL = "fake-ocr"
OTHER_MODEL = "fake-chat"
DELAY_MS = 300
MIN_DELAYED_S = 0.3
FAST_LIMIT_S = 0.25


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Zeruje liczniki i opóźnienie przed i po każdym teście (stan modułowy jest wspólny)."""
    stats.reset()
    stats.set_ocr_delay_ms(0)
    yield
    stats.reset()
    stats.set_ocr_delay_ms(0)


def _body(model: str, stream: bool = False) -> dict[str, object]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "pytanie"}],
        "stream": stream,
    }


async def _elapsed(client: httpx.AsyncClient, model: str, stream: bool = False) -> float:
    """Czas odpowiedzi `POST /v1/chat/completions` w sekundach."""
    start = time.perf_counter()
    response = await client.post("/v1/chat/completions", json=_body(model, stream))
    assert response.status_code == HTTP_OK
    return time.perf_counter() - start


async def test_default_delay_is_zero(client: httpx.AsyncClient) -> None:
    """Bez ustawienia opóźnienia `GET /ocr-delay` zwraca 0, a `fake-ocr` odpowiada szybko."""
    response = await client.get("/v1/fake/ocr-delay")
    assert response.status_code == HTTP_OK
    assert response.json() == {"ms": 0}
    assert await _elapsed(client, OCR_MODEL) < FAST_LIMIT_S


async def test_set_delay_echoes_and_get_returns_it(client: httpx.AsyncClient) -> None:
    """`POST /ocr-delay` zwraca ustawioną wartość, `GET` ją potwierdza."""
    response = await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS})
    assert response.status_code == HTTP_OK
    assert response.json() == {"ms": DELAY_MS}
    again = await client.get("/v1/fake/ocr-delay")
    assert again.json() == {"ms": DELAY_MS}


async def test_fake_ocr_request_is_delayed(client: httpx.AsyncClient) -> None:
    """Po ustawieniu 300 ms żądanie `fake-ocr` trwa co najmniej 0,3 s."""
    await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS})
    assert await _elapsed(client, OCR_MODEL) >= MIN_DELAYED_S


async def test_fake_ocr_stream_is_delayed(client: httpx.AsyncClient) -> None:
    """Opóźnienie obejmuje też żądanie strumieniowe (C6)."""
    await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS})
    assert await _elapsed(client, OCR_MODEL, stream=True) >= MIN_DELAYED_S


async def test_other_model_is_not_delayed(client: httpx.AsyncClient) -> None:
    """Ustawione opóźnienie nie dotyczy innego modelu (`fake-chat`)."""
    await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS})
    assert await _elapsed(client, OTHER_MODEL) < FAST_LIMIT_S


async def test_negative_delay_is_rejected(client: httpx.AsyncClient) -> None:
    """`ms < 0` → 422, a stan opóźnienia się nie zmienia."""
    response = await client.post("/v1/fake/ocr-delay", json={"ms": -1})
    assert response.status_code == HTTP_UNPROCESSABLE
    current = await client.get("/v1/fake/ocr-delay")
    assert current.json() == {"ms": 0}


async def test_stats_reset_zeroes_counters_not_delay(client: httpx.AsyncClient) -> None:
    """`POST /stats/reset` zeruje liczniki, ale nie opóźnienie."""
    await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS})
    await client.post("/v1/chat/completions", json=_body(OCR_MODEL))
    assert (await client.get("/v1/fake/stats")).json()["chat_completions"]
    response = await client.post("/v1/fake/stats/reset")
    assert response.status_code == HTTP_OK
    assert response.json()["chat_completions"] == {}
    stats_after = (await client.get("/v1/fake/stats")).json()
    assert stats_after["chat_completions"] == {}
    assert stats_after["embeddings"] == {"requests": 0, "rejected_429": 0}
    assert (await client.get("/v1/fake/ocr-delay")).json() == {"ms": DELAY_MS}


def test_delay_initialized_from_env() -> None:
    """`FAKE_OCR_DELAY_MS` ustawia opóźnienie startowe przy imporcie modułu."""
    process = subprocess.run(
        [sys.executable, "-c", "from fake_llm import stats; print(stats.OCR_DELAY_MS)"],
        cwd=FAKE_LLM_DIR,
        env={"FAKE_OCR_DELAY_MS": "250"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == "250"
