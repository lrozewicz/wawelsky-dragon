"""Usługa sesji czatu — CRUD sesji asystenta (kontrakt WP E1-9b: C3, R2, R5, R6, R11).

Port ``chat_api.py`` v0.27.2 (create/list/get/rename/delete_sessions); uprawnienia
wyłącznie przez ``app.domain.policy`` (K5 §7.2), komunikaty błędów dosłownie z C8.
Widoki niosą ``reference`` i ``id`` każdej wiadomości (R11 — dla E2-2).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.errors import Conflict, NotFound
from app.db.repositories import assistant_access as assistant_access_repo
from app.db.repositories import chat_messages as chat_messages_repo
from app.db.repositories import chat_sessions as chat_sessions_repo
from app.db.repositories import chats as chats_repo
from app.db.repositories.chat_messages import MessageRow
from app.db.repositories.chat_sessions import SessionRow
from app.db.repositories.chats import ChatRow
from app.db.uow import transaction
from app.domain.chat.config import merge_prompt_config
from app.domain.policy import Action, ResourceRef, can, require, visibility_filter
from app.domain.policy.principal import Principal
from app.services.chats import DeleteResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.container import Container

__all__ = ["MessageView", "SessionListQuery", "SessionView", "SessionsService"]


@dataclass(frozen=True)
class MessageView:
    """Wiadomość sesji (kontrakt C3); reference i id — R11 (E2-2).

    ``id`` pary user+assistant = id wiadomości asystenta (K4 §3.3, chat_api.py:1010);
    ``thumbup``/``feedback`` wypełnia ocena wiadomości (E2-1 chat_extras).
    """

    id: str
    seq: int
    role: str
    content: str
    reference: dict[str, Any] | None
    created_at: float
    thumbup: bool | None = None
    feedback: str | None = None


@dataclass(frozen=True)
class SessionView:
    """Widok sesji (kontrakt C3); avatar emitowany tylko przez GET jednej sesji."""

    id: str
    chat_id: str
    name: str
    user_id: str | None
    create_time: int
    update_time: int
    messages: list[MessageView]  # po seq
    avatar: str  # icon czatu ("" gdy brak)


@dataclass(frozen=True)
class SessionListQuery:
    """Parametry listy sesji (kontrakt C3)."""

    page: int
    page_size: int
    orderby: str
    desc: bool
    session_id: str | None
    name: str | None
    user_id: str | None


def _first_seq_of_pair(rows: list[MessageRow], message_id: str) -> int | None:
    """seq pierwszej wiadomości pary o danym id; None gdy brak (chat_api.py:1008).

    Upstream usuwa wpis o ``msg_id`` wraz z następnym (oba dzielą id); u nas para to
    wiersze ``user``(seq N) i ``assistant``(seq N+1) — start liczymy z obu stron.
    """
    for index, row in enumerate(rows):
        if row.id != message_id:
            continue
        if row.role == "user":
            return row.seq
        if index > 0 and rows[index - 1].role == "user":
            return rows[index - 1].seq
    return None


def _assistant_of_pair(rows: list[MessageRow], message_id: str) -> MessageRow | None:
    """Wiadomość asystenta o danym id (upstream ocenia wyłącznie rolę assistant; :1044)."""
    return next(
        (row for row in rows if row.id == message_id and row.role == "assistant"),
        None,
    )


class SessionsService:
    """CRUD sesji czatu (kontrakt C3); transakcje przez ``app.db.uow.transaction``."""

    def __init__(self, container: Container) -> None:
        """Zapamiętuje kontener; bez I/O — właściwość może powstać przed start()."""
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Sessionmaker kontenera; bez startu → RuntimeError (wzorzec app/services/chat.py)."""
        if self._container.sessionmaker is None:
            raise RuntimeError("container not started")
        return self._container.sessionmaker

    async def _load_chat(self, chat_id: str) -> ChatRow:
        """Czat po id; brak → NotFound("Chat not found!") (C8)."""
        async with transaction(self._sessionmaker()) as session:
            chat = await chats_repo.get(session, chat_id)
        if chat is None:
            raise NotFound("Chat not found!")
        return chat

    async def _chat_ref(self, chat: ChatRow) -> ResourceRef:
        """Referencja czatu z grantami (C6); miejsca UPDATE/DELETE jej nie używają."""
        async with transaction(self._sessionmaker()) as session:
            grants = await assistant_access_repo.emails_for_chat(session, chat.id)
        return ResourceRef("chat", chat.tenant_id, id=chat.id, chat_grant_emails=grants)

    async def ensure_owned(self, principal: Principal, chat_id: str) -> bool:
        """Czy czat istnieje i jest w zasięgu principala (``_ensure_owned_chat``, chat_api.py:190).

        Brak czatu i czat cudzy to u upstream ta sama odmowa (HTTP 200, code 109, ``data: false``;
        złoto ``chats__000…0__sessions/errors_access--46``), więc trasy sesji prezentują ją
        profilem swojej trasy — ``refuse`` woła się w trasie, nie tutaj (DEC-091 p. 1).
        Akcja ``USE`` z pełną referencją (granty C6): tego samego sprawdzenia używa ``create``.
        """
        async with transaction(self._sessionmaker()) as session:
            chat = await chats_repo.get(session, chat_id)
        if chat is None:
            return False
        return can(principal, Action.USE, await self._chat_ref(chat))

    async def _load_session(self, session_id: str) -> SessionRow:
        """Sesja po id; brak → NotFound("Session not found!") (C8)."""
        async with transaction(self._sessionmaker()) as session:
            found = await chat_sessions_repo.get(session, session_id)
        if found is None:
            raise NotFound("Session not found!")
        return found

    @staticmethod
    def _session_ref(s: SessionRow) -> ResourceRef:
        """Referencja sesji dla polityki (kontrakt C3)."""
        return ResourceRef(kind="session", owner_id=s.owner_id, session_user_id=s.user_id, id=s.id)

    @staticmethod
    def _message_view(m: MessageRow, message_id: str) -> MessageView:
        """Wiersz wiadomości → widok; ``message_id`` = id pary eksponowane w API."""
        return MessageView(
            id=message_id,
            seq=m.seq,
            role=m.role,
            content=m.content,
            reference=m.reference,
            created_at=m.created_at,
            thumbup=m.thumbup,
            feedback=m.feedback,
        )

    @classmethod
    def _messages(cls, rows: list[MessageRow]) -> list[MessageView]:
        """Wiersze wiadomości → widoki (R11: reference i id każdej wiadomości).

        Para user+assistant dzieli jedno id — to id asystenta (upstream zapisuje parę
        w jednym wierszu ``message``; u nas PK wymusza dwa wiersze — K4 §3.3).
        """
        views: list[MessageView] = []
        index = 0
        while index < len(rows):
            row = rows[index]
            nxt = rows[index + 1] if index + 1 < len(rows) else None
            if row.role == "user" and nxt is not None and nxt.role == "assistant":
                views.append(cls._message_view(row, nxt.id))
                views.append(cls._message_view(nxt, nxt.id))
                index += 2
            else:
                views.append(cls._message_view(row, row.id))
                index += 1
        return views

    @staticmethod
    def _view(chat: ChatRow, s: SessionRow, messages: list[MessageView]) -> SessionView:
        """Widok sesji z iconą czatu jako avatar (C3)."""
        return SessionView(
            id=s.id,
            chat_id=s.chat_id,
            name=s.name,
            user_id=s.user_id,
            create_time=s.create_time,
            update_time=s.update_time,
            messages=messages,
            avatar=chat.icon,
        )

    async def create(
        self, principal: Principal, chat_id: str, name: str, *, user_id: str | None = None
    ) -> SessionView:
        """Nowa sesja z prologue (C3 create, R5); sesja i wiadomość w jednej transakcji.

        ``user_id`` nadpisuje pole użytkownika sesji (profil 0.24 bierze je z ciała żądania,
        upstream ``create``); ``None`` → podmiot jak w 0.27. ``owner_id`` zawsze = podmiot.
        """
        chat = await self._load_chat(chat_id)
        require(principal, Action.USE, await self._chat_ref(chat))
        session_id = self._container.id_gen.new_id()
        now = self._container.clock.now_ms()
        prologue = str(merge_prompt_config(chat.prompt_config).get("prologue") or "")
        s_row = SessionRow(
            id=session_id,
            chat_id=chat.id,
            name=name,
            user_id=user_id if user_id is not None else principal.user_id,
            owner_id=principal.user_id,
            source="api",
            message_count=1,
            create_time=now,
            update_time=now,
        )
        m_row = MessageRow(
            id=self._container.id_gen.new_id(),
            session_id=session_id,
            seq=0,
            role="assistant",
            content=prologue,
            reference=None,
            prompt_tokens=None,
            completion_tokens=None,
            created_at=now / 1000,
            create_time=now,
        )
        async with transaction(self._sessionmaker()) as session:
            await chat_sessions_repo.insert(session, s_row)
            await chat_messages_repo.insert(session, m_row)
        return self._view(chat, s_row, self._messages([m_row]))

    async def get(self, principal: Principal, chat_id: str, session_id: str) -> SessionView:
        """Sesja z wiadomościami (C3 get): inny czat → Conflict (R2); avatar = icon czatu."""
        chat = await self._load_chat(chat_id)
        require(principal, Action.USE, await self._chat_ref(chat))
        s = await self._load_session(session_id)
        if s.chat_id != chat_id:
            raise Conflict("Session does not belong to this chat!")
        require(principal, Action.READ, self._session_ref(s))
        async with transaction(self._sessionmaker()) as session:
            messages = await chat_messages_repo.list_by_session(session, session_id)
        return self._view(chat, s, self._messages(messages))

    async def _load_for_messages(
        self, principal: Principal, chat_id: str, session_id: str
    ) -> tuple[ChatRow, SessionRow]:
        """Czat i sesja operacji na wiadomość; obcy czat/sesja → NotFound (chat_api.py:1008)."""
        chat = await self._load_chat(chat_id)
        require(principal, Action.USE, await self._chat_ref(chat))
        s = await self._load_session(session_id)
        if s.chat_id != chat_id:
            raise NotFound("Session not found!")
        require(principal, Action.UPDATE, self._session_ref(s))
        return chat, s

    async def _messages_of(self, session_id: str) -> list[MessageView]:
        """Świeże wiadomości sesji, po seq (C3)."""
        async with transaction(self._sessionmaker()) as session:
            return self._messages(await chat_messages_repo.list_by_session(session, session_id))

    async def delete_message(
        self, principal: Principal, chat_id: str, session_id: str, message_id: str
    ) -> SessionView:
        """DELETE wiadomości (C3): usuwa parę user+assistant; brak trafienia → bez zmian.

        Port ``chat_api.py:1000``: wpis o ``msg_id`` i następny znikają razem, licznik
        wiadomości sesji maleje o 2.
        """
        chat, s = await self._load_for_messages(principal, chat_id, session_id)
        async with transaction(self._sessionmaker()) as session:
            rows = await chat_messages_repo.list_by_session(session, session_id)
            first_seq = _first_seq_of_pair(rows, message_id)
            if first_seq is not None:
                await chat_messages_repo.delete_pair(session, session_id, first_seq)
                await chat_sessions_repo.bump(
                    session, session_id, added=-2, now_ms=self._container.clock.now_ms()
                )
        return self._view(chat, s, await self._messages_of(session_id))

    async def set_message_feedback(  # noqa: PLR0913 — sygnatura trasy (chat_id, session_id, msg_id…)
        self,
        principal: Principal,
        chat_id: str,
        session_id: str,
        message_id: str,
        *,
        thumbup: bool,
        feedback: str | None,
    ) -> SessionView:
        """PUT feedback (C3): ocena wiadomości asystenta pary; brak trafienia → bez zmian.

        Port ``chat_api.py:1025``: ``thumbup`` true czyści ``feedback``; false zapisuje nowy,
        a gdy nowy pusty — zostawia poprzedni.
        """
        chat, s = await self._load_for_messages(principal, chat_id, session_id)
        async with transaction(self._sessionmaker()) as session:
            rows = await chat_messages_repo.list_by_session(session, session_id)
            target = _assistant_of_pair(rows, message_id)
            if target is not None:
                stored = None if thumbup else (feedback or target.feedback)
                await chat_messages_repo.set_feedback(
                    session,
                    target.id,
                    thumbup=thumbup,
                    feedback=stored,
                    now_ms=self._container.clock.now_ms(),
                )
                await chat_sessions_repo.bump(
                    session, session_id, added=0, now_ms=self._container.clock.now_ms()
                )
        return self._view(chat, s, await self._messages_of(session_id))

    async def rename(
        self, principal: Principal, chat_id: str, session_id: str, name: str | None
    ) -> SessionView:
        """Zmiana nazwy (C3 rename): inny czat → NotFound; name None → bez zapisu; świeży widok."""
        chat = await self._load_chat(chat_id)
        require(principal, Action.USE, await self._chat_ref(chat))
        s = await self._load_session(session_id)
        if s.chat_id != chat_id:
            raise NotFound("Session not found!")
        require(principal, Action.UPDATE, self._session_ref(s))
        if name is not None:
            async with transaction(self._sessionmaker()) as session:
                await chat_sessions_repo.rename(
                    session, session_id, name, now_ms=self._container.clock.now_ms()
                )
        fresh = await self._load_session(session_id)
        async with transaction(self._sessionmaker()) as session:
            messages = await chat_messages_repo.list_by_session(session, session_id)
        return self._view(chat, fresh, self._messages(messages))

    async def delete_many(
        self, principal: Principal, chat_id: str, ids: list[str] | None, delete_all: bool
    ) -> DeleteResult:
        """Usuwanie masowe (C3): sukces częściowy → DeleteResult, 0 sukcesów → NotFound."""
        chat = await self._load_chat(chat_id)
        require(principal, Action.USE, await self._chat_ref(chat))
        if not ids:
            if delete_all is not True:
                return DeleteResult(0, [], True)
            vf = visibility_filter(principal, "session")
            owner_ids = None if vf.all else vf.owner_ids
            async with transaction(self._sessionmaker()) as session:
                ids = await chat_sessions_repo.list_ids(session, chat_id, owner_ids=owner_ids)
            if not ids:
                return DeleteResult(0, [], True)
        counts = Counter(ids)
        unique = list(dict.fromkeys(ids))
        duplicates = [f"Duplicate session ids: {sid}" for sid in unique if counts[sid] > 1]
        id_errors: list[str] = []
        success_count = 0
        async with transaction(self._sessionmaker()) as session:
            for sid in unique:
                s = await chat_sessions_repo.get(session, sid)
                if (
                    s is None
                    or s.chat_id != chat_id
                    or not can(principal, Action.DELETE, self._session_ref(s))
                ):
                    id_errors.append(f"The chat doesn't own the session {sid}")
                    continue
                await chat_sessions_repo.delete(session, sid)
                success_count += 1
        errors = id_errors + duplicates
        if success_count == 0 and errors:
            raise NotFound("; ".join(errors))
        return DeleteResult(success_count, errors, False)

    # ``list`` na końcu klasy: w sygnaturach metod zdefiniowanych PO niej mypy widzi tę metodę
    # pod nazwą ``list`` zamiast wbudowanego typu (np. ``ids: list[str]`` w delete_many).
    async def list(
        self, principal: Principal, chat_id: str, q: SessionListQuery
    ) -> list[SessionView]:
        """Lista sesji czatu wg widoczności (C3 list, R6); page_size 0 → [] bez zapytania (Q25)."""
        chat = await self._load_chat(chat_id)
        require(principal, Action.USE, await self._chat_ref(chat))
        if q.page_size == 0:
            return []
        vf = visibility_filter(principal, "session")
        owner_ids = None if vf.all else vf.owner_ids
        async with transaction(self._sessionmaker()) as session:
            rows = await chat_sessions_repo.list_page(
                session,
                chat_id,
                owner_ids=owner_ids,
                session_id=q.session_id,
                name=q.name,
                user_id=q.user_id,
                orderby=q.orderby,
                desc=q.desc,
                offset=(q.page - 1) * q.page_size,
                limit=q.page_size,
            )
            grouped = await chat_messages_repo.list_by_sessions(session, [s.id for s in rows])
        return [self._view(chat, s, self._messages(grouped.get(s.id, []))) for s in rows]
