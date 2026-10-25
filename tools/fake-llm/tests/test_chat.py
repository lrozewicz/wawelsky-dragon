"""Testy HTTP `POST /v1/chat/completions` — wiersz tabeli briefu = test (K10 §4, C5)."""

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from fake_llm.tokens import tokenize

HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_SERVER_ERROR = 500
HTTP_RATE_LIMITED = 429
RETRY_AFTER = "1"
TEXT_LIMIT = 80
CHUNK_CHARS = 5
LONG_LENGTH = 2000
SLOW_STREAM_MIN_SECONDS = 0.6
SLOW_STREAM_DELTAS = 4
STREAM_EMPTY_CHUNKS = 2
PROMPT_TOKENS_UMOWA_NAJMU = 2
CHAT_MODEL = "fake-chat"
THINK_MODEL = "fake-chat-think"
VISION_MODEL = "fake-vision"
UNKNOWN_MODEL = "nope"
EMBED_MODEL = "fake-embed-1024"
COMPLETION_ID = "chatcmpl-fake"
FIXTURE_RED_TEXT = "czerwony kwadrat"
SYS = "Kontekst:\nID: 2\nDrugi fragment.\nID: 1\n  Pierwszy fragment o umowie najmu.  \n"
RED_BYTES = (Path(__file__).resolve().parent / "data" / "red.png").read_bytes()
RED_SHA8 = hashlib.sha256(RED_BYTES).hexdigest()[:8]
UNKNOWN_BYTES = b"abc"
UNKNOWN_SHA8 = hashlib.sha256(UNKNOWN_BYTES).hexdigest()[:8]
URL_ENCODED_BYTES = b"hello world"
URL_ENCODED_SHA8 = hashlib.sha256(URL_ENCODED_BYTES).hexdigest()[:8]
STREAM_USER_TEXT = "Jaka jest stolica?"


def _chat_body(model: str, messages: list[dict[str, Any]], stream: bool = False) -> dict[str, Any]:
    return {"model": model, "messages": messages, "stream": stream}


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


async def test_chat_basic_completion(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(CHAT_MODEL, [_user("Jaka jest stolica?")])
    )
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["id"] == COMPLETION_ID
    assert body["created"] == 0
    assert body["model"] == CHAT_MODEL
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "Odpowiedź testowa: Jaka jest stolica?",
    }
    assert body["choices"][0]["finish_reason"] == "stop"


async def test_user_text_truncated(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(CHAT_MODEL, [_user("a" * 100)])
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Odpowiedź testowa: " + "a" * TEXT_LIMIT


async def test_last_user_message_wins(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user("pierwsza"), _user("druga")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content.endswith("druga")


async def test_knowledge_block_basic(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [{"role": "system", "content": SYS}, _user("pytanie")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Na podstawie źródeł: Pierwszy fragment o umowie najmu. [ID:1]"


async def test_knowledge_block_snippet_truncated(client: httpx.AsyncClient) -> None:
    system = "ID: 0\n" + "x" * 100 + "  "
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [{"role": "system", "content": system}, _user("pytanie")]),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Na podstawie źródeł: " + "x" * TEXT_LIMIT + " [ID:0]"


async def test_knowledge_block_across_messages(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(
            CHAT_MODEL,
            [
                {"role": "system", "content": "ID: 5\npiąty"},
                {"role": "system", "content": "ID: 3\ntrzeci"},
            ],
        ),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content.endswith(" trzeci [ID:3]")


async def test_multimodal_text_parts(client: httpx.AsyncClient) -> None:
    parts = [
        {"type": "text", "text": "ala"},
        {"type": "text", "text": "kot"},
    ]
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(CHAT_MODEL, [{"role": "user", "content": parts}])
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Odpowiedź testowa: ala\nkot"


async def test_think_model_prefix(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/chat/completions", json=_chat_body(THINK_MODEL, [_user("x")]))
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "<think>Rozważam pytanie.</think>Odpowiedź testowa: x"


async def test_usage_counts(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(CHAT_MODEL, [_user("umowa najmu")])
    )
    assert response.status_code == HTTP_OK
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    assert body["usage"]["prompt_tokens"] == PROMPT_TOKENS_UMOWA_NAJMU
    assert body["usage"]["completion_tokens"] == len(tokenize(content))
    assert body["usage"]["total_tokens"] == (
        body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
    )


async def test_unknown_model_not_found(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(UNKNOWN_MODEL, [_user("x")])
    )
    assert response.status_code == HTTP_NOT_FOUND
    error = response.json()["error"]
    assert error["code"] == "model_not_found"
    assert error["param"] == "model"


async def test_embedding_model_not_found(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/chat/completions", json=_chat_body(EMBED_MODEL, [_user("x")]))
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json()["error"]["code"] == "model_not_found"


@pytest.mark.parametrize("stream", [False, True])
async def test_error_500_scenario(client: httpx.AsyncClient, stream: bool) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user("x")], stream=stream),
        headers={"X-Fake-Scenario": "error_500"},
    )
    assert response.status_code == HTTP_SERVER_ERROR
    assert response.json() == {"error": {"message": "fake error", "type": "server_error"}}


async def test_error_429_scenario(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user("x")]),
        headers={"X-Fake-Scenario": "error_429"},
    )
    assert response.status_code == HTTP_RATE_LIMITED
    assert response.json() == {"error": {"message": "rate limited", "type": "rate_limit_error"}}
    assert response.headers["retry-after"] == RETRY_AFTER


@pytest.mark.parametrize("model", [CHAT_MODEL, THINK_MODEL])
async def test_empty_scenario(client: httpx.AsyncClient, model: str) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(model, [_user("x")]),
        headers={"X-Fake-Scenario": "empty"},
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == ""


async def test_no_citations_scenario(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [{"role": "system", "content": SYS}, _user("pytanie")]),
        headers={"X-Fake-Scenario": "no_citations"},
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Na podstawie źródeł: Pierwszy fragment o umowie najmu."
    assert "[ID:" not in content


async def test_long_scenario(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user("x")]),
        headers={"X-Fake-Scenario": "long"},
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert len(content) == LONG_LENGTH
    assert content.startswith("Odpowiedź testowa: x")


async def test_unknown_scenario_ignored(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user("x")]),
        headers={"X-Fake-Scenario": "nieznany"},
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == "Odpowiedź testowa: x"


async def test_stream_frames(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(CHAT_MODEL, [_user(STREAM_USER_TEXT)], stream=True)
    )
    assert response.status_code == HTTP_OK
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [frame for frame in response.text.split("\n\n") if frame]
    assert all(frame.startswith("data: ") for frame in frames)
    assert frames[-1] == "data: [DONE]"
    chunks = [json.loads(frame[len("data: ") :]) for frame in frames[:-1]]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    for chunk in chunks:
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["created"] == 0
    deltas = [chunk["choices"][0]["delta"]["content"] for chunk in chunks[1:-1]]
    assert all(len(delta) == CHUNK_CHARS for delta in deltas[:-1])
    assert len(deltas[-1]) <= CHUNK_CHARS
    stop = chunks[-1]
    assert stop["choices"][0]["finish_reason"] == "stop"
    assert stop["choices"][0]["delta"] == {}
    base = await client.post(
        "/v1/chat/completions", json=_chat_body(CHAT_MODEL, [_user(STREAM_USER_TEXT)])
    )
    base_body = base.json()
    assert "".join(deltas) == base_body["choices"][0]["message"]["content"]
    assert stop["usage"] == base_body["usage"]


async def test_stream_empty_scenario(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user("x")], stream=True),
        headers={"X-Fake-Scenario": "empty"},
    )
    assert response.status_code == HTTP_OK
    frames = [frame for frame in response.text.split("\n\n") if frame]
    assert frames[-1] == "data: [DONE]"
    chunks = [json.loads(frame[len("data: ") :]) for frame in frames[:-1]]
    assert len(chunks) == STREAM_EMPTY_CHUNKS  # ramka roli + ramka stop z usage, zero delt content
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    assert chunks[1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[1]["usage"]["completion_tokens"] == 0


async def test_slow_stream_timing(client: httpx.AsyncClient) -> None:
    start = time.monotonic()
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user("x")], stream=True),
        headers={"X-Fake-Scenario": "slow_stream"},
    )
    elapsed = time.monotonic() - start
    assert response.status_code == HTTP_OK
    frames = [frame for frame in response.text.split("\n\n") if frame]
    chunks = [json.loads(frame[len("data: ") :]) for frame in frames[:-1]]
    deltas = [chunk["choices"][0]["delta"]["content"] for chunk in chunks[1:-1]]
    assert len(deltas) == SLOW_STREAM_DELTAS  # treść 20 znaków → 4 delty
    assert elapsed >= SLOW_STREAM_MIN_SECONDS
    assert "".join(deltas) == "Odpowiedź testowa: x"


async def test_vision_known_image(client: httpx.AsyncClient) -> None:
    data_url = "data:image/png;base64," + base64.b64encode(RED_BYTES).decode("ascii")
    parts = [
        {"type": "text", "text": "co to?"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(VISION_MODEL, [{"role": "user", "content": parts}])
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == f"<p>OCR:{RED_SHA8}</p><p>{FIXTURE_RED_TEXT}</p>"


async def test_vision_unknown_image(client: httpx.AsyncClient) -> None:
    data_url = "data:application/octet-stream;base64," + base64.b64encode(UNKNOWN_BYTES).decode(
        "ascii"
    )
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(
            VISION_MODEL,
            [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url}}]}],
        ),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == f"<p>OCR:{UNKNOWN_SHA8}</p>"


async def test_vision_url_encoded(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(
            VISION_MODEL,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:text/plain,hello%20world"}}
                    ],
                }
            ],
        ),
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == f"<p>OCR:{URL_ENCODED_SHA8}</p>"


async def test_vision_https_url_ignored(client: httpx.AsyncClient) -> None:
    parts = [
        {"type": "text", "text": "x"},
        {"type": "image_url", "image_url": {"url": "https://example.com/obraz.png"}},
    ]
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(VISION_MODEL, [{"role": "user", "content": parts}])
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == "Odpowiedź testowa: x"


async def test_vision_two_images(client: httpx.AsyncClient) -> None:
    parts = [
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(RED_BYTES).decode("ascii")
            },
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "data:application/octet-stream;base64,"
                + base64.b64encode(UNKNOWN_BYTES).decode("ascii")
            },
        },
    ]
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(VISION_MODEL, [{"role": "user", "content": parts}])
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == f"<p>OCR:{RED_SHA8}</p><p>{FIXTURE_RED_TEXT}</p><p>OCR:{UNKNOWN_SHA8}</p>"
