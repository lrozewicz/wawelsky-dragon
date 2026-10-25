"""Testy usługi czatów ChatsService na MariaDB (brief T2b, kontrakt C2, C2.1, C2.2, R1-R4, R6)."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.db.uow import transaction
from app.domain.chat.config import DEFAULT_PROMPT_CONFIG
from app.services.chats import (
    ChatInput,
    ChatListQuery,
    ChatsService,
    apply_prompt_defaults,
)
from tests.integration.chat.conftest import seed_chat, seed_user
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

# Przykład C2.2 dla (None, False) — złoto chat_session--01.
PROMPT_DEFAULTS_NO_DATASETS: dict[str, Any] = {
    "system": "",
    "prologue": "Hi! I'm your assistant. What can I do for you?",
    "parameters": [
        {"key": "knowledge", "optional": False},
        {"key": "date", "optional": True},
    ],
    "empty_response": "Sorry! No relevant content was found in the knowledge base!",
    "quote": True,
    "tts": False,
    "refine_multiturn": True,
}


def _svc(container: Container) -> ChatsService:
    """Usługa na kontenerze testowym."""
    return ChatsService(container)


def _query() -> ChatListQuery:
    """Parametry listy jak w briefie: pierwsza strona po create_time malejąco."""
    return ChatListQuery(
        page=1, page_size=30, orderby="create_time", desc=True, chat_id=None, name=None, keywords=""
    )


async def _model_id(sm: async_sessionmaker[AsyncSession], name: str) -> str:
    """Id modelu z tabeli models po nazwie (R1: 32 hex)."""
    async with transaction(sm) as session:
        raw = (
            await session.execute(text("SELECT id FROM models WHERE name = :n"), {"n": name})
        ).scalar_one()
    return str(raw)


async def _set_dataset(
    sm: async_sessionmaker[AsyncSession],
    dataset_id: str,
    *,
    chunk_count: int | None = None,
    name: str | None = None,
    tenant: str | None = None,
) -> None:
    """Podbija chunk_count, nazwę lub właściciela datasetu wprost SQL-em (brief T2b).

    ``tenant`` — seed_dataset tworzy za każdym razem nowego użytkownika; przykłady
    briefu z „dwoma własnymi datasetami" wymagają jednego właściciela.
    """
    sets: list[str] = []
    params: dict[str, Any] = {"id": dataset_id}
    if chunk_count is not None:
        sets.append("chunk_count = :chunks")
        params["chunks"] = chunk_count
    if name is not None:
        sets.append("name = :name")
        params["name"] = name
    if tenant is not None:
        sets.append("tenant_id = :tenant, created_by = :tenant")
        params["tenant"] = tenant
    async with transaction(sm) as session:
        await session.execute(
            # Składany SQL: wyłącznie stałe fragmenty SET z tego pliku (S608).
            text(f"UPDATE datasets SET {', '.join(sets)} WHERE id = :id"),  # noqa: S608
            params,
        )


async def test_create_defaults(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """create bez llm_id i dataset_ids: domyślny model, puste rerank, przykład C2.2 (brief)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    view = await _svc(container).create(principal, ChatInput({"name": "a", "dataset_ids": []}))
    chat_llm = await _model_id(sm, "fake-chat")
    assert view.llm_id == chat_llm
    assert view.tenant_llm_id == chat_llm
    assert view.rerank_id == ""
    assert view.tenant_rerank_id is None
    assert view.description == "A helpful Assistant"
    assert view.prompt_config == PROMPT_DEFAULTS_NO_DATASETS
    assert view.llm_setting == {}
    assert view.meta_data_filter == {}
    assert view.kb_names == []
    assert view.tenant_id == principal.user_id
    assert view.status == "1"
    assert view.create_time > 0


async def test_create_duplicate_name(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Drugi czat o tej samej nazwie (inna wielkość liter) → Conflict (brief, wiersz 2)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    await service.create(principal, ChatInput({"name": "a", "dataset_ids": []}))
    with pytest.raises(Conflict) as err:
        await service.create(principal, ChatInput({"name": "A", "dataset_ids": []}))
    assert err.value.message == "duplicated chat name in creating chat"


async def test_create_foreign_dataset(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """dataset_ids z cudzym datasetem → NotFound "You don't own the dataset" (brief, wiersz 3)."""
    dataset = await seed_dataset(sm)
    stranger = await seed_user(sm)
    with pytest.raises(NotFound) as err:
        await _svc(container).create(
            principal_for(stranger), ChatInput({"name": "a", "dataset_ids": [dataset.id]})
        )
    assert err.value.message == f"You don't own the dataset {dataset.id}"


async def test_create_dataset_without_parsed_file(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Własny dataset bez chunków (chunk_count 0) → Conflict (brief, wiersz 4)."""
    dataset = await seed_dataset(sm)
    with pytest.raises(Conflict) as err:
        await _svc(container).create(
            principal_for(dataset.tenant_id), ChatInput({"name": "a", "dataset_ids": [dataset.id]})
        )
    assert err.value.message == f"The dataset {dataset.id} doesn't own parsed file"


async def test_create_datasets_different_embedding(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dwa własne datasety z różnymi modelami embeddingu → Conflict (brief, wiersz 5)."""
    d1 = await seed_dataset(sm)
    d2 = await seed_dataset(sm, embedding_model="inny@x")
    # oba datasety jednego właściciela; nazwa w tym samym UPDATE (uq_datasets_tenant_name_ci)
    await _set_dataset(sm, d2.id, tenant=d1.tenant_id, name="Inny")
    await _set_dataset(sm, d1.id, chunk_count=1)
    await _set_dataset(sm, d2.id, chunk_count=1)
    with pytest.raises(Conflict) as err:
        await _svc(container).create(
            principal_for(d1.tenant_id),
            ChatInput({"name": "a", "dataset_ids": [d1.id, d2.id]}),
        )
    assert (
        err.value.message
        == "Datasets use different embedding models: ['fake-embed-1024', 'inny@x']"
    )


async def test_create_unknown_models(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieznany llm_id i nieznany rerank_id → Conflict z komunikatem upstream (brief, wiersz 6)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    with pytest.raises(Conflict) as err:
        await service.create(principal, ChatInput({"name": "a", "llm_id": "nie-ma"}))
    assert err.value.message == "`llm_id` nie-ma doesn't exist"
    with pytest.raises(Conflict) as err:
        await service.create(principal, ChatInput({"name": "b", "rerank_id": "nie-ma"}))
    assert err.value.message == "`rerank_id` nie-ma doesn't exist"


async def test_create_with_dataset_prompt_and_kb_names(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """create z datasetem: system z DEFAULT_PROMPT_CONFIG, kb_names z nazwą (brief, wiersz 7)."""
    dataset = await seed_dataset(sm)
    await _set_dataset(sm, dataset.id, chunk_count=1)
    view = await _svc(container).create(
        principal_for(dataset.tenant_id), ChatInput({"name": "a", "dataset_ids": [dataset.id]})
    )
    assert view.prompt_config["system"] == DEFAULT_PROMPT_CONFIG["system"]
    assert view.kb_names == [dataset.name]


async def test_apply_prompt_defaults_knowledge_parameters() -> None:
    """apply_prompt_defaults({"system":"{knowledge} x","parameters":[]}, True) (brief, wiersz 8)."""
    result = apply_prompt_defaults({"system": "{knowledge} x", "parameters": []}, True)
    assert result["parameters"] == [
        {"key": "knowledge", "optional": False},
        {"key": "date", "optional": True},
    ]


async def test_list_only_owner_chats(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """list zwykłego użytkownika: tylko własne czaty, total, nickname właściciela (brief)."""
    user = await seed_user(sm)
    other = await seed_user(sm)
    service = _svc(container)
    mine = await service.create(principal_for(user), ChatInput({"name": "a", "dataset_ids": []}))
    await service.create(principal_for(other), ChatInput({"name": "b", "dataset_ids": []}))
    views, total = await service.list(principal_for(user), _query())
    assert [view.id for view in views] == [mine.id]
    assert total == 1
    assert views[0].nickname == "seed"


async def test_list_superuser_sees_all_chats(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """list superusera: czaty obu właścicieli (brief, wiersz 10)."""
    first = await seed_user(sm)
    second = await seed_user(sm)
    service = _svc(container)
    chat_a = await service.create(principal_for(first), ChatInput({"name": "a", "dataset_ids": []}))
    chat_b = await service.create(
        principal_for(second), ChatInput({"name": "b", "dataset_ids": []})
    )
    views, total = await service.list(principal_for(first, superuser=True), _query())
    assert total == 2  # noqa: PLR2004 — dwóch seeded właścicieli (przykład briefu)
    assert {view.id for view in views} == {chat_a.id, chat_b.id}


async def test_get_permissions_and_missing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """get cudzego czatu → PermissionDenied; nieistniejącego → "Chat not found!" (brief)."""
    user = await seed_user(sm)
    stranger = await seed_user(sm)
    chat = await _svc(container).create(
        principal_for(user), ChatInput({"name": "a", "dataset_ids": []})
    )
    service = _svc(container)
    with pytest.raises(PermissionDenied):
        await service.get(principal_for(stranger), chat.id)
    with pytest.raises(NotFound) as err:
        await service.get(principal_for(user), "brak")
    assert err.value.message == "Chat not found!"


async def test_get_and_delete_with_non_ascii_id(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DEC-090 p. H: id spoza ASCII nie wywraca kolacji `chats.id` — `get`/`delete` → NotFound.

    Bez `CAST(:id AS BINARY)` MariaDB rzuca tu 1267 („Illegal mix of collations": kolumna
    `ascii_bin` vs parametr `utf8mb4_*`), a trasa oddawała `code 100` zamiast 102.
    """
    user = await seed_user(sm)
    service = _svc(container)
    principal = principal_for(user)
    with pytest.raises(NotFound) as err:
        await service.get(principal, "čhat-id")
    assert err.value.message == "Chat not found!"
    with pytest.raises(NotFound):
        await service.delete(principal, "ž")


async def test_update_merge_llm_setting(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """update llm_setting: merge=True scala, merge=False zastępuje (brief, wiersz 12)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    chat = await service.create(
        principal, ChatInput({"name": "a", "llm_setting": {"temperature": 0.1}})
    )
    merged = await service.update(
        principal, chat.id, ChatInput({"llm_setting": {"top_p": 0.5}}), merge=True
    )
    assert merged.llm_setting == {"temperature": 0.1, "top_p": 0.5}
    replaced = await service.update(
        principal, chat.id, ChatInput({"llm_setting": {"top_p": 0.5}}), merge=False
    )
    assert replaced.llm_setting == {"top_p": 0.5}


async def test_update_prompt_config_merges_without_defaults(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Po zmianie prompt_config update NIE woła apply_prompt_defaults (brief p. 6, upstream)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    chat = await service.create(principal, ChatInput({"name": "a", "dataset_ids": []}))
    updated = await service.update(
        principal, chat.id, ChatInput({"prompt_config": {"prologue": "Siema"}}), merge=True
    )
    assert updated.prompt_config["prologue"] == "Siema"
    assert updated.prompt_config["system"] == ""  # bez domyślnego systemu z create


async def test_update_name_conflicts(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """update na zajęta nazwę → Conflict; ta sama nazwa inną wielkością liter → OK (brief)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    chat_a = await service.create(principal, ChatInput({"name": "a", "dataset_ids": []}))
    chat_b = await service.create(principal, ChatInput({"name": "b", "dataset_ids": []}))
    with pytest.raises(Conflict) as err:
        await service.update(principal, chat_b.id, ChatInput({"name": "A"}), merge=False)
    assert err.value.message == "duplicated chat name"
    renamed = await service.update(principal, chat_a.id, ChatInput({"name": "A"}), merge=False)
    assert renamed.name == "A"


async def test_update_foreign_chat_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """update cudzego czatu → PermissionDenied (brief, wiersz 14; cel łatki chat-crud-owner)."""
    user = await seed_user(sm)
    stranger = await seed_user(sm)
    chat = await _svc(container).create(
        principal_for(user), ChatInput({"name": "a", "dataset_ids": []})
    )
    with pytest.raises(PermissionDenied):
        await _svc(container).update(
            principal_for(stranger), chat.id, ChatInput({"name": "x"}), merge=False
        )


async def test_delete_foreign_chat_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete cudzego czatu → PermissionDenied (brief, wiersz 14; cel łatki chat-crud-owner)."""
    user = await seed_user(sm)
    stranger = await seed_user(sm)
    chat = await _svc(container).create(
        principal_for(user), ChatInput({"name": "a", "dataset_ids": []})
    )
    with pytest.raises(PermissionDenied):
        await _svc(container).delete(principal_for(stranger), chat.id)


async def test_delete_own_chat(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """delete własnego czatu: znika (twarde usunięcie, R3)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    chat = await service.create(principal, ChatInput({"name": "a", "dataset_ids": []}))
    await service.delete(principal, chat.id)
    with pytest.raises(NotFound):
        await service.get(principal, chat.id)


async def test_delete_many_partial_and_duplicates(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete_many z duplikatem i brakiem: sukces częściowy, błędy id przed duplikatami (brief)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    kept = await service.create(principal, ChatInput({"name": "a", "dataset_ids": []}))
    result = await service.delete_many(principal, [kept.id, "brak", kept.id], False)
    assert result.success_count == 1
    assert result.errors == ["Chat(brak) not found.", f"Duplicate chat ids: {kept.id}"]
    assert result.nothing is False


async def test_delete_many_all_missing_raises(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete_many gdy żaden czat nie istnieje → NotFound ze złączonymi błędami (brief)."""
    user = await seed_user(sm)
    with pytest.raises(NotFound) as err:
        await _svc(container).delete_many(principal_for(user), ["brak"], False)
    assert err.value.message == "Chat(brak) not found."


async def test_delete_many_delete_all_and_nothing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """delete_many(None, True): usuwa wszystkie własne; bez czatów i False → nothing (brief)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    await service.create(principal, ChatInput({"name": "a", "dataset_ids": []}))
    await service.create(principal, ChatInput({"name": "b", "dataset_ids": []}))
    result = await service.delete_many(principal, None, True)
    assert result.success_count == 2  # noqa: PLR2004 — dwa czaty z przykładu briefu
    assert result.errors == []
    again = await service.delete_many(principal, None, True)
    assert again.nothing is True
    empty = await service.delete_many(principal, None, False)
    assert empty.nothing is True


async def test_create_llm_by_name_and_empty(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """create z llm_id nazwą → id modelu w widoku; llm_id "" → "" i tenant_llm_id None (R1)."""
    user = await seed_user(sm)
    principal = principal_for(user)
    service = _svc(container)
    by_name = await service.create(principal, ChatInput({"name": "a", "llm_id": "fake-chat"}))
    assert by_name.llm_id == await _model_id(sm, "fake-chat")
    cleared = await service.create(principal, ChatInput({"name": "b", "llm_id": ""}))
    assert cleared.llm_id == ""
    assert cleared.tenant_llm_id is None


async def test_get_chat_with_unknown_model_name(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Czat z llm_id nieobecnym w models → llm_id "" i tenant_llm_id None (R1)."""
    user = await seed_user(sm)
    row = await seed_chat(sm, user, [], llm_id="znik")
    view = await _svc(container).get(principal_for(user), row.id)
    assert view.llm_id == ""
    assert view.tenant_llm_id is None
    assert view.rerank_id == ""
    assert view.tenant_rerank_id is None


async def test_update_replaces_datasets(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """update z dataset_ids: walidacja C2.1 i replace wiązań, nowy widok (C2 update)."""
    d1 = await seed_dataset(sm)
    d2 = await seed_dataset(sm)
    await _set_dataset(sm, d2.id, tenant=d1.tenant_id, name="Inny")  # jeden właściciel
    await _set_dataset(sm, d1.id, chunk_count=1)
    await _set_dataset(sm, d2.id, chunk_count=1)
    principal = principal_for(d1.tenant_id)
    service = _svc(container)
    chat = await service.create(principal, ChatInput({"name": "a", "dataset_ids": [d1.id]}))
    updated = await service.update(
        principal, chat.id, ChatInput({"dataset_ids": [d2.id, d1.id]}), merge=False
    )
    assert updated.dataset_ids == [d2.id, d1.id]
    assert updated.kb_names == ["Inny", d1.name]
