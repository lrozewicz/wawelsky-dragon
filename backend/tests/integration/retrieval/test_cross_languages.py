"""Testy ``cross_languages`` w DbRetrievalService (kontrakt E2-H2 C3, fake-llm K10).

Pytanie przepisywane jednym wywołaniem modelu czatu przed wyszukiwaniem; brak listy
(lub pusta) → bez wywołania; błąd bramki/``**ERROR**`` → pytanie oryginalne.
Wzorzec: ``test_service.py`` (pipeline ingestii) i ``test_service_filters.py``.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories.datasets import DatasetRow
from app.llm.errors import LLMUnavailable
from app.llm.types import ChatResult
from app.prompts import load_prompt
from app.services.retrieval import RetrievalQuery
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

_TEXT = (
    "Umowa najmu lokalu użytkowego w Krakowie. Wynajmujący oddaje najemcy lokal przy ulicy "
    "Grodeckiej 7. Umowa najmu może zostać wypowiedziana z zachowaniem trzymiesięcznego okresu."
) * 2
_QUESTION = "Jak wypowiedzieć umowę najmu lokalu?"
# Odpowiedź modelu jak w C3: wiodący „Output:” i puste linie mają zniknąć, „===” rozdziela warianty.
_RAW_ANSWER = (
    "Output:How to terminate the lease agreement?\n\n===\n\nWie kündige ich den Mietvertrag?\n\n"
)
_REWRITTEN = "How to terminate the lease agreement?\nWie kündige ich den Mietvertrag?"
_KEYWORDS = "lease, agreement"


@pytest.fixture
async def ingested(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> AsyncIterator[tuple[Container, DatasetRow]]:
    """Kontener z zingestowanym „umowa.txt” i datasetem (wzorzec test_service.ingested)."""
    ds = await seed_dataset(sm)
    await ingest_text(container, ds, "umowa.txt", _TEXT)
    yield container, ds


def _chat_result(text: str) -> ChatResult:
    """ChatResult z samą treścią (pola tokenów/rozumu nieistotne dla testu)."""
    return ChatResult(text=text, reasoning=None, tokens_in=0, tokens_out=0, finish_reason=None)


class _ChatSpy:
    """Zaślepka ``llm.chat``: zapisuje wywołania, zwraca kolejne treści albo rzuca błąd."""

    def __init__(self, *, texts: Sequence[str] = (), error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._texts = tuple(texts)
        self._error = error

    async def __call__(
        self, model: Any, messages: Sequence[dict[str, str]], **kwargs: Any
    ) -> ChatResult:
        index = len(self.calls)
        self.calls.append({"model": model, "messages": messages, "kwargs": kwargs})
        if self._error is not None:
            raise self._error
        return _chat_result(self._texts[min(index, len(self._texts) - 1)])


def _install_chat(
    monkeypatch: pytest.MonkeyPatch, container: Container, spy: _ChatSpy
) -> list[str]:
    """Podmienia ``chat`` bramki; zwraca listę pytań przekazanych do ``embed_query``.

    Pytanie z ``embed_query`` to pytanie po przepisaniu — wejście wyszukiwania (K5 §3.3).
    """
    seen: list[str] = []
    original = container.llm.embed_query

    async def recording_embed_query(model: Any, text: str) -> list[float]:
        seen.append(text)
        return await original(model, text)

    monkeypatch.setattr(container.llm, "chat", spy)
    monkeypatch.setattr(container.llm, "embed_query", recording_embed_query)
    return seen


def _q(ds: DatasetRow, **overrides: object) -> RetrievalQuery:
    """RetrievalQuery na zingestowanym datasecie (tryb wektorowy: w > 0)."""
    params: dict[str, Any] = {"question": _QUESTION, "dataset_ids": (ds.id,)}
    params.update(overrides)
    return RetrievalQuery(**params)


async def test_rewrites_question_with_one_chat_call(
    ingested: tuple[Container, DatasetRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) niepusta lista → 1 wywołanie chat, a przepisane pytanie trafia do wyszukiwania.

    Warianty odpowiedzi rozdzielone ``===`` łączone ``\\n``, wiodące ``Output:`` i puste linie
    usunięte (wzorzec C3) — sprawdza to ``_RAW_ANSWER``.
    """
    container, ds = ingested
    spy = _ChatSpy(texts=[_RAW_ANSWER])
    seen = _install_chat(monkeypatch, container, spy)

    await container.retrieval.retrieve(
        principal_for(ds.tenant_id), _q(ds, cross_languages=("en", "de"))
    )

    assert len(spy.calls) == 1
    assert spy.calls[0]["kwargs"]["temperature"] == 0.2  # noqa: PLR2004 — temperatura wg C3
    assert spy.calls[0]["kwargs"]["cache"] is True
    system, user = spy.calls[0]["messages"]
    assert system["content"] == load_prompt("cross_languages_sys_prompt")
    assert user["content"] == "**Tekst:**\n" + _QUESTION + "\n===\nen, de\n\n**Output:**\n\n"
    assert seen == [_REWRITTEN]


async def test_cross_languages_runs_before_keyword(
    ingested: tuple[Container, DatasetRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C3: przepisanie (1. czat) idzie przed rozszerzeniem ``keyword`` (2. czat).

    Słowa kluczowe doklejone do pytania JUŻ przepisanego — kolejność jak w upstreamie.
    """
    container, ds = ingested
    spy = _ChatSpy(texts=[_RAW_ANSWER, _KEYWORDS])
    seen = _install_chat(monkeypatch, container, spy)

    await container.retrieval.retrieve(
        principal_for(ds.tenant_id), _q(ds, cross_languages=("en", "de"), keyword=True)
    )

    assert len(spy.calls) == 2  # noqa: PLR2004 — dwa czaty: cross_languages, potem keyword
    assert spy.calls[0]["messages"][0]["content"] == load_prompt("cross_languages_sys_prompt")
    assert spy.calls[1]["messages"][0]["content"] != load_prompt("cross_languages_sys_prompt")
    assert seen == [_REWRITTEN + " lease agreement"]


async def test_no_chat_call_without_languages(
    ingested: tuple[Container, DatasetRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) brak listy / pusta lista → 0 wywołań chat, oryginalne pytanie w wyszukiwaniu."""
    container, ds = ingested
    for overrides in ({}, {"cross_languages": ()}):
        spy = _ChatSpy(error=AssertionError("chat nie powinien być wołany"))
        seen = _install_chat(monkeypatch, container, spy)
        await container.retrieval.retrieve(principal_for(ds.tenant_id), _q(ds, **overrides))
        assert spy.calls == []
        assert seen == [_QUESTION]


async def test_error_marker_falls_back_to_original(
    ingested: tuple[Container, DatasetRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) odpowiedź z ``**ERROR**`` → pytanie oryginalne w wyszukiwaniu."""
    container, ds = ingested
    spy = _ChatSpy(texts=["**ERROR** nie umiem przetłumaczyć"])
    seen = _install_chat(monkeypatch, container, spy)

    await container.retrieval.retrieve(principal_for(ds.tenant_id), _q(ds, cross_languages=("en",)))

    assert len(spy.calls) == 1
    assert seen == [_QUESTION]


async def test_llm_error_falls_back_to_original(
    ingested: tuple[Container, DatasetRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """(d) wyjątek bramki LLM → pytanie oryginalne (bez propagacji błędu)."""
    container, ds = ingested
    spy = _ChatSpy(error=LLMUnavailable("LLM timeout"))
    seen = _install_chat(monkeypatch, container, spy)

    await container.retrieval.retrieve(principal_for(ds.tenant_id), _q(ds, cross_languages=("en",)))

    assert len(spy.calls) == 1
    assert seen == [_QUESTION]
