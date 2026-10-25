"""Usługa czatów — CRUD asystentów czatu (kontrakt WP E1-9b: C2, C2.1, C2.2, R1-R4, R6).

Port ``chat_api.py`` v0.27.2 (create/list/get/update/delete/delete_many); uprawnienia
wyłącznie przez ``app.domain.policy`` (K5 §7.2), komunikaty błędów dosłownie z C8.
Widok (ChatView), walidacja dataset_ids i domyślne prompt_config: ``app.services.chat_validation``
(rozbicie sankcjonowane briefem — limit 400 linii; nazwy importowalne także stąd).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final

from app.core.errors import Conflict, NotFound
from app.db.repositories import assistant_access as assistant_access_repo
from app.db.repositories import chat_datasets as chat_datasets_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from app.domain.policy import Action, ResourceRef, can, require, visibility_filter
from app.domain.policy.principal import Principal
from app.services import chat_recommendation
from app.services.chat_recommendation import _related_questions  # jawny re-eksport (testy)
from app.services.chat_validation import (
    ChatView,
    apply_prompt_defaults,
    chat_view,
    list_dataset_records,
    resolve_model_ids,
    validate_dataset_ids,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.container import Container
    from app.llm.registry import ModelRegistry
    from app.llm.types import ModelType

# Jawny re-eksport (mypy strict): widok i defaults żyją w chat_validation (limit 400 linii),
# a rekomendacje pytań w chat_recommendation.
__all__ = [
    "CHAT_INPUT_KEYS",
    "ChatInput",
    "ChatListQuery",
    "ChatView",
    "ChatsService",
    "DeleteResult",
    "_related_questions",
    "apply_prompt_defaults",
]

CHAT_INPUT_KEYS: Final = (
    "name",
    "icon",
    "description",
    "dataset_ids",
    "llm_id",
    "llm_setting",
    "prompt_config",
    "similarity_threshold",
    "vector_similarity_weight",
    "top_n",
    "top_k",
    "rerank_candidates_count",
    "rerank_id",
    "prompt_type",
    "language",
    "meta_data_filter",
)

# Klucze update wchodzące do chats.update bez przetwarzania (C2; dataset_ids i modele osobno).
_UPDATE_KEYS: Final = (
    "name",
    "icon",
    "description",
    "language",
    "prompt_type",
    "similarity_threshold",
    "vector_similarity_weight",
    "top_n",
    "top_k",
    "rerank_candidates_count",
    "meta_data_filter",
)


@dataclass(frozen=True)
class ChatInput:
    """Pola żądania: tylko klucze obecne w żądaniu, typy już sprawdzone w normalize (C2)."""

    fields: Mapping[str, Any]


@dataclass(frozen=True)
class ChatListQuery:
    """Parametry listy czatów (kontrakt C2)."""

    page: int
    page_size: int
    orderby: str
    desc: bool
    chat_id: str | None
    name: str | None
    keywords: str


@dataclass(frozen=True)
class DeleteResult:
    """Wynik usuwania masowego (R4): nothing=True = nic do zrobienia → trasa zwraca ok({})."""

    success_count: int
    errors: list[str]
    nothing: bool


class ChatsService:
    """CRUD asystentów czatu (kontrakt C2); transakcje przez ``app.db.uow.transaction``."""

    def __init__(self, container: Container) -> None:
        """Zapamiętuje kontener; bez I/O — właściwość może powstać przed start()."""
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Sessionmaker kontenera; bez startu → RuntimeError (wzorzec app/services/chat.py)."""
        if self._container.sessionmaker is None:
            raise RuntimeError("container not started")
        return self._container.sessionmaker

    def _models(self) -> ModelRegistry:
        """Rejestr modeli; bez startu → RuntimeError."""
        if self._container.models is None:
            raise RuntimeError("container not started")
        return self._container.models

    async def create(self, principal: Principal, inp: ChatInput) -> ChatView:
        """Tworzy asystenta (C2: dataset_ids → modele → domyślne → name_taken → insert → get)."""
        fields = inp.fields
        name = fields["name"]  # obecność i typ gwarantuje normalize (C4)
        dataset_ids: list[str] = []
        has_datasets = False
        if "dataset_ids" in fields:
            async with transaction(self._sessionmaker()) as session:
                dataset_ids = await validate_dataset_ids(session, principal, fields["dataset_ids"])
            has_datasets = bool(dataset_ids)
        llm_name = await self._model_name(fields.get("llm_id"), "chat", "llm_id")
        rerank_value = fields.get("rerank_id")
        rerank_name = (
            ""
            if rerank_value is None
            else await self._model_name(rerank_value, "rerank", "rerank_id")
        )
        prompt_config = apply_prompt_defaults(fields.get("prompt_config"), has_datasets)
        chat_id = self._container.id_gen.new_id()
        row = ChatRow(
            id=chat_id,
            tenant_id=principal.user_id,
            created_by=principal.user_id,
            name=name,
            language=fields.get("language", "English"),
            llm_id=llm_name,
            llm_setting=fields.get("llm_setting", {}),
            prompt_config=prompt_config,
            similarity_threshold=fields.get("similarity_threshold", 0.1),
            vector_similarity_weight=fields.get("vector_similarity_weight", 0.3),
            top_n=fields.get("top_n", 6),
            top_k=fields.get("top_k", 1024),
            rerank_candidates_count=fields.get("rerank_candidates_count", 64),
            rerank_id=rerank_name,
            meta_data_filter=fields.get("meta_data_filter"),
            status="1",
            description=fields.get("description", "A helpful Assistant"),
            icon=fields.get("icon", ""),
            prompt_type=fields.get("prompt_type", "simple"),
            do_refer="1",
        )
        async with transaction(self._sessionmaker()) as session:
            if await chats_repo.name_taken(session, principal.user_id, name):
                raise Conflict("duplicated chat name in creating chat")
            await chats_repo.insert(session, row, now_ms=self._container.clock.now_ms())
            await chat_datasets_repo.insert_many(session, chat_id, dataset_ids)
        return await self._detail_view(await self._load(chat_id))

    async def get(self, principal: Principal, chat_id: str) -> ChatView:
        """Widok czatu (C2 get): brak → NotFound, dostęp → require(READ z grantami, C6)."""
        chat = await self._load(chat_id)
        require(principal, Action.READ, await self._chat_ref(chat))
        return await self._detail_view(chat)

    async def _chat_ref(self, chat: ChatRow) -> ResourceRef:
        """Referencja czatu z grantami (C6); miejsca UPDATE/DELETE jej nie używają."""
        async with transaction(self._sessionmaker()) as session:
            grants = await assistant_access_repo.emails_for_chat(session, chat.id)
        return ResourceRef("chat", chat.tenant_id, id=chat.id, chat_grant_emails=grants)

    async def ensure_owned(self, principal: Principal, chat_id: str) -> bool:
        """Czy czat istnieje i należy do tenanta principala (upstream ``_ensure_owned_chat``).

        Port ``chat_api.py:188``: brak czatu i czat cudzy to u upstream ta sama odmowa
        (HTTP 200, code 109, ``data: false``) — trasy PUT/PATCH czatu prezentują ją tą kopertą.
        """
        async with transaction(self._sessionmaker()) as session:
            chat = await chats_repo.get(session, chat_id)
        return chat is not None and can(
            principal, Action.UPDATE, ResourceRef(kind="chat", owner_id=chat.tenant_id, id=chat.id)
        )

    async def recommend_questions(
        self,
        question: str,
        *,
        model_id: str | None = None,
        llm_setting: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Pytania pokrewne z modelu czatu tenanta (chat_api.py:1202).

        Obsługuje kanoniczną trasę ``/chat/recommendation`` i alias
        ``/sessions/related_questions`` (backward_compat.py:480); ``model_id`` i ``llm_setting``
        pochodzą z ``search_config`` wyszukiwarki (T4), a ich brak zostawia zachowanie
        bez zmian (model domyślny tenanta, parametry ``_RELATED_DEFAULTS``).
        """
        return await chat_recommendation.recommend_questions(
            self._container, question, model_id=model_id, llm_setting=llm_setting
        )

    async def update(
        self, principal: Principal, chat_id: str, inp: ChatInput, *, merge: bool
    ) -> ChatView:
        """Aktualizacja (C2 update): PUT merge=False, PATCH merge=True; bez defaults promptu."""
        fields = inp.fields
        current = await self._load(chat_id)
        require(principal, Action.UPDATE, ResourceRef("chat", current.tenant_id, id=current.id))
        dataset_ids: list[str] | None = None
        if "dataset_ids" in fields:
            async with transaction(self._sessionmaker()) as session:
                dataset_ids = await validate_dataset_ids(session, principal, fields["dataset_ids"])
        updates: dict[str, Any] = {key: fields[key] for key in _UPDATE_KEYS if key in fields}
        if "llm_id" in fields:
            value = fields["llm_id"]
            updates["llm_id"] = "" if not value else await self._model_name(value, "chat", "llm_id")
        if "rerank_id" in fields:
            value = fields["rerank_id"]
            updates["rerank_id"] = (
                "" if not value else await self._model_name(value, "rerank", "rerank_id")
            )
        if "llm_setting" in fields:
            new_setting = fields["llm_setting"]
            updates["llm_setting"] = (
                {**current.llm_setting, **new_setting} if merge else new_setting
            )
        if "prompt_config" in fields:
            new_config = fields["prompt_config"]
            updates["prompt_config"] = (
                {**current.prompt_config, **new_config} if merge else new_config
            )
        name = fields.get("name")
        async with transaction(self._sessionmaker()) as session:
            if (
                name is not None
                and str(name).lower() != current.name.lower()
                and await chats_repo.name_taken(
                    session, principal.user_id, name, exclude_id=chat_id
                )
            ):
                raise Conflict("duplicated chat name")
            if dataset_ids is not None:
                await chat_datasets_repo.replace(session, chat_id, dataset_ids)
            await chats_repo.update(
                session, chat_id, updates, now_ms=self._container.clock.now_ms()
            )
        return await self._detail_view(await self._load(chat_id))

    async def delete(self, principal: Principal, chat_id: str) -> None:
        """Twarde usunięcie czatu (C2 delete, R3); kaskada FK czyści tabele powiązane."""
        chat = await self._load(chat_id)
        require(
            principal, Action.DELETE, ResourceRef(kind="chat", owner_id=chat.tenant_id, id=chat.id)
        )
        async with transaction(self._sessionmaker()) as session:
            await chats_repo.delete(session, chat_id)

    async def delete_many(
        self, principal: Principal, ids: list[str] | None, delete_all: bool
    ) -> DeleteResult:
        """Usuwanie masowe (C2, R4): sukces częściowy → DeleteResult, 0 sukcesów → NotFound."""
        if not ids:
            if delete_all is not True:
                return DeleteResult(0, [], True)
            async with transaction(self._sessionmaker()) as session:
                ids = await chats_repo.list_ids_by_owner(session, principal.user_id)
            if not ids:
                return DeleteResult(0, [], True)
        counts = Counter(ids)
        unique = list(dict.fromkeys(ids))
        duplicates = [f"Duplicate chat ids: {cid}" for cid in unique if counts[cid] > 1]
        id_errors: list[str] = []
        success_count = 0
        async with transaction(self._sessionmaker()) as session:
            for cid in unique:
                chat = await chats_repo.get(session, cid)
                if chat is None or not can(
                    principal,
                    Action.DELETE,
                    ResourceRef(kind="chat", owner_id=chat.tenant_id, id=chat.id),
                ):
                    id_errors.append(f"Chat({cid}) not found.")
                    continue
                await chats_repo.delete(session, cid)
                success_count += 1
        errors = id_errors + duplicates
        if success_count == 0 and errors:
            raise NotFound("; ".join(errors))
        return DeleteResult(success_count, errors, False)

    # ``list`` na końcu klasy: metody PO niej widziałyby ``list`` jako tę metodę (mypy).
    async def list(self, principal: Principal, q: ChatListQuery) -> tuple[list[ChatView], int]:
        """Lista czatów wg widoczności (C2 list, R6); nickname/avatar i datasety w widoku."""
        async with transaction(self._sessionmaker()) as session:
            granted = await assistant_access_repo.chat_ids_for_email(session, principal.email)
            vf = visibility_filter(principal, "chat", granted)
            rows, total = await chats_repo.list_page(
                session,
                owner_ids=None if vf.all else vf.owner_ids,
                granted_ids=vf.granted_ids,
                chat_id=q.chat_id,
                name=q.name,
                keywords=q.keywords,
                orderby=q.orderby,
                desc=q.desc,
                offset=(q.page - 1) * q.page_size,
                limit=q.page_size,
            )
            names = await chat_datasets_repo.names_by_chat(session, [r.chat.id for r in rows])
            datasets = await list_dataset_records(session, names)  # pole ``datasets`` listy v0.24
        model_ids = await resolve_model_ids(self._models(), [r.chat for r in rows])
        views = [
            chat_view(
                r.chat,
                model_ids=model_ids,
                bindings=names.get(r.chat.id, []),
                nickname=r.nickname,
                tenant_avatar=r.avatar,
            )
            for r in rows
        ]
        return [replace(v, datasets=datasets.get(v.id, ())) for v in views], total

    async def _load(self, chat_id: str) -> ChatRow:
        """Czat po id; brak → NotFound("Chat not found!") (C8)."""
        async with transaction(self._sessionmaker()) as session:
            chat = await chats_repo.get(session, chat_id)
        if chat is None:
            raise NotFound("Chat not found!")
        return chat

    async def _detail_view(self, chat: ChatRow) -> ChatView:
        """Widok szczegółu (get/create/update): dataset_ids/kb_names z bazy, nickname="" (C2)."""
        async with transaction(self._sessionmaker()) as session:
            names = await chat_datasets_repo.names_by_chat(session, [chat.id])
        model_ids = await resolve_model_ids(self._models(), [chat])
        return chat_view(
            chat,
            model_ids=model_ids,
            bindings=names.get(chat.id, []),
            nickname="",
            tenant_avatar=None,
        )

    async def _model_name(self, value: Any, model_type: ModelType, field: str) -> str:
        """Nazwa modelu do zapisu (C2): "" → ""; None → domyślny; brak trafienia → Conflict."""
        if value == "":
            return ""
        try:
            return (await self._models().resolve(value, model_type)).name
        except NotFound:
            if value is None:
                return ""
            raise Conflict(f"`{field}` {value} doesn't exist") from None
