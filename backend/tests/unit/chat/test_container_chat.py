"""Testy jednostkowe Container.chat i WD_POSTHOC_CITATIONS (CONTRACT C11)."""

import pytest

from app.core.config import Settings
from app.core.container import Container
from app.services.chat import DbChatService


def test_container_chat_is_lazy_singleton() -> None:
    """Container.chat tworzy usługę leniwie, raz i bez I/O — ta sama instancja w kontenerze."""
    container = Container(Settings(env="test"))
    assert isinstance(container.chat, DbChatService)
    assert container.chat is container.chat


def test_posthoc_citations_default_true() -> None:
    """Domyślnie cytowania post-hoc włączone (CONTRACT C11)."""
    assert Settings(env="test").posthoc_citations is True


def test_posthoc_citations_env_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """WD_POSTHOC_CITATIONS=false wyłącza post-hoc (K4 §4 p. 3)."""
    monkeypatch.setenv("WD_POSTHOC_CITATIONS", "false")
    assert Settings(env="test").posthoc_citations is False
