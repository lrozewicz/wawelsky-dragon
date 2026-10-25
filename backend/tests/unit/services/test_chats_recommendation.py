"""Testy jednostkowe rekomendacji pytań (E2-1 CHAT): prompt, parametry, parsowanie."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.prompts import load_prompt
from app.services.chats import ChatsService, _related_questions


def test_related_questions_parsing() -> None:
    """Linie „N. pytanie" bez numeru; reszta odpowiedzi pomijana (chat_api.py:1231).

    Upstream: ``re.match(r"^[0-9]\\. ", …)`` — dokładnie jedna cyfra numeru, więc
    „10. Gdzie mieszkał smok?" nie jest linią pytania i zostaje pominięte.
    """
    raw = "Oto pytania:\n1. Kto zabił smoka?\n10. Gdzie mieszkał smok?\n- bez numeru"
    assert _related_questions(raw) == ["Kto zabił smoka?"]
    assert _related_questions("Odpowiedź testowa: smok") == []


class _StubRegistry:
    """Rejestr zwracający stały model czatu (bez bazy)."""

    def __init__(self) -> None:
        self.refs: list[str | None] = []

    async def resolve(self, ref: str | None, model_type: str) -> SimpleNamespace:
        self.refs.append(ref)
        assert model_type == "chat"
        return SimpleNamespace(name="fake-chat")


class _StubGateway:
    """Bramka LLM zapisująca wywołanie i zwracająca numerowaną odpowiedź."""

    def __init__(self, text: str = "1. Kto zabił smoka?\n2. Gdzie mieszkał smok?") -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def chat(self, model: Any, messages: Any, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({"model": model, "messages": list(messages), "kwargs": kwargs})
        return SimpleNamespace(text=self.text)


async def test_recommend_questions_prompt_and_generation_params() -> None:
    """Rekomendacja: prompt related_question, wiadomość user i parametry jak upstream."""
    registry = _StubRegistry()
    gateway = _StubGateway()
    service = ChatsService(SimpleNamespace(models=registry, llm=gateway))  # type: ignore[arg-type]
    result = await service.recommend_questions("smokwawelski")
    assert result == ["Kto zabił smoka?", "Gdzie mieszkał smok?"]
    assert registry.refs == [None]
    call = gateway.calls[0]
    assert [message["role"] for message in call["messages"]] == ["system", "user"]
    assert call["messages"][0]["content"] == load_prompt("related_question")
    assert call["messages"][1]["content"] == (
        "\nKeywords: smokwawelski\nRelated search terms:\n    "
    )
    # LLM_SETTING_DEFAULTS (llm_service.py:31): presence_penalty 0.4 też jest wysyłany.
    assert call["kwargs"] == {
        "temperature": 0.1,
        "top_p": 0.3,
        "extra": {"frequency_penalty": 0.7, "presence_penalty": 0.4},
    }
    assert call["model"].name == "fake-chat"


async def test_recommend_questions_without_container_start() -> None:
    """Kontener przed start() → RuntimeError (wzorzec usług)."""
    service = ChatsService(SimpleNamespace(models=None, llm=None))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        await service.recommend_questions("smok")
