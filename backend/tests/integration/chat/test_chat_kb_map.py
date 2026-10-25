"""Czat: katalog bazy w prompcie i pełna mapa przy pytaniu o bazę (K21 §3, §4; brief T5).

Sprawdza wpięcie sekcji w pipeline na realnej bazie (MariaDB) i atrapie LLM: zakres dokumentów
(datasety zapytania), format katalogu/mapy w polu `prompt`, pominięcie `empty_response` przy
pytaniu o bazę oraz wyłączanie sekcji zmiennymi `WD_CHAT_KB_*_TOKENS`.
"""

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import document_profiles as document_profiles_repo
from app.db.uow import transaction
from app.domain.chat.events import Final
from app.domain.chat.kb_overview import build_catalog_section
from app.domain.chat.prompts import citation_prompt
from app.llm.tokens import count_tokens
from app.prompts import load_prompt
from app.services import chat_pipeline
from app.services.chat import CompletionRequest
from tests.integration.chat.conftest import chat_with_doc, collect, seed_chat
from tests.integration.ingest.conftest import TIME_MS, seed_dataset
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_TOPIC_QUESTION = "Gdzie mieszkał smok wawelski?"
_OVERVIEW_QUESTION = "Co zawiera twoja baza wiedzy?"
# Pytanie o bazę ze słowami dokumentu (retrieval ma trafienia) — do testów bez mapy.
_OVERVIEW_WITH_TERMS = "Co zawiera twoja baza wiedzy o smoku wawelskim?"
_NO_HITS_QUESTION = "Prognoza pogody na weekend w górach?"

_OUTLINE = [
    {"level": 0, "title": "DZIAŁ I", "page": 1},
    {"level": 1, "title": "Podrozdział", "page": 2},
    {"level": 0, "title": "DZIAŁ II", "page": 5},
]


def _req(chat_id: str, question: str) -> CompletionRequest:
    return CompletionRequest(
        chat_id=chat_id,
        session_id=None,
        messages=({"role": "user", "content": question},),
    )


async def _add_profile(
    sm: async_sessionmaker[AsyncSession],
    document_id: str,
    dataset_id: str,
    outline: Sequence[dict[str, Any]] = _OUTLINE,
    *,
    source: str = "pdf_bookmarks",
) -> None:
    async with transaction(sm) as session:
        await document_profiles_repo.upsert(
            session,
            document_id=document_id,
            dataset_id=dataset_id,
            outline=list(outline),
            outline_source=source,
            now_ms=TIME_MS,
        )


async def _prompt(container: Container, tenant_id: str, chat_id: str, question: str) -> str:
    """Pole `prompt` finalnego zdarzenia (expose_prompt domyślnie True)."""
    stream = await container.chat.start(principal_for(tenant_id), _req(chat_id, question))
    finals = [event for event in await collect(stream) if isinstance(event, Final)]
    assert len(finals) == 1
    return finals[0].prompt


class _RecordingLLM:
    """Nakładka na bramkę LLM: deleguje 1:1, zapamiętując wiadomości strumienia czatu.

    Wzór podmiany `container.llm` z `use_scenario` (conftest); `__getattr__` wystarcza
    reszcie portu (m.in. `aclose`, którą fixture `container` woła przez atrybut).
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.stream_messages: list[list[dict[str, Any]]] = []

    async def chat_stream(
        self, model: Any, messages: Sequence[dict[str, Any]], **kwargs: Any
    ) -> AsyncIterator[Any]:
        self.stream_messages.append([dict(message) for message in messages])
        async for event in self._inner.chat_stream(model, messages, **kwargs):
            yield event

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def test_catalog_section_in_prompt_single_dataset(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Katalog: nagłówek `(<D>)`, bez `[nazwa bazy]`, działy poziomu 0; numeracja ID bez zmian."""
    chat, dataset, doc_id = await chat_with_doc(container, sm, _DOC)
    await _add_profile(sm, doc_id, dataset.id)
    prompt = await _prompt(container, chat.tenant_id, chat.id, _TOPIC_QUESTION)
    # Pole `prompt` ma "\n" zamienione na "  \n" (build_prompt_text) — asercje bez końca linii.
    assert "## Zawartość bazy wiedzy" in prompt
    assert "Masz dostęp do następujących dokumentów (1):" in prompt
    assert "- wawel.txt — działy: DZIAŁ I; DZIAŁ II" in prompt
    assert "[Korpus]" not in prompt
    assert "ID: 0" in prompt  # numeracja cytowań bez zmian (K21 §3 p. 2)


async def test_map_section_for_kb_overview_question(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Pytanie o bazę → pełna mapa w miejscu katalogu: nagłówek `### nazwa [baza]`, `(s. N)`."""
    chat, dataset, doc_id = await chat_with_doc(container, sm, _DOC)
    await _add_profile(sm, doc_id, dataset.id)
    prompt = await _prompt(container, chat.tenant_id, chat.id, _OVERVIEW_QUESTION)
    assert "## Zawartość bazy wiedzy (pełna mapa)" in prompt
    assert (
        "Użytkownik pyta o zawartość bazy. Wymień wszystkie dokumenty i ich działy "
        "z poniższej listy — nie ograniczaj się do fragmentów wiedzy." in prompt
    )
    assert "### wawel.txt [Korpus]" in prompt
    assert "- DZIAŁ I (s. 1)" in prompt
    assert "  - Podrozdział (s. 2)" in prompt
    assert "- DZIAŁ II (s. 5)" in prompt
    assert "Masz dostęp do następujących dokumentów" not in prompt  # katalog zastąpiony mapą


async def test_kb_overview_skips_empty_response_when_map_present(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Przy pytaniu o bazę i mapie ≥ 1 dokument skrót `empty_response` nie działa (K21 §4 p. 3)."""
    dataset = await seed_dataset(sm)
    doc_id = await ingest_text(container, dataset, "wawel.txt", _DOC)
    await _add_profile(sm, doc_id, dataset.id)
    chat = await seed_chat(
        sm,
        dataset.tenant_id,
        [dataset.id],
        similarity_threshold=0.99,
        vector_similarity_weight=0.0,
    )
    stream = await container.chat.start(
        principal_for(dataset.tenant_id), _req(chat.id, _OVERVIEW_QUESTION)
    )
    final = next(event for event in await collect(stream) if isinstance(event, Final))
    assert final.empty is False
    assert "## Zawartość bazy wiedzy (pełna mapa)" in final.prompt
    assert "No relevant content was found" not in final.final_answer

    stream2 = await container.chat.start(
        principal_for(dataset.tenant_id), _req(chat.id, _NO_HITS_QUESTION)
    )
    final2 = next(event for event in await collect(stream2) if isinstance(event, Final))
    assert final2.empty is True  # zwykłe pytanie nadal kończy się empty_response


async def test_map_disabled_falls_back_to_catalog(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    migrated_db: Settings,
    tmp_path: Path,
) -> None:
    """`WD_CHAT_KB_MAP_TOKENS=0`: pytanie o bazę dostaje zwykły katalog (K21 §4 p. 4)."""
    instance = Container(
        migrated_db.model_copy(
            update={"chat_kb_map_tokens": 0, "storage_root": str(tmp_path / "nokb")}
        )
    )
    await instance.start()
    try:
        chat, dataset, doc_id = await chat_with_doc(instance, instance.sessionmaker, _DOC)
        await _add_profile(instance.sessionmaker, doc_id, dataset.id)
        # Pytanie o bazę zawiera słowa dokumentu, więc retrieval ma trafienia (zwykła ścieżka).
        prompt = await _prompt(instance, chat.tenant_id, chat.id, _OVERVIEW_WITH_TERMS)
        assert "## Zawartość bazy wiedzy" in prompt
        assert "Masz dostęp do następujących dokumentów (1):" in prompt
        assert "(pełna mapa)" not in prompt
    finally:
        await instance.aclose()


async def test_catalog_and_map_disabled_when_tokens_zero(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    migrated_db: Settings,
    tmp_path: Path,
) -> None:
    """`WD_CHAT_KB_CATALOG_TOKENS=0` → brak sekcji w prompcie zwykłego pytania (K21 §3 p. 3)."""
    instance = Container(
        migrated_db.model_copy(
            update={"chat_kb_catalog_tokens": 0, "storage_root": str(tmp_path / "noctlg")}
        )
    )
    await instance.start()
    try:
        chat, dataset, doc_id = await chat_with_doc(instance, instance.sessionmaker, _DOC)
        await _add_profile(instance.sessionmaker, doc_id, dataset.id)
        prompt = await _prompt(instance, chat.tenant_id, chat.id, _TOPIC_QUESTION)
        assert "## Zawartość bazy wiedzy" not in prompt
    finally:
        await instance.aclose()


async def test_sessions_ask_has_no_kb_section(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """`/sessions/ask` (i Search — bez czatu) bez sekcji katalogu/mapy (K21 §4 p. 5)."""
    dataset = await seed_dataset(sm)
    doc_id = await ingest_text(container, dataset, "wawel.txt", _DOC)
    await _add_profile(sm, doc_id, dataset.id)
    stream = await container.chat.ask(
        principal_for(dataset.tenant_id), _OVERVIEW_QUESTION, [dataset.id]
    )
    final = next(event for event in await collect(stream) if isinstance(event, Final))
    assert "## Zawartość bazy wiedzy" not in final.prompt
    assert "(pełna mapa)" not in final.prompt


async def test_catalog_scope_excludes_foreign_dataset(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zakres katalogu = datasety zapytania; dokument z obcego datasetu nie trafia (§3 p. 1)."""
    outer = await seed_dataset(sm)
    foreign = await seed_dataset(sm)
    outer_doc = await ingest_text(container, outer, "outer.txt", _DOC)
    foreign_doc = await ingest_text(container, foreign, "foreign.txt", _DOC)
    await _add_profile(sm, outer_doc, outer.id)
    await _add_profile(sm, foreign_doc, foreign.id)
    chat = await seed_chat(
        sm, outer.tenant_id, [outer.id], similarity_threshold=0.0, vector_similarity_weight=0.0
    )
    prompt = await _prompt(container, outer.tenant_id, chat.id, _TOPIC_QUESTION)
    assert "outer.txt" in prompt
    assert "foreign.txt" not in prompt


async def test_catalog_two_datasets_uses_base_name(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dwie bazy: nagłówek `(<D> w <B> bazach)` i sufiks `[nazwa bazy]` (K21 §3 p. 2)."""
    first = await seed_dataset(sm)
    second = await seed_dataset(sm)
    first_doc = await ingest_text(container, first, "a.txt", _DOC)
    second_doc = await ingest_text(container, second, "b.txt", _DOC)
    await _add_profile(sm, first_doc, first.id)
    await _add_profile(sm, second_doc, second.id)
    chat = await seed_chat(
        sm,
        first.tenant_id,
        [first.id, second.id],
        similarity_threshold=0.0,
        vector_similarity_weight=0.0,
    )
    prompt = await _prompt(container, first.tenant_id, chat.id, _TOPIC_QUESTION)
    assert "Masz dostęp do następujących dokumentów (2 w 2 bazach):" in prompt
    assert "- a.txt [Korpus] — działy:" in prompt
    assert "- b.txt [Korpus] — działy:" in prompt


async def test_llm_system_message_has_section_after_citation_prompt(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Sekcja katalogu/mapy PO `citation_prompt`, na końcu systemu do LLM (K21 §3 p. 2).

    `citation_prompt` doklejany jest tylko przy blokach wiedzy (pytanie z trafieniami);
    pytanie o bazę bez słów dokumentu ma puste bloki — wtedy sekcja zamyka system sama.
    """
    chat, dataset, doc_id = await chat_with_doc(container, sm, _DOC)
    await _add_profile(sm, doc_id, dataset.id)
    container.llm = _RecordingLLM(container.llm)
    # Szablon cytowań z pliku promptów (chat_pipeline dokleja citation_prompt(load_prompt(...))).
    citation = citation_prompt(load_prompt("citation_prompt"))
    for question, section_header, last_line in (
        (_TOPIC_QUESTION, "## Zawartość bazy wiedzy\n", "- wawel.txt — działy: DZIAŁ I; DZIAŁ II"),
        (_OVERVIEW_QUESTION, "## Zawartość bazy wiedzy (pełna mapa)", "- DZIAŁ II (s. 5)"),
    ):
        await _prompt(container, chat.tenant_id, chat.id, question)
        system = container.llm.stream_messages[-1][0]["content"]
        assert section_header in system
        assert system.rstrip().endswith(last_line)  # sekcja na KOŃCU systemu (K21 §3 p. 2)
        if question == _TOPIC_QUESTION:  # bloki wiedzy obecne → cytowania w systemie
            assert citation in system
        if citation in system:
            assert system.index(citation) < system.index(section_header)


async def test_fit_messages_budget_reduced_by_section_tokens(
    container: Container, sm: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`fit_messages` dostaje budżet 0,95·max_tokens pomniejszony o tokeny sekcji (K21 §3 p. 2)."""
    chat, dataset, doc_id = await chat_with_doc(container, sm, _DOC)
    await _add_profile(sm, doc_id, dataset.id)

    async with transaction(sm) as session:
        catalog = await document_profiles_repo.list_catalog(session, [dataset.id])
    section = build_catalog_section(
        catalog,
        max_tokens=container.settings.chat_kb_catalog_tokens,
        count_tokens=count_tokens,
    )
    assert section  # sekcja istnieje — budżet ma być od niej pomniejszony
    real_fit = chat_pipeline.fit_messages
    recorded: dict[str, int] = {}

    def _spy(messages: Any, budget: int, **kwargs: Any) -> Any:
        recorded["budget"] = budget
        return real_fit(messages, budget, **kwargs)

    monkeypatch.setattr(chat_pipeline, "fit_messages", _spy)
    await _prompt(container, chat.tenant_id, chat.id, _TOPIC_QUESTION)
    # fake-chat bez max_tokens w bazie → domyślne 8192 w `_build_prompt` (chat_pipeline).
    assert recorded["budget"] == int(8192 * 0.95) - count_tokens(section)
