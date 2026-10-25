"""Usługa tras OpenAI-compat WD (brief OD p. 2-3, brief OC p. 2-3; port ``openai_api.py`` v0.27.2).

Zakres briefu OD: właściciel czatu i istnienie ``model`` (upstream :270-281) oraz model czatu
dla ``GET /openai/{chat_id}/models`` (rozszerzenie WD, 02-api §9). Zakres briefu OC: model
odpowiedzi completions na wyjściu jako ``models.id`` (R1, K11 §10a p. 4 — złoto
``openai_compat--02`` ma ``<ID:id#2>``); kształt OpenAI (``choices``/``usage``) składa
``app/api/ragflow/present/openai_chat.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.errors import NotFound, ValidationFailed
from app.db.repositories import assistant_access as assistant_access_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from app.domain.policy import Action, Principal, ResourceRef, can
from app.llm.registry import ModelRegistry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.container import Container

# Nazwa-placeholder z goldenu OpenAI-compat: „model” znaczy „model czatu” (upstream :277).
PLACEHOLDER_MODEL = "model"
# Wartości profilu zgodności (``app/api/ragflow/compat.py``); warstwa usług nie importuje API,
# więc porównuje je dosłownie (C0 p. 1, C0 p. 7).
PROFILE_V024 = "ragflow_0_24"
PROFILE_V027 = "ragflow_0_27"


class ChatNotOwned(NotFound):
    """Czat nie istnieje albo należy do kogoś innego — upstream zwraca ten sam komunikat."""

    def __init__(self, chat_id: str) -> None:
        super().__init__(f"You don't own the chat {chat_id}")


class UnknownModel(ValidationFailed):
    """Nieznany ``model`` żądania OpenAI-compat (upstream ``_validate_llm_id``, :48)."""

    def __init__(self, model: str) -> None:
        super().__init__(f"`llm_id` {model} doesn't exist")


class OpenAIService:
    """Czat (właściciel, model) dla tras ``/openai/{chat_id}/…``."""

    def __init__(self, container: Container) -> None:
        """Zapamiętuje kontener; bez I/O — usługa może powstać przed ``start()``."""
        self._container = container

    async def chat(self, principal: Principal, chat_id: str) -> ChatRow:
        """Wiersz czatu widoczny dla principala; brak lub cudzy → ``ChatNotOwned`` (:274-275).

        Dostęp z grantem (C6) — grant daje READ, tak jak właścicielowi.
        """
        async with transaction(self._sessionmaker()) as session:
            row = await chats_repo.get(session, chat_id)
        if row is None or not can(principal, Action.READ, await self._chat_ref(row)):
            raise ChatNotOwned(chat_id)
        return row

    async def _chat_ref(self, chat: ChatRow) -> ResourceRef:
        """Referencja czatu z grantami (C6); miejsca UPDATE/DELETE jej nie używają."""
        async with transaction(self._sessionmaker()) as session:
            grants = await assistant_access_repo.emails_for_chat(session, chat.id)
        return ResourceRef("chat", chat.tenant_id, id=chat.id, chat_grant_emails=grants)

    async def chat_model_name(self, principal: Principal, chat_id: str) -> str:
        """Nazwa modelu czatu dla ``GET /openai/{chat_id}/models`` (02-api §9)."""
        return (await self.chat(principal, chat_id)).llm_id

    async def check_model(self, model: str, profile: str = PROFILE_V027) -> None:
        """Istnienie modelu w rejestrze WD; placeholder i puste → bez sprawdzenia (:48, :277).

        Profil ``ragflow_0_24`` nie waliduje ``model`` (upstream v0.24 nie zna ``_validate_llm_id``;
        złoto ``openai_dify--09`` przyjmuje ``no-such-model`` i zwraca odpowiedź, nie kod 101).
        """
        if profile == PROFILE_V024 or not model or model == PLACEHOLDER_MODEL:
            return
        try:
            await self._models().resolve(model, "chat")
        except NotFound:
            raise UnknownModel(model) from None

    async def response_model(
        self, chat: ChatRow, requested: str, profile: str = PROFILE_V027
    ) -> str:
        """``model`` odpowiedzi: ``models.id`` modelu czatu (v0.27) albo nazwa z żądania (v0.24).

        Placeholder „model”/puste znaczy „model czatu” (upstream :270-271); id na wyjściu
        wg R1 (K11 §10a p. 4: złoto ``openai_compat--02`` ma ``<ID:id#2>``, nie nazwę).
        Nieznana nazwa jest odsiewana wcześniej przez ``check_model`` (kod 101) — w profilu
        ``ragflow_0_24`` zostaje bez zmian (upstream v0.24: ``req.get("model", "")``).
        """
        if profile == PROFILE_V024:
            return requested
        ref = chat.llm_id if requested in ("", PLACEHOLDER_MODEL) else requested
        model_id = (await self._models().resolve(ref, "chat")).id
        return model_id or ref  # model spoza rejestru (testy) nie ma id

    def _models(self) -> ModelRegistry:
        """Rejestr modeli kontenera; bez startu → RuntimeError (wzorzec ``services/chats.py``)."""
        models: ModelRegistry | None = self._container.models
        if models is None:
            raise RuntimeError("container not started")
        return models

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera; brak startu → RuntimeError (wzorzec ``services/chat.py``)."""
        sessionmaker: async_sessionmaker[AsyncSession] | None = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        return sessionmaker
