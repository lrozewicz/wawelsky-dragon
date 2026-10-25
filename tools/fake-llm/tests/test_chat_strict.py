"""Testy modelu `fake-chat-strict` (K10, 2026-10-04): treść jak `fake-chat`, 400 parametrów."""

import json
from typing import Any

import httpx
import pytest

from fake_llm.stats import CHAT_REQUESTS

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_SERVER_ERROR = 500
STRICT_MODEL = "fake-chat-strict"
CHAT_MODEL = "fake-chat"
UNKNOWN_MODEL = "nope"
RELATED_PROMPT = "Zadanie: **5-10 follow-up questions** dla poprzedniej odpowiedzi."
SYS = "Kontekst:\nID: 1\nPierwszy fragment o umowie najmu.\n"
COUNTED_REQUESTS = 2

# Dosłowna treść błędu 400 z K10 „Poprawka 2026-10-04” (JSON z kontraktu, <lista> do wstawienia).
_CONTRACT_ERROR_TEMPLATE = (
    '{"error":{"message":"litellm.UnsupportedParamsError: openai does not support parameters: '
    "[<lista>], for model=fake-chat-strict. To drop these, set `litellm.drop_params=True` or for "
    'proxy:\\n\\n`litellm_settings:\\n drop_params: true`\\n","type":"invalid_request_error",'
    '"param":null,"code":"400"}}'
)


def _body(
    model: str,
    messages: list[dict[str, Any]],
    stream: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    return {"model": model, "messages": messages, "stream": stream, **extra}


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _expected_error(listing: str) -> dict[str, Any]:
    """Błąd z kontraktu z wstawioną listą kluczy (JSON-escape `\\n` → prawdziwe nowe linie)."""
    error = json.loads(_CONTRACT_ERROR_TEMPLATE.replace("<lista>", listing))["error"]
    return dict(error)


async def test_strict_model_in_models_list(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models")
    assert response.status_code == HTTP_OK
    assert STRICT_MODEL in [model["id"] for model in response.json()["data"]]


async def test_strict_content_matches_chat(client: httpx.AsyncClient) -> None:
    messages = [{"role": "system", "content": SYS}, _user("pytanie")]
    chat = await client.post("/v1/chat/completions", json=_body(CHAT_MODEL, messages))
    strict = await client.post("/v1/chat/completions", json=_body(STRICT_MODEL, messages))
    assert strict.status_code == HTTP_OK
    strict_content = strict.json()["choices"][0]["message"]["content"]
    chat_content = chat.json()["choices"][0]["message"]["content"]
    assert strict_content == chat_content
    assert strict.json()["model"] == STRICT_MODEL


async def test_strict_related_questions_rule(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_body(STRICT_MODEL, [_user(RELATED_PROMPT)])
    )
    assert response.status_code == HTTP_OK
    content = response.json()["choices"][0]["message"]["content"]
    assert content == (
        "1. Pytanie pokrewne pierwsze\n2. Pytanie pokrewne drugie\n3. Pytanie pokrewne trzecie"
    )


async def test_strict_stream_matches_chat(client: httpx.AsyncClient) -> None:
    messages = [_user("Jaka jest stolica?")]
    strict = await client.post("/v1/chat/completions", json=_body(STRICT_MODEL, messages, True))
    chat = await client.post("/v1/chat/completions", json=_body(CHAT_MODEL, messages, True))
    assert strict.status_code == HTTP_OK
    assert strict.headers["content-type"].startswith("text/event-stream")

    def chunks(response: httpx.Response) -> list[dict[str, Any]]:
        frames = [frame for frame in response.text.split("\n\n") if frame]
        assert frames[-1] == "data: [DONE]"
        return [json.loads(frame[len("data: ") :]) for frame in frames[:-1]]

    strict_chunks = chunks(strict)
    chat_chunks = chunks(chat)
    strict_deltas = [c["choices"][0]["delta"].get("content") for c in strict_chunks[1:-1]]
    chat_deltas = [c["choices"][0]["delta"].get("content") for c in chat_chunks[1:-1]]
    assert strict_deltas == chat_deltas
    assert strict_chunks[-1]["usage"] == chat_chunks[-1]["usage"]
    assert strict_chunks[-1]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize(
    ("extra", "listing"),
    [
        ({"presence_penalty": 0.4}, "'presence_penalty'"),
        ({"frequency_penalty": 0.7}, "'frequency_penalty'"),
        ({"presence_penalty": 0}, "'presence_penalty'"),
        ({"frequency_penalty": 0}, "'frequency_penalty'"),
        ({"temperature": 0.2}, "'temperature'"),
        ({"top_p": 0.5}, "'top_p'"),
    ],
)
async def test_strict_rejects_unsupported_param(
    client: httpx.AsyncClient, extra: dict[str, Any], listing: str
) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_body(STRICT_MODEL, [_user("x")], **extra)
    )
    assert response.status_code == HTTP_BAD_REQUEST
    assert response.json()["error"] == _expected_error(listing)


async def test_strict_rejects_all_four_in_contract_order(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_body(
            STRICT_MODEL,
            [_user("x")],
            presence_penalty=0.4,
            frequency_penalty=0.7,
            temperature=0.2,
            top_p=0.5,
        ),
    )
    assert response.status_code == HTTP_BAD_REQUEST
    assert response.json()["error"] == _expected_error(
        "'presence_penalty', 'frequency_penalty', 'temperature', 'top_p'"
    )


async def test_strict_lists_only_present_params(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_body(STRICT_MODEL, [_user("x")], presence_penalty=0.4, frequency_penalty=0.7),
    )
    assert response.status_code == HTTP_BAD_REQUEST
    assert response.json()["error"] == _expected_error("'presence_penalty', 'frequency_penalty'")


@pytest.mark.parametrize(
    "extra",
    [{"temperature": 1}, {"top_p": 1}, {"temperature": 1, "top_p": 1}],
)
async def test_strict_allows_value_one(client: httpx.AsyncClient, extra: dict[str, Any]) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_body(STRICT_MODEL, [_user("x")], **extra)
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == "Odpowiedź testowa: x"


async def test_strict_one_allowed_but_penalty_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_body(STRICT_MODEL, [_user("x")], temperature=1, presence_penalty=0.4),
    )
    assert response.status_code == HTTP_BAD_REQUEST
    assert response.json()["error"] == _expected_error("'presence_penalty'")


async def test_strict_rejects_params_for_stream(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_body(STRICT_MODEL, [_user("x")], True, temperature=0.2)
    )
    assert response.status_code == HTTP_BAD_REQUEST
    assert response.json()["error"]["code"] == "400"


async def test_chat_ignores_params(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_body(
            CHAT_MODEL,
            [_user("x")],
            presence_penalty=0.4,
            frequency_penalty=0.7,
            temperature=0.2,
            top_p=0.5,
        ),
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == "Odpowiedź testowa: x"


async def test_scenario_wins_before_400(client: httpx.AsyncClient) -> None:
    """Przykład z briefu: `fake-chat-strict` + `X-Fake-Scenario` → scenariusz wygrywa przed 400."""
    response = await client.post(
        "/v1/chat/completions",
        json=_body(STRICT_MODEL, [_user("x")], temperature=0.2),
        headers={"X-Fake-Scenario": "empty"},
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == ""


async def test_error_scenario_wins_before_400(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_body(STRICT_MODEL, [_user("x")], temperature=0.2),
        headers={"X-Fake-Scenario": "error_500"},
    )
    assert response.status_code == HTTP_SERVER_ERROR


async def test_unknown_model_before_400(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_body(UNKNOWN_MODEL, [_user("x")], temperature=0.2)
    )
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json()["error"]["code"] == "model_not_found"


async def test_stats_counts_chat_requests(client: httpx.AsyncClient) -> None:
    """Licznik żądań na model (T3.5): liczy także żądania odrzucone 400 — używany w T5."""
    before = CHAT_REQUESTS[STRICT_MODEL]
    await client.post("/v1/chat/completions", json=_body(STRICT_MODEL, [_user("x")]))
    await client.post(
        "/v1/chat/completions", json=_body(STRICT_MODEL, [_user("x")], temperature=0.2)
    )
    after = CHAT_REQUESTS[STRICT_MODEL]
    assert after - before == COUNTED_REQUESTS
    response = await client.get("/v1/fake/stats")
    assert response.status_code == HTTP_OK
    assert response.json()["chat_completions"][STRICT_MODEL] == after
