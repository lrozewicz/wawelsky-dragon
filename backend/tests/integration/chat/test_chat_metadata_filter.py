"""`meta_data_filter` czatu w completions (K11 §10f p. 5; złoto `chats*/metadata_e6--46…50`).

Czat z `chats.meta_data_filter` (`method: manual`) zawęża zbiór dokumentów zapytania:
`--47` → odpowiedź i `reference` tylko z pasującego dokumentu; `--49/50` → filtr bez trafień
daje komunikat `empty_response` i puste `reference` (nie błąd).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from app.services.chat import CompletionRequest
from tests.integration.chat.conftest import seed_chat
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

_QUESTION = "smokwawelski"
_TEXT = "Smokwawelski mieszkał w jamie pod Wawelem."
_MANUAL_A = {
    "method": "manual",
    "logic": "and",
    "manual": [
        {"key": "author", "op": "=", "value": "A"},
        {"key": "year", "op": "=", "value": "2020"},
    ],
}
_MANUAL_Z = {"method": "manual", "manual": [{"key": "author", "op": "=", "value": "Z"}]}


def _req(chat_id: str) -> CompletionRequest:
    """CompletionRequest jednego pytania user (K4 §3.3)."""
    return CompletionRequest(
        chat_id=chat_id,
        session_id=None,
        messages=({"role": "user", "content": _QUESTION},),
        llm_id="fake-chat",
    )


async def _seed_docs_and_chat(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    meta_data_filter: dict,
) -> tuple[ChatRow, str, str]:
    """Dataset z dokumentami a={author A, year "2020"} i b={author B}; czat z filtrem.

    Czat w trybie termowym (bez wektorów, próg 0.0), jak ``chat_with_doc``.
    """
    ds = await seed_dataset(sm)
    doc_a = await ingest_text(container, ds, "a.txt", _TEXT)
    doc_b = await ingest_text(container, ds, "b.txt", _TEXT)
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE documents SET meta_fields = :m WHERE id = :id"),
            {"m": '{"author": "A", "year": "2020"}', "id": doc_a},
        )
        await session.execute(
            text("UPDATE documents SET meta_fields = :m WHERE id = :id"),
            {"m": '{"author": "B", "year": "2021"}', "id": doc_b},
        )
    chat = await seed_chat(
        sm,
        ds.tenant_id,
        [ds.id],
        similarity_threshold=0.0,
        vector_similarity_weight=0.0,
        meta_data_filter=meta_data_filter,
    )
    return chat, doc_a, doc_b


async def test_chat_manual_filter_narrows_reference(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Złoto --46/47: filtr manual author=A AND year="2020" → reference tylko dokumentu a."""
    chat, doc_a, doc_b = await _seed_docs_and_chat(container, sm, _MANUAL_A)
    result = await container.chat.complete_once(principal_for(chat.tenant_id), _req(chat.id))
    assert result.reference["total"] == 1
    assert [chunk["document_id"] for chunk in result.reference["chunks"]] == [doc_a]
    assert doc_b not in [chunk["document_id"] for chunk in result.reference["chunks"]]


async def test_chat_manual_filter_no_match_empty_response(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Złoto --49/50: filtr manual author=Z bez trafień → empty_response i puste reference."""
    chat, _, _ = await _seed_docs_and_chat(container, sm, _MANUAL_Z)
    result = await container.chat.complete_once(principal_for(chat.tenant_id), _req(chat.id))
    assert result.answer == "Sorry! No relevant content was found in the knowledge base!"
    assert result.reference["chunks"] == []
    assert result.reference["total"] == 0
