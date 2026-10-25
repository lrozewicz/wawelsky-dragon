"""Pytania pokrewne: marker promptu `related_question.md` (K10 §4, poprawka 2026-10-01)."""

import json
import re
from typing import Any

import httpx
import pytest

HTTP_OK = 200
CHAT_MODEL = "fake-chat"
THINK_MODEL = "fake-chat-think"
RELATED_MARKER = "**5-10 follow-up questions**"
RELATED_ANSWER = (
    "1. Pytanie pokrewne pierwsze\n2. Pytanie pokrewne drugie\n3. Pytanie pokrewne trzecie"
)
THINK_PREFIX = "<think>Rozważam pytanie.</think>"
LINE_RE = re.compile(r"^[0-9]\. ")
SYS_WITH_KNOWLEDGE = "ID: 1\n  Pierwszy fragment o umowie najmu.  \n"
USER_WITH_MARKER = f"Zadanie: {RELATED_MARKER} dla poprzedniej odpowiedzi."
USER_PLAIN = "Jaka jest stolica?"


def _chat_body(model: str, messages: list[dict[str, Any]], stream: bool = False) -> dict[str, Any]:
    return {"model": model, "messages": messages, "stream": stream}


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _system(text: str) -> dict[str, Any]:
    return {"role": "system", "content": text}


async def test_marker_in_user(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(CHAT_MODEL, [_user(USER_WITH_MARKER)])
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == RELATED_ANSWER


async def test_marker_in_system(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_system(USER_WITH_MARKER), _user("pytanie")]),
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == RELATED_ANSWER


async def test_marker_in_think_model(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(THINK_MODEL, [_user(USER_WITH_MARKER)])
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == THINK_PREFIX + RELATED_ANSWER


async def test_marker_precedes_knowledge_block(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_system(SYS_WITH_KNOWLEDGE), _user(USER_WITH_MARKER)]),
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == RELATED_ANSWER


async def test_marker_with_empty_scenario(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user(USER_WITH_MARKER)]),
        headers={"X-Fake-Scenario": "empty"},
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == ""


async def test_marker_streamed(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json=_chat_body(CHAT_MODEL, [_user(USER_WITH_MARKER)], stream=True),
    )
    assert response.status_code == HTTP_OK
    frames = [frame for frame in response.text.split("\n\n") if frame]
    chunks = [json.loads(frame[len("data: ") :]) for frame in frames[:-1]]
    deltas = [chunk["choices"][0]["delta"]["content"] for chunk in chunks[1:-1]]
    assert "".join(deltas) == RELATED_ANSWER


async def test_without_marker_regression(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions", json=_chat_body(CHAT_MODEL, [_user(USER_PLAIN)])
    )
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == f"Odpowiedź testowa: {USER_PLAIN}"


@pytest.mark.parametrize("line", RELATED_ANSWER.splitlines())
def test_related_lines_are_numbered(line: str) -> None:
    assert LINE_RE.match(line)
