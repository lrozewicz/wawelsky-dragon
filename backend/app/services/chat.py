"""Usługa czatu (K4 §3.3, CONTRACT C12): walidacja, uprawnienia, sesja, start/complete_once.

``StreamIds`` pochodzi z ``app.domain.chat.events`` (jedna definicja, K4 §6 p. 5).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.db.repositories import assistant_access as assistant_access_repo
from app.db.repositories import chat_datasets as chat_datasets_repo
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories import chat_sessions as chat_sessions_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories.chat_messages import MessageRow
from app.db.repositories.chat_sessions import SessionRow
from app.db.repositories.chats import ChatRow
from app.db.repositories.datasets import DatasetRecord
from app.db.uow import transaction
from app.domain.chat.config import DEFAULT_DIRECT_CHAT_PROMPT_CONFIG, merge_prompt_config
from app.domain.chat.events import ChatEvent, Final, StreamIds
from app.domain.policy import Action, ResourceRef, require
from app.domain.policy.principal import Principal
from app.domain.retrieval.metadata import meta_data_filter_to_condition, parse_metadata_condition
from app.services.chat_pipeline import RunContext, RunState, run_events, safe_events

if TYPE_CHECKING:
    from app.core.container import Container
    from app.domain.retrieval.metadata import MetadataCondition
    from app.llm.types import ModelRef

# Komunikaty ``/sessions/ask`` v0.24 (upstream ``ask_about``, api/apps/sdk/session.py:836-843).
MSG_ASK_DATASET = "You don't own the dataset {dataset_id}."
MSG_ASK_NO_PARSED = "The dataset {dataset_id} doesn't own parsed file"


def _dataset_ref(record: DatasetRecord) -> ResourceRef:
    """ResourceRef datasetu (reguła jak ``DatasetService._ref`` i retrieval: READ)."""
    return ResourceRef(
        kind="dataset", owner_id=record.tenant_id, permission=record.permission, id=record.id
    )


def _chat_meta_filter(
    metadata: MetadataCondition | None, chat: ChatRow | None
) -> tuple[MetadataCondition | None, Mapping[str, Any] | None]:
    """Zawężenie z ``meta_data_filter`` czatu (K11 §10f p. 5, dialog_service.py:2061-2070).

    ``manual`` → warunek na metadanych dokumentów (zwracany jako ``metadata``); ``auto``/
    ``semi_auto`` → surowa specyfikacja dla kroku retrievalu (drugi element). Warunek żądania
    (niepuste ``metadata``) ma pierwszeństwo i zeruje filtr czatu.
    """
    if metadata is not None or chat is None or not chat.meta_data_filter:
        return metadata, None
    spec = chat.meta_data_filter
    if spec.get("method") in ("auto", "semi_auto"):
        return metadata, spec
    return meta_data_filter_to_condition(spec), None


@dataclass(frozen=True)
class CompletionRequest:
    """Żądanie uzupełnienia czatu (K4 §3.3 dosłownie)."""

    chat_id: str | None  # None → solo chat (06 §5.3)
    session_id: str | None  # None + chat_id → nowa sesja (§3.4)
    messages: tuple[Mapping[str, Any], ...]  # {"role","content","id"?}; ostatnia = user
    llm_id: str | None = None  # nadpisanie modelu (K5 §3.5)
    llm_setting: Mapping[str, Any] | None = None  # nadpisania temperature/top_p/max_tokens/…
    quote: bool = True
    reasoning: bool = False  # extra wg models.extra.supports_reasoning
    pass_all_history_messages: bool = False
    store_history_messages: bool = True  # False wymaga pass_all_history_messages=True
    doc_ids: tuple[str, ...] | None = None  # zawężenie retrievalu do dokumentów
    metadata_condition: Mapping[str, Any] | None = None
    user_id: str | None = None  # dla nowej sesji (hub-compat: e-mail); None → principal.email
    source: Literal["api", "ui", "openai"] = "api"


@dataclass(frozen=True)
class ChatStream:
    """Strumień zdarzeń z identyfikatorami ramek (K4 §3.3)."""

    ids: StreamIds
    events: AsyncIterator[ChatEvent]


@dataclass(frozen=True)
class CompletionResult:
    """Wynik nie-strumieniowy (K4 §3.3, complete_once)."""

    ids: StreamIds
    answer: str  # po finalize_answer, bez <think>
    thinking: str | None
    reference: Mapping[str, Any]
    prompt: str
    created_at: float
    usage: tuple[int, int]


class ChatService(Protocol):
    """Port usługi czatu (K4 §3.3)."""

    async def start(self, principal: Principal, req: CompletionRequest) -> ChatStream: ...

    async def complete_once(
        self, principal: Principal, req: CompletionRequest
    ) -> CompletionResult: ...

    async def ask(
        self, principal: Principal, question: str, dataset_ids: Sequence[str]
    ) -> ChatStream: ...


class DbChatService:
    """Czat na MariaDB (C12): walidacja i sesja przed strumieniem, pipeline w zdarzeniach."""

    def __init__(self, container: Container) -> None:
        """Zapamiętuje kontener; bez I/O — właściwość Container.chat może powstać przed start()."""
        self._container = container

    async def start(self, principal: Principal, req: CompletionRequest) -> ChatStream:
        """Walidacja, uprawnienia i utworzenie sesji PRZED zwróceniem; błędy → wyjątki WDError."""
        ctx = await self._prepare(principal, req)
        return ChatStream(ids=ctx.ids, events=safe_events(ctx))

    async def complete_once(self, principal: Principal, req: CompletionRequest) -> CompletionResult:
        """Pipeline bez ErrorEvent: wyjątki lecą do wołającego; wynik składany z Final (R0 p. 4)."""
        ctx = await self._prepare(principal, req)
        state = RunState()
        final: Final | None = None
        async for event in run_events(ctx, state):
            if isinstance(event, Final):
                final = event
        now_s = self._container.clock.now_ms() / 1000
        if final is None:  # pusta odpowiedź LLM (R0 p. 4)
            return CompletionResult(
                ids=ctx.ids,
                answer="",
                thinking=state.thinking_text,
                reference={"chunks": []},
                prompt="",
                created_at=now_s,
                usage=state.usage,
            )
        return CompletionResult(
            ids=ctx.ids,
            answer=final.final_answer,
            thinking=final.thinking,
            reference=final.reference,
            prompt=final.prompt,
            created_at=final.created_at if final.created_at is not None else now_s,
            usage=final.usage,
        )

    async def ask(
        self, principal: Principal, question: str, dataset_ids: Sequence[str]
    ) -> ChatStream:
        """Strumień odpowiedzi nad datasetami bez czatu (v0.24 ``/sessions/ask``, CONTRACT C4).

        Sprawdza dostęp do każdego datasetu (``require`` READ, jak retrieval) i posiadanie
        sparsowanego pliku, po czym buduje ``RunContext`` z ``chat=None`` (solo) i uruchamia
        pipeline; sesja/historia nie powstają (``store_history_messages=False``).
        """
        await self._load_ask_datasets(principal, dataset_ids)
        models = self._container.models
        if models is None:
            raise RuntimeError("container not started")
        model = await models.resolve(None, "chat")
        req = CompletionRequest(
            chat_id=None,
            session_id=None,
            messages=({"role": "user", "content": question},),
            store_history_messages=False,
            pass_all_history_messages=True,
            source="api",
        )
        ctx = RunContext(
            container=self._container,
            req=req,
            chat=None,
            # Upstream ``async_ask`` nie ma skrótu ``empty_response``: puste ``empty_response``
            # (wzór DEC-199/Search) → przy 0 trafieniach pipeline woła model, nie kończy pustką.
            prompt_config=merge_prompt_config({"empty_response": ""}),
            model=model,
            dataset_ids=tuple(dataset_ids),
            session_id=None,
            ids=StreamIds(message_id=str(uuid.uuid4()), session_id=None, chat_id=None),
            metadata=None,
        )
        return ChatStream(ids=ctx.ids, events=safe_events(ctx))

    async def _load_ask_datasets(
        self, principal: Principal, dataset_ids: Sequence[str]
    ) -> list[DatasetRecord]:
        """Datasety ask po kolei: brak/cudzy → PermissionDenied z id w ``details``; pusty → 102."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        async with transaction(sessionmaker) as session:
            records = [
                await datasets_repo.get_record(session, dataset_id) for dataset_id in dataset_ids
            ]
        checked: list[DatasetRecord] = []
        for dataset_id, record in zip(dataset_ids, records, strict=True):
            if record is None:
                raise PermissionDenied(
                    MSG_ASK_DATASET.format(dataset_id=dataset_id),
                    details={"dataset_id": dataset_id},
                )
            try:
                require(principal, Action.READ, _dataset_ref(record))
            except PermissionDenied:
                raise PermissionDenied(
                    MSG_ASK_DATASET.format(dataset_id=dataset_id),
                    details={"dataset_id": dataset_id},
                ) from None
            if record.chunk_count == 0:  # upstream: „The dataset <id> doesn't own parsed file”
                raise ValidationFailed(MSG_ASK_NO_PARSED.format(dataset_id=dataset_id))
            checked.append(record)
        return checked

    async def _prepare(self, principal: Principal, req: CompletionRequest) -> RunContext:
        """Kroki 1-9 z CONTRACT C12: walidacje, czat, sesja, doc_ids, model, sesja nowa, ids."""
        if self._container.sessionmaker is None:
            raise RuntimeError("container not started")
        if not req.messages or req.messages[-1].get("role") != "user":
            raise ValidationFailed("The last content of this conversation is not from user.")
        if not req.store_history_messages and not req.pass_all_history_messages:
            raise ValidationFailed(
                "`pass_all_history_messages` must be true when `store_history_messages` is false."
            )
        if req.session_id and not req.chat_id:
            raise ValidationFailed("`chat_id` is required when `session_id` is provided.")
        chat: ChatRow | None = None
        dataset_ids: tuple[str, ...] = ()
        outside: list[str] = []
        if req.chat_id is not None:
            chat, dataset_ids, outside = await self._load_chat(req.chat_id, req.doc_ids or ())
            require(principal, Action.USE, await self._chat_ref(chat))
        if req.chat_id is not None and req.session_id is not None:
            session_row = await self._load_session(req.session_id)
            if session_row.chat_id != req.chat_id:
                raise ValidationFailed("Session does not belong to this chat!")
            require(
                principal,
                Action.USE,
                ResourceRef(
                    kind="session",
                    owner_id=session_row.owner_id,
                    session_user_id=session_row.user_id,
                    id=session_row.id,
                ),
            )
        if outside:
            raise ValidationFailed(f"Documents {outside} are not in the chat's datasets.")
        metadata: MetadataCondition | None = None
        if req.metadata_condition is not None:
            metadata = parse_metadata_condition(req.metadata_condition)
        # Zawężenie z `meta_data_filter` czatu (K11 §10f p. 5, dialog_service.py:2061-2070):
        # `manual` → warunek na metadanych dokumentów; `auto`/`semi_auto` → model w kroku
        # retrievalu (przekazujemy surową specyfikację). Warunek żądania ma pierwszeństwo.
        metadata, meta_data_filter = _chat_meta_filter(metadata, chat)
        model = await self._resolve_model(req, chat)
        prompt_config = (
            merge_prompt_config(chat.prompt_config)
            if chat is not None
            else dict(DEFAULT_DIRECT_CHAT_PROMPT_CONFIG)
        )
        session_id: str | None = None
        if chat is not None:
            session_id = req.session_id or self._container.id_gen.new_id()
            # wiersz sesji tylko przy zapisie historii (C12 krok 8); store=False → brak zapisu
            if req.session_id is None and req.store_history_messages:
                await self._create_session(chat, prompt_config, req, principal, session_id)
        ids = StreamIds(message_id=str(uuid.uuid4()), session_id=session_id, chat_id=req.chat_id)
        return RunContext(
            container=self._container,
            req=req,
            chat=chat,
            prompt_config=prompt_config,
            model=model,
            dataset_ids=dataset_ids,
            session_id=session_id,
            ids=ids,
            metadata=metadata,
            meta_data_filter=meta_data_filter,
        )

    async def _load_chat(
        self, chat_id: str, doc_ids: tuple[str, ...]
    ) -> tuple[ChatRow, tuple[str, ...], list[str]]:
        """Czat, id datasetów i dokumenty spoza datasetów (C12 kroki 4 i 6, SQL w jednej turze)."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        async with transaction(sessionmaker) as session:
            chat = await chats_repo.get(session, chat_id)
            if chat is None:
                raise NotFound("Chat not found!")
            dataset_ids = tuple(await chat_datasets_repo.list_dataset_ids(session, chat_id))
            outside = await chat_datasets_repo.documents_outside(session, dataset_ids, doc_ids)
        return chat, dataset_ids, outside

    async def _chat_ref(self, chat: ChatRow) -> ResourceRef:
        """Referencja czatu z grantami (C6); sesja i miejsca UPDATE/DELETE jej nie używają."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        async with transaction(sessionmaker) as session:
            grants = await assistant_access_repo.emails_for_chat(session, chat.id)
        return ResourceRef("chat", chat.tenant_id, id=chat.id, chat_grant_emails=grants)

    async def _load_session(self, session_id: str) -> SessionRow:
        """Sesja po id; brak → NotFound (C12 krok 5)."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        async with transaction(sessionmaker) as session:
            session_row = await chat_sessions_repo.get(session, session_id)
        if session_row is None:
            raise NotFound("Session not found!")
        return session_row

    async def _resolve_model(self, req: CompletionRequest, chat: ChatRow | None) -> ModelRef:
        """Model czatu (C12 krok 7); podane llm_id bez trafienia → "Cannot use specified model"."""
        models = self._container.models
        if models is None:
            raise RuntimeError("container not started")
        ref = req.llm_id or (chat.llm_id if chat is not None else None)
        try:
            return await models.resolve(ref, "chat")
        except NotFound:
            if req.llm_id is not None:
                raise NotFound(f"Cannot use specified model {req.llm_id}.") from None
            raise

    async def _create_session(
        self,
        chat: ChatRow,
        prompt_config: dict[str, Any],
        req: CompletionRequest,
        principal: Principal,
        session_id: str,
    ) -> None:
        """Nowa sesja (C12 krok 8): wiersz chat_sessions + prologue (seq 0) gdy niepusty."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        now_ms = self._container.clock.now_ms()
        prologue = str(prompt_config.get("prologue") or "")
        name = next((str(m["content"]) for m in req.messages if m.get("role") == "user"), "")[:50]
        async with transaction(sessionmaker) as session:
            await chat_sessions_repo.insert(
                session,
                SessionRow(
                    id=session_id,
                    chat_id=chat.id,
                    name=name,
                    user_id=req.user_id or principal.email,
                    owner_id=principal.user_id,
                    source=req.source,
                    message_count=1 if prologue else 0,
                    create_time=now_ms,
                    update_time=now_ms,
                ),
            )
            if prologue:
                await chat_messages_repo.insert(
                    session,
                    MessageRow(
                        id=str(uuid.uuid4()),
                        session_id=session_id,
                        seq=0,
                        role="assistant",
                        content=prologue,
                        reference=None,
                        prompt_tokens=None,
                        completion_tokens=None,
                        created_at=now_ms / 1000,
                        create_time=now_ms,
                    ),
                )
