"""Testy wstrzykiwania błędów 5xx (`GET`/`POST /v1/fake/upstream-error`) (C7, E5-H8e)."""

import time
from collections.abc import Iterator
from typing import Any

import httpx
import openai
import pytest

from fake_llm import stats

HTTP_OK = 200
HTTP_TOO_MANY = 429
HTTP_UNPROCESSABLE = 422
HTTP_INTERNAL = 500
HTTP_BAD_GATEWAY = 502
HTTP_UNAVAILABLE = 503
HTTP_GATEWAY_TIMEOUT = 504
EMBED_MODEL = "fake-embed-1024"
CHAT_MODEL = "fake-chat"
VISION_MODEL = "fake-vision"
DELAY_MS = 300
FAST_LIMIT_S = 0.15
EMPTY_STATE = {"every": 0, "status": 500, "times_left": None}


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Zeruje liczniki, opóźnienia i ustawienia 429/upstream-error przed i po każdym teście."""
    stats.reset()
    stats.set_embed_delay_ms(0)
    stats.set_ocr_delay_ms(0)
    stats.set_embed_429(0, None)
    for route in stats.UPSTREAM_ROUTES:
        stats.set_upstream_error(route, 0, 500, None)
    yield
    stats.reset()
    stats.set_embed_delay_ms(0)
    stats.set_ocr_delay_ms(0)
    stats.set_embed_429(0, None)
    for route in stats.UPSTREAM_ROUTES:
        stats.set_upstream_error(route, 0, 500, None)


def _embed_body() -> dict[str, object]:
    return {"model": EMBED_MODEL, "input": "zdanie do osadzenia"}


def _chat_body() -> dict[str, object]:
    return {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "pytanie"}]}


def _vision_body() -> dict[str, object]:
    return {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "co widzisz?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,YWJj"},
                    },
                ],
            }
        ],
    }


async def _upstream(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/v1/fake/upstream-error")
    assert response.status_code == HTTP_OK
    return response.json()


async def test_embeddings_every_three_times_two(client: httpx.AsyncClient) -> None:
    """`every:3, times:2` na embeddings: żądania 3 i 6 → 502, reszta OK; reguła sama się wyłącza."""
    setup = await client.post(
        "/v1/fake/upstream-error",
        json={"route": "embeddings", "every": 3, "status": 502, "times": 2},
    )
    assert setup.status_code == HTTP_OK
    state = await _upstream(client)
    assert state["embeddings"] == {"every": 3, "status": 502, "times_left": 2}
    assert state["chat"] == EMPTY_STATE

    statuses: list[int] = []
    for _ in range(3):
        statuses.append((await client.post("/v1/embeddings", json=_embed_body())).status_code)
    assert statuses == [HTTP_OK, HTTP_OK, HTTP_BAD_GATEWAY]
    assert (await _upstream(client))["embeddings"]["times_left"] == 1
    for _ in range(3):
        statuses.append((await client.post("/v1/embeddings", json=_embed_body())).status_code)
    assert statuses[3:5] == [HTTP_OK, HTTP_OK]
    assert (await _upstream(client))["embeddings"]["times_left"] == 0
    assert statuses[5] == HTTP_BAD_GATEWAY

    state = await _upstream(client)
    assert state["embeddings"] == {"every": 0, "status": 502, "times_left": 0}
    for _ in range(3):
        assert (await client.post("/v1/embeddings", json=_embed_body())).status_code == HTTP_OK


async def test_error_body_is_openai_server_error(client: httpx.AsyncClient) -> None:
    """Ciało błędu ma format OpenAI z `error.type == "server_error"` i komunikatem ze statusem."""
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "embeddings", "every": 1, "status": 503, "times": None},
    )
    response = await client.post("/v1/embeddings", json=_embed_body())
    assert response.status_code == HTTP_UNAVAILABLE
    assert response.json() == {"error": {"message": "upstream error 503", "type": "server_error"}}


async def test_chat_route_covers_vision(client: httpx.AsyncClient) -> None:
    """Trasa `chat` obejmuje wizję: żądanie `fake-vision` dostaje 5xx i jest liczone."""
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "chat", "every": 1, "status": 500, "times": None},
    )
    response = await client.post("/v1/chat/completions", json=_vision_body())
    assert response.status_code == HTTP_INTERNAL
    assert response.json()["error"]["type"] == "server_error"
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["chat_completions"] == {VISION_MODEL: 1}
    assert payload["upstream_errors"]["chat"] == 1


async def test_every_one_without_times_always_injects(client: httpx.AsyncClient) -> None:
    """`every:1` bez `times` wstrzykuje 5xx w każde żądanie (bez wyłączania)."""
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "chat", "every": 1, "status": 504, "times": None},
    )
    for _ in range(3):
        response = await client.post("/v1/chat/completions", json=_chat_body())
        assert response.status_code == HTTP_GATEWAY_TIMEOUT
    assert (await _upstream(client))["chat"]["times_left"] is None


async def test_every_zero_disables(client: httpx.AsyncClient) -> None:
    """`every:0` wyłącza wstrzykiwanie (ustawienie po włączeniu)."""
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "embeddings", "every": 1, "status": 500, "times": None},
    )
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "embeddings", "every": 0, "status": 500, "times": None},
    )
    assert (await client.post("/v1/embeddings", json=_embed_body())).status_code == HTTP_OK
    assert (await _upstream(client))["embeddings"]["every"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"route": "embeddings", "every": 1, "status": 404, "times": None},
        {"route": "rerank", "every": 1, "status": 500, "times": None},
        {"route": "embeddings", "every": -1, "status": 500, "times": None},
        {"route": "embeddings", "every": 1, "status": 500, "times": 0},
    ],
)
async def test_invalid_body_is_unprocessable(
    client: httpx.AsyncClient, body: dict[str, object]
) -> None:
    """Błędne `status`/`route`/`every`/`times` → 422, stan obu tras bez zmian."""
    response = await client.post("/v1/fake/upstream-error", json=body)
    assert response.status_code == HTTP_UNPROCESSABLE
    state = await _upstream(client)
    assert state["embeddings"] == EMPTY_STATE
    assert state["chat"] == EMPTY_STATE


async def test_routes_are_independent(client: httpx.AsyncClient) -> None:
    """Ustawienia i licznik tras są niezależne."""
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "embeddings", "every": 1, "status": 502, "times": None},
    )
    assert (await client.post("/v1/embeddings", json=_embed_body())).status_code == HTTP_BAD_GATEWAY
    assert (await client.post("/v1/chat/completions", json=_chat_body())).status_code == HTTP_OK
    state = await _upstream(client)
    assert state["chat"] == EMPTY_STATE
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["upstream_errors"] == {"embeddings": 1, "chat": 0}


async def test_embed_429_takes_precedence(client: httpx.AsyncClient) -> None:
    """Gdy obie reguły trafiają to samo żądanie, wygrywa `embed-429`; 5xx się nie liczy."""
    await client.post("/v1/fake/embed-429", json={"every": 1, "retry_after_s": None})
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "embeddings", "every": 1, "status": 502, "times": 1},
    )
    response = await client.post("/v1/embeddings", json=_embed_body())
    assert response.status_code == HTTP_TOO_MANY
    assert response.json()["error"]["type"] == "rate_limit_error"
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["upstream_errors"]["embeddings"] == 0
    assert (await _upstream(client))["embeddings"]["times_left"] == 1


async def test_upstream_errors_in_stats_and_reset(client: httpx.AsyncClient) -> None:
    """Wstrzyknięcia liczone w `upstream_errors`; reset zeruje liczniki, nie ustawienia."""
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "embeddings", "every": 1, "status": 500, "times": None},
    )
    for _ in range(2):
        await client.post("/v1/embeddings", json=_embed_body())
    payload = (await client.get("/v1/fake/stats")).json()
    assert payload["upstream_errors"] == {"embeddings": 2, "chat": 0}

    reset = await client.post("/v1/fake/stats/reset")
    assert reset.status_code == HTTP_OK
    assert reset.json()["upstream_errors"] == {"embeddings": 0, "chat": 0}
    assert (await _upstream(client))["embeddings"] == {
        "every": 1,
        "status": 500,
        "times_left": None,
    }


async def test_error_returned_before_delays(client: httpx.AsyncClient) -> None:
    """5xx zwracany jest przed opóźnieniami embed-delay/ocr-delay (odpowiedź natychmiastowa)."""
    await client.post("/v1/fake/embed-delay", json={"ms": DELAY_MS})
    await client.post("/v1/fake/ocr-delay", json={"ms": DELAY_MS})
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "embeddings", "every": 1, "status": 502, "times": None},
    )
    await client.post(
        "/v1/fake/upstream-error",
        json={"route": "chat", "every": 1, "status": 502, "times": None},
    )
    start = time.perf_counter()
    embed = await client.post("/v1/embeddings", json=_embed_body())
    chat = await client.post("/v1/chat/completions", json=_chat_body())
    assert time.perf_counter() - start < FAST_LIMIT_S
    assert embed.status_code == HTTP_BAD_GATEWAY
    assert chat.status_code == HTTP_BAD_GATEWAY


async def test_sdk_receives_internal_server_error(sdk: openai.AsyncOpenAI) -> None:
    """Prawdziwe SDK `openai` (max_retries=0) dostaje `InternalServerError` przy 5xx."""
    stats.set_upstream_error("embeddings", 1, 500, None)
    with pytest.raises(openai.InternalServerError):
        await sdk.embeddings.create(model=EMBED_MODEL, input="a")
